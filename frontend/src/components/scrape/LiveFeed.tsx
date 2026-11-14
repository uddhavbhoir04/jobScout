"use client";

import { useMemo, useState } from "react";
import type { JobEvent, JobStatus, LogEvent, PostEvent, ProgressEvent, SummaryEvent } from "@/lib/api";
import { Badge, Card, cn, EmptyState, Spinner } from "../ui";

const STATUS_LABEL: Record<JobStatus, string> = {
  running: "Searching",
  done: "Finished",
  stopped: "Stopped",
  error: "Failed",
};

const STOP_REASON: Record<string, string> = {
  "target reached": "Reached your target.",
  "stopped by you": "You stopped the search.",
  "no working LinkedIn account left": "No LinkedIn account could stay logged in. Log in again on LinkedIn accounts.",
  "no channel could be read": "None of your Telegram channels could be read. Check them on the Telegram tab.",
};

export function LiveFeed({ events, status }: { events: JobEvent[]; status: JobStatus | null }) {
  const [showSkipped, setShowSkipped] = useState(false);

  const { posts, logs, progress, summary, start } = useMemo(() => {
    const posts: PostEvent[] = [];
    const logs: LogEvent[] = [];
    let progress: ProgressEvent | null = null;
    let summary: SummaryEvent | null = null;
    let start: JobEvent | null = null;
    for (const e of events) {
      if (e.type === "post") posts.push(e as PostEvent);
      else if (e.type === "log" || e.type === "error") logs.push(e as LogEvent);
      else if (e.type === "progress") progress = e as ProgressEvent;
      else if (e.type === "summary") summary = e as SummaryEvent;
      else if (e.type === "start") start = e;
    }
    return { posts: posts.reverse(), logs, progress, summary, start };
  }, [events]);

  const saved = posts.filter((p) => p.status === "saved").length;
  const collected = summary?.collected ?? progress?.collected ?? posts.filter((p) => p.status === "saved" && p.counted !== false).length;
  const skipped = posts.length - saved;
  const scanned = summary?.scanned ?? progress?.scanned ?? 0;
  const limit = (start?.limit as number | undefined) ?? progress?.limit ?? 0;
  const visible = showSkipped ? posts : posts.filter((p) => p.status === "saved");
  const range = start?.date_range as { label: string } | undefined;
  const pct = limit ? Math.min(100, Math.round((collected / limit) * 100)) : 0;

  if (!status) {
    return (
      <Card className="min-h-[480px]">
        <EmptyState title="No search running">
          Choose LinkedIn or Telegram, set your filters and how many contacts you want, then start. Each post appears
          here as it&apos;s checked, with the reason it was saved or skipped.
        </EmptyState>
      </Card>
    );
  }

  return (
    <Card className="flex min-h-[480px] flex-col">
      {/* header */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          {status === "running" ? (
            <Spinner />
          ) : (
            <span className={cn("h-2 w-2 rounded-full", status === "done" ? "bg-brand-600" : status === "error" ? "bg-red-600" : "bg-zinc-400")} />
          )}
          <h2 className="text-[13px] font-semibold text-ink">{STATUS_LABEL[status]}</h2>
          {range && <span className="text-xs text-zinc-500">Posted {range.label.replace(/-/g, " ")}</span>}
        </div>
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-zinc-600">
          <input type="checkbox" checked={showSkipped} onChange={(e) => setShowSkipped(e.target.checked)} className="h-3.5 w-3.5 accent-brand-700" />
          Show skipped posts ({skipped})
        </label>
      </div>

      {/* progress */}
      <div className="border-b border-line px-5 py-4">
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <span className="text-2xl font-semibold tabular-nums text-ink">{collected}</span>
            {limit > 0 && <span className="text-sm tabular-nums text-zinc-500"> / {limit} contacts</span>}
          </div>
          <div className="flex gap-5 text-xs text-zinc-500">
            <span><b className="font-medium tabular-nums text-zinc-800">{saved}</b> saved</span>
            <span><b className="font-medium tabular-nums text-zinc-800">{scanned}</b> checked</span>
            <span><b className="font-medium tabular-nums text-zinc-800">{skipped}</b> skipped</span>
          </div>
        </div>
        {limit > 0 && (
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-zinc-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full rounded-full bg-brand-600 transition-[width] duration-500" style={{ width: `${pct}%` }} />
          </div>
        )}
      </div>

      {/* activity log */}
      {logs.length > 0 && (
        <details className="group border-b border-line" open={status === "running"}>
          <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-2 text-xs text-zinc-500 hover:text-ink">
            <span>Activity</span>
            <span className="truncate pl-4 text-zinc-400 group-open:hidden">{logs[logs.length - 1].message}</span>
          </summary>
          <div className="max-h-32 overflow-y-auto bg-zinc-50 px-5 py-2 font-mono text-[11px] leading-5">
            {logs.slice(-40).map((l) => (
              <div key={l.seq} className={cn(l.type === "error" || l.level === "error" ? "text-red-700" : l.level === "warning" ? "text-amber-700" : "text-zinc-500")}>
                <span className="text-zinc-400">{new Date(l.ts * 1000).toLocaleTimeString()}</span>&nbsp; {l.message}
              </div>
            ))}
          </div>
        </details>
      )}

      {summary && <SummaryBar summary={summary} telegram={start?.source === "telegram"} />}

      {/* posts */}
      <div className="flex-1 divide-y divide-line overflow-y-auto" style={{ maxHeight: "70vh" }}>
        {visible.length === 0 && (
          <p className="px-5 py-12 text-center text-sm text-zinc-500">
            {status === "running"
              ? "Checking posts. Saved contacts will appear here."
              : skipped && !showSkipped
                ? "No posts were saved. Turn on “Show skipped posts” to see why."
                : "No posts to show."}
          </p>
        )}
        {visible.map((p) => (p.status === "saved" ? <SavedPost key={p.seq} p={p} /> : <SkippedPost key={p.seq} p={p} />))}
      </div>
    </Card>
  );
}

function SummaryBar({ summary, telegram }: { summary: SummaryEvent; telegram: boolean }) {
  const reasons = Object.entries(summary.skipped).sort((a, b) => b[1] - a[1]);
  const reached = summary.stop_reason === "target reached";
  const reason = STOP_REASON[summary.stop_reason] ??
    (summary.stop_reason.startsWith("no more matching")
      ? telegram
        ? "No more matching posts in your channels for these dates. Try a wider date range, more keywords or another channel."
        : "LinkedIn has no more matching posts for these hashtags and dates. Try a wider date range or more role hashtags."
      : summary.stop_reason);
  return (
    <div className={cn("space-y-2 border-b border-line px-5 py-3 text-[13px]", reached ? "bg-brand-50/60" : "bg-amber-50/50")}>
      <p className="text-zinc-700">
        <span className="font-medium text-ink">Run #{summary.run_id} finished.</span> {reason}
      </p>
      {reasons.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {reasons.map(([r, n]) => (
            <Badge key={r} dot={false}>{r} · {n}</Badge>
          ))}
        </div>
      )}
      {summary.failed_accounts.length > 0 && (
        <p className="text-amber-800">
          {telegram ? "Couldn't read: " : "Log in again: "}
          {summary.failed_accounts.join(", ")}
        </p>
      )}
    </div>
  );
}

