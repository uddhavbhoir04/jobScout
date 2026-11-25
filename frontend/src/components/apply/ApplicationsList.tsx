"use client";

import { useCallback, useEffect, useState } from "react";
import { api, timeAgo, type Application, type ApplyStatus, type Page } from "@/lib/api";
import { Badge, Button, buttonClass, Card, cn, EmptyState, Segmented, type Tone } from "../ui";
import { SITE_NAME } from "./ApplyPanel";

export const STATUS: Record<ApplyStatus, { label: string; tone: Tone }> = {
  applied: { label: "Applied", tone: "green" },
  dry_run: { label: "Dry run", tone: "blue" },
  needs_you: { label: "Needs you", tone: "amber" },
  skipped: { label: "Skipped", tone: "neutral" },
  failed: { label: "Failed", tone: "red" },
};

type Filter = "all" | ApplyStatus;

export function ApplicationsList({ refreshKey, onError }: { refreshKey: number; onError: (m: string) => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [data, setData] = useState<Page<Application> | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(() => {
    const q = filter === "all" ? "" : `?status=${filter}`;
    api<Page<Application>>(`/api/applications${q}`).then(setData).catch((e) => onError(e.message));
  }, [filter, onError]);

  useEffect(load, [load, refreshKey]);

  const mark = async (a: Application, status: "applied" | "skipped") => {
    try {
      await api(`/api/applications/${a.id}`, { method: "PATCH", body: JSON.stringify({ status }) });
      load();
    } catch (e) {
      onError((e as Error).message);
    }
  };

  return (
    <div className="space-y-3">
      <Segmented<Filter>
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all", label: "All" },
          { value: "applied", label: "Applied" },
          { value: "needs_you", label: "Needs you" },
          { value: "dry_run", label: "Dry run" },
          { value: "failed", label: "Failed" },
          { value: "skipped", label: "Skipped" },
        ]}
      />
      <Card className="divide-y divide-line">
        {data === null && <p className="px-5 py-10 text-center text-sm text-zinc-500">Loading…</p>}
        {data && data.items.length === 0 && (
          <EmptyState title="Nothing here yet">Jobs auto apply tries show up here, with the answers it gave.</EmptyState>
        )}
        {data?.items.map((a) => (
          <article key={a.id} className="px-5 py-3.5">
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
              <Badge tone={STATUS[a.status].tone}>{STATUS[a.status].label}</Badge>
              <Badge dot={false}>{SITE_NAME[a.platform] ?? a.platform}</Badge>
              {a.url ? (
                <a href={a.url} target="_blank" rel="noreferrer" className="text-sm font-medium text-ink underline-offset-4 hover:underline">
                  {a.title || "Job"}
                </a>
              ) : (
                <span className="text-sm font-medium text-ink">{a.title || "Job"}</span>
              )}
              <span className="text-sm text-zinc-500">{[a.company, a.location].filter(Boolean).join(" · ")}</span>
              <span className="ml-auto text-xs text-zinc-500">{timeAgo(a.updated_at)}</span>
            </div>
            {a.reason && <p className="mt-1 text-[13px] text-zinc-600">{a.reason}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {a.questions.length > 0 && (
                <button onClick={() => setOpen(open === a.id ? null : a.id)} className="text-xs font-medium text-zinc-500 hover:text-ink">
                  {open === a.id ? "Hide answers" : `Answers (${a.questions.length})`}
                </button>
              )}
              {a.status === "needs_you" && (
                <>
                  {a.url && <a href={a.url} target="_blank" rel="noreferrer" className={buttonClass("secondary", "sm")}>Open job</a>}
                  <Button size="sm" onClick={() => mark(a, "applied")}>I applied</Button>
                  <Button size="sm" variant="ghost" onClick={() => mark(a, "skipped")}>Not interested</Button>
                </>
              )}
            </div>
            {open === a.id && <QAList questions={a.questions} />}
          </article>
        ))}
        {data && data.total > data.items.length && (
          <p className="px-5 py-2.5 text-xs text-zinc-500">Showing {data.items.length} of {data.total}</p>
        )}
      </Card>
    </div>
  );
}

const SOURCE: Record<string, string> = { saved: "your answers", learned: "learned", ai: "AI", prefilled: "already filled", none: "not answered" };

export function QAList({ questions }: { questions: Application["questions"] }) {
  return (
    <dl className="mt-2 space-y-1 rounded-md bg-zinc-50 p-3 text-xs leading-5">
      {questions.map((qa, i) => (
        <div key={i} className="grid gap-x-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <dt className="text-zinc-600">{qa.q || "(no label)"}</dt>
          <dd className={cn("text-zinc-900", qa.answer === null && "text-amber-700")}>{qa.answer ?? "—"}</dd>
          <dd className="text-zinc-400">{SOURCE[qa.source] ?? qa.source}</dd>
        </div>
      ))}
    </dl>
  );
}
