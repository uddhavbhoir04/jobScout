"use client";

import { useRef, useState } from "react";
import { api, type EmailSettings } from "@/lib/api";
import { Button, Card, CardHeader, ErrorNote, Spinner, Textarea } from "../ui";

/** What the AI knows about the user when writing emails, plus the resume that gets attached. */
export function ProfileCard({ settings, onChange }: { settings: EmailSettings; onChange: (s: EmailSettings) => void }) {
  const [text, setText] = useState(settings.profile_text);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const dirty = text !== settings.profile_text;

  const saveProfile = async () => {
    setSaving(true);
    setError(null);
    try {
      onChange(await api<EmailSettings>("/api/email/settings", { method: "PUT", body: JSON.stringify({ profile_text: text }) }));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const upload = async (file: File) => {
    setError(null);
    if (file.size > 5 * 1024 * 1024) return setError("Resume must be under 5 MB.");
    setUploading(true);
    try {
      const b64 = await new Promise<string>((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
        r.onerror = () => reject(new Error("Could not read the file."));
        r.readAsDataURL(file);
      });
      onChange(await api<EmailSettings>("/api/email/settings/resume", {
        method: "POST",
        body: JSON.stringify({ filename: file.name, content_base64: b64 }),
      }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const removeResume = async () => {
    onChange(await api<EmailSettings>("/api/email/settings/resume", { method: "DELETE" }));
  };

  return (
    <Card>
      <CardHeader title="About you" subtitle="Each email is written from your resume and these notes. Nothing is invented." />
      <div className="space-y-4 px-5 py-5">
        <div>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            maxLength={8000}
            placeholder={
              "The AI already reads your uploaded resume. Add anything it doesn't say, e.g.:\n" +
              "Looking for backend / AI engineer roles. Immediate joiner, open to remote or hybrid in Mumbai.\n" +
              "Happy to start at a more junior level on strong teams."
            }
            aria-label="About you"
          />
          <div className="mt-2 flex items-center gap-2">
            <Button size="sm" onClick={saveProfile} disabled={!dirty || saving}>
              {saving ? <Spinner /> : null} {saved ? "Saved" : "Save"}
            </Button>
            {!text.trim() && !settings.resume_text_chars && (
              <span className="text-xs text-amber-700">Upload your resume or write something here, or emails will be generic.</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-md border border-dashed border-zinc-300 bg-zinc-50/60 px-3 py-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-zinc-100 text-[10px] font-semibold text-zinc-500">
            {settings.resume_filename ? settings.resume_filename.split(".").pop()?.toUpperCase() : "CV"}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-ink">{settings.resume_filename ?? "No resume uploaded"}</div>
            <div className="text-xs text-zinc-500">
              {!settings.resume_filename
                ? "PDF or Word, up to 5 MB"
                : settings.resume_text_chars > 0
                  ? "Attached to every email · AI reads it to write each email"
                  : "Attached, but its text could not be read (scanned PDF?): the AI only uses About you"}
            </div>
          </div>
          <input ref={fileRef} type="file" accept=".pdf,.doc,.docx" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <Button size="sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? <Spinner /> : null} {settings.resume_filename ? "Replace" : "Upload"}
          </Button>
          {settings.resume_filename && (
            <Button size="sm" variant="ghost" onClick={removeResume}>Remove</Button>
          )}
        </div>
        <ErrorNote message={error} />
      </div>
    </Card>
  );
}
