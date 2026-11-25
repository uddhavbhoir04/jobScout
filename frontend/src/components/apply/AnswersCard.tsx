"use client";

import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { api, type ApplyAnswers, type ApplySettings } from "@/lib/api";
import { Button, Card, CardHeader, ErrorNote, Input, Label, Notice, Spinner } from "../ui";

// The answers sheet used for screening questions, learned answers, and the daily limit.

type YesNo = "" | "yes" | "no";
const toYesNo = (v: boolean | null | undefined): YesNo => (v === true ? "yes" : v === false ? "no" : "");
const fromYesNo = (v: YesNo): boolean | null => (v === "yes" ? true : v === "no" ? false : null);
const numOrNull = (v: string): number | null => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));

type Form = {
  notice: string;
  currentCtc: string;
  expectedCtc: string;
  totalExp: string;
  skills: { skill: string; years: string }[];
  relocate: YesNo;
  authorized: YesNo;
  sponsorship: YesNo;
  phone: string;
  city: string;
  linkedin: string;
  portfolio: string;
  custom: { q: string; a: string }[];
  dailyCap: string;
};

function toForm(s: ApplySettings): Form {
  const a = s.answers;
  return {
    notice: a.notice_period_days?.toString() ?? "",
    currentCtc: a.current_ctc ?? "",
    expectedCtc: a.expected_ctc ?? "",
    totalExp: a.total_experience_years?.toString() ?? "",
    skills: Object.entries(a.skills_experience ?? {}).map(([skill, years]) => ({ skill, years: String(years) })),
    relocate: toYesNo(a.relocate),
    authorized: toYesNo(a.authorized_to_work),
    sponsorship: toYesNo(a.needs_sponsorship),
    phone: a.phone ?? "",
    city: a.city ?? "",
    linkedin: a.linkedin_url ?? "",
    portfolio: a.portfolio_url ?? "",
    custom: a.custom ?? [],
    dailyCap: String(s.daily_cap),
  };
}

function toAnswers(f: Form): ApplyAnswers {
  return {
    notice_period_days: numOrNull(f.notice),
    current_ctc: f.currentCtc || null,
    expected_ctc: f.expectedCtc || null,
    total_experience_years: numOrNull(f.totalExp),
    skills_experience: Object.fromEntries(
      f.skills.filter((s) => s.skill.trim() && numOrNull(s.years) !== null).map((s) => [s.skill.trim(), Number(s.years)]),
    ),
    relocate: fromYesNo(f.relocate),
    authorized_to_work: fromYesNo(f.authorized),
    needs_sponsorship: fromYesNo(f.sponsorship),
    phone: f.phone || null,
    city: f.city || null,
    linkedin_url: f.linkedin || null,
    portfolio_url: f.portfolio || null,
    custom: f.custom.filter((c) => c.q.trim() && c.a.trim()),
  };
}