function SavedPost({ p }: { p: PostEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <article className="feed-in px-5 py-4">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {p.author_url ? (
          <a href={p.author_url} target="_blank" rel="noreferrer" className="text-sm font-medium text-ink underline-offset-4 hover:underline">
            {p.author || "Unknown"}
          </a>
        ) : (
          <span className="text-sm font-medium text-ink">{p.author || "Unknown"}</span>
        )}
        {p.posted && <span className="text-xs text-zinc-500">{p.posted.split("•")[0].trim()} ago</span>}
        {p.counted === false ? (
          <span title={p.note ?? undefined}><Badge>Saved, not counted</Badge></span>
        ) : (
          <Badge tone="green">New contact</Badge>
        )}
      </div>
      {p.hiring_for && <p className="mt-1 text-sm text-zinc-700">{p.hiring_for}</p>}
      <dl className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1.5 text-[13px]">
        {p.contact_name && <Field label="Contact" value={p.contact_name} />}
        {(p.emails ?? []).map((e) => <Field key={e} label="Email" value={e} mono copy />)}
        {(p.phones ?? []).map((ph) => <Field key={ph} label="Phone" value={ph} mono copy />)}
      </dl>
      <button onClick={() => setOpen(!open)} className="mt-2 text-xs font-medium text-zinc-500 hover:text-ink">
        {open ? "Hide post" : "Read post"}
      </button>
      {open && <p className="mt-2 whitespace-pre-line rounded-md bg-zinc-50 p-3 text-xs leading-5 text-zinc-700">{p.text}</p>}
    </article>
  );
}

function SkippedPost({ p }: { p: PostEvent }) {
  return (
    <div className="feed-in flex items-center gap-3 px-5 py-2.5 text-xs">
      <span className="w-40 shrink-0 truncate text-zinc-600">{p.author || "Unknown"}</span>
      <span className="hidden min-w-0 flex-1 truncate text-zinc-400 sm:block">{p.text.replace(/\s+/g, " ").slice(0, 100)}</span>
      <span className="ml-auto shrink-0"><Badge dot={false}>{p.reason}</Badge></span>
    </div>
  );
}

function Field({ label, value, copy, mono }: { label: string; value: string; copy?: boolean; mono?: boolean }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="inline-flex items-baseline gap-2">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className={cn("text-zinc-900", mono && "font-mono text-[12.5px]")}>{value}</dd>
      {copy && (
        <button
          onClick={() => {
            navigator.clipboard?.writeText(value).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1200);
            });
          }}
          className="text-xs text-brand-700 hover:underline"
          aria-label={`Copy ${label.toLowerCase()}`}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      )}
    </div>
  );
}