export function AnswersCard({ settings, isPaid, onSaved }: { settings: ApplySettings; isPaid: boolean; onSaved: (s: ApplySettings) => void }) {
  const [f, setF] = useState<Form>(() => toForm(settings));
  const [learned, setLearned] = useState<Record<string, string>>(settings.learned);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      const b64 = await new Promise<string>((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
        r.onerror = () => reject(new Error("Could not read the file."));
        r.readAsDataURL(file);
      });
      onSaved(await api<ApplySettings>("/api/apply/resume", {
        method: "POST",
        body: JSON.stringify({ filename: file.name, content_base64: b64 }),
      }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
    }
  };
  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setSaved(false);
    setF((p) => ({ ...p, [k]: v }));
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const s = await api<ApplySettings>("/api/apply/settings", {
        method: "PUT",
        body: JSON.stringify({ answers: toAnswers(f), learned, daily_cap: Math.max(1, Math.min(50, Number(f.dailyCap) || 25)) }),
      });
      onSaved(s);
      setF(toForm(s));
      setLearned(s.learned);
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const yesNo = (id: string, label: string, k: "relocate" | "authorized" | "sponsorship") => (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <select id={id} value={f[k]} onChange={(e) => set(k, e.target.value as YesNo)}
        className="h-9 w-full rounded-md border border-line bg-surface px-2.5 text-sm text-ink">
        <option value="">Not set</option>
        <option value="yes">Yes</option>
        <option value="no">No</option>
      </select>
    </div>
  );

  const field = (id: string, label: string, k: keyof Form, props: Record<string, unknown> = {}) => (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={f[k] as string} onChange={(e) => set(k, e.target.value as never)} {...props} />
    </div>
  );

  const learnedEntries = Object.entries(learned);

  return (
    <form onSubmit={save} className="space-y-6">
      <Card>
        <CardHeader
          title="Your CV"
          subtitle={isPaid
            ? "Screening questions your answers below don't cover are answered from it by the AI, only when it's sure. Your phone and profile links are read from it too."
            : "Your phone and profile links are read from it. AI answers from the CV are on the paid plan."}
        />
        <div className="flex flex-wrap items-center gap-3 px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-ink">{settings.resume_filename ?? "No CV uploaded"}</div>
            <div className="text-xs text-zinc-500">
              {!settings.resume_filename
                ? "PDF or Word, up to 5 MB."
                : settings.resume_chars > 0
                  ? `${settings.resume_chars.toLocaleString()} characters read.`
                  : "No text could be read from it (a scanned PDF?). Upload a text PDF or Word file."}
            </div>
          </div>
          <input ref={fileRef} type="file" accept=".pdf,.doc,.docx" className="hidden" onChange={upload} />
          <Button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? <Spinner /> : null} {settings.resume_filename ? "Replace" : "Upload CV"}
          </Button>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Your answers"
          subtitle={`Used for screening questions. ${isPaid ? "Anything not covered here is answered by the AI from your resume, only when it's sure." : "Questions not covered here leave the job for you (AI answers are on the paid plan)."}`}
        />
        <div className="grid gap-4 px-5 py-5 sm:grid-cols-2">
          {field("ans-notice", "Notice period (days, 0 = immediate)", "notice", { type: "number", min: 0, max: 365 })}
          {field("ans-total", "Total experience (years)", "totalExp", { type: "number", min: 0, max: 60, step: 0.5 })}
          {field("ans-cctc", "Current CTC", "currentCtc", { placeholder: "12 LPA" })}
          {field("ans-ectc", "Expected CTC", "expectedCtc", { placeholder: "18 LPA" })}
          {field("ans-phone", "Phone", "phone", { placeholder: "+91 98765 43210" })}
          {field("ans-city", "Current city", "city", { placeholder: "Pune" })}
          {field("ans-linkedin", "LinkedIn URL", "linkedin")}
          {field("ans-portfolio", "Portfolio / GitHub URL", "portfolio")}
          {yesNo("ans-relocate", "Willing to relocate?", "relocate")}
          {yesNo("ans-auth", "Authorized to work in India?", "authorized")}
          {yesNo("ans-sponsor", "Need visa sponsorship?", "sponsorship")}
        </div>

        <div className="border-t border-line px-5 py-5">
          <Label hint="“Years of experience with …” questions">Experience per skill</Label>
          <div className="space-y-2">
            {f.skills.map((s, i) => (
              <div key={i} className="flex gap-2">
                <Input aria-label="Skill" placeholder="python" value={s.skill}
                  onChange={(e) => set("skills", f.skills.map((x, j) => (j === i ? { ...x, skill: e.target.value } : x)))} />
                <Input aria-label="Years" type="number" min={0} max={60} step={0.5} placeholder="years" value={s.years} className="w-24"
                  onChange={(e) => set("skills", f.skills.map((x, j) => (j === i ? { ...x, years: e.target.value } : x)))} />
                <Button type="button" variant="ghost" size="sm" onClick={() => set("skills", f.skills.filter((_, j) => j !== i))}>Remove</Button>
              </div>
            ))}
            <Button type="button" size="sm" onClick={() => set("skills", [...f.skills, { skill: "", years: "" }])}>Add skill</Button>
          </div>
        </div>

        <div className="border-t border-line px-5 py-5">
          <Label hint="Matched on the question's wording">Other questions</Label>
          <div className="space-y-2">
            {f.custom.map((c, i) => (
              <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                <Input aria-label="Question" placeholder="Why do you want to join us?" value={c.q}
                  onChange={(e) => set("custom", f.custom.map((x, j) => (j === i ? { ...x, q: e.target.value } : x)))} />
                <Input aria-label="Answer" placeholder="Your answer" value={c.a}
                  onChange={(e) => set("custom", f.custom.map((x, j) => (j === i ? { ...x, a: e.target.value } : x)))} />
                <Button type="button" variant="ghost" size="sm" onClick={() => set("custom", f.custom.filter((_, j) => j !== i))}>Remove</Button>
              </div>
            ))}
            <Button type="button" size="sm" onClick={() => set("custom", [...f.custom, { q: "", a: "" }])}>Add question</Button>
          </div>
        </div>

      </Card>

      <Card>
        <CardHeader title="Learned answers" subtitle="Answers given on earlier applications, reused for the same question. Edit or remove any." />
        {learnedEntries.length === 0 ? (
          <p className="px-5 py-5 text-sm text-zinc-500">None yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {learnedEntries.map(([q, a]) => (
              <li key={q} className="grid items-center gap-2 px-5 py-2.5 sm:grid-cols-[1fr_1fr_auto]">
                <span className="text-[13px] text-zinc-700">{q}</span>
                <Input aria-label={`Answer to ${q}`} value={a} onChange={(e) => { setSaved(false); setLearned({ ...learned, [q]: e.target.value }); }} />
                <Button type="button" variant="ghost" size="sm" onClick={() => { setSaved(false); setLearned(Object.fromEntries(learnedEntries.filter(([k]) => k !== q))); }}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader title="Daily limit" subtitle="Per site. Applying a lot in one day is what gets accounts restricted." />
        <div className="flex items-end gap-3 px-5 py-5">
          <div>
            <Label htmlFor="ans-cap" hint="1–50">Applications per day</Label>
            <Input id="ans-cap" type="number" min={1} max={50} value={f.dailyCap} className="w-24" onChange={(e) => set("dailyCap", e.target.value)} />
          </div>
          <p className="pb-2 text-xs text-zinc-500">
            Today: LinkedIn {settings.applied_today.linkedin} · Naukri {settings.applied_today.naukri} · Indeed {settings.applied_today.indeed}
          </p>
        </div>
      </Card>

      <ErrorNote message={error} />
      {saved && <Notice tone="success">Saved.</Notice>}
      <Button type="submit" variant="primary" disabled={saving}>
        {saving ? <Spinner className="border-white/40 border-t-white" /> : null} Save answers
      </Button>
    </form>
  );
}
