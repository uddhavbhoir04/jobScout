"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  timeAgo,
  type EmailJobEvent,
  type EmailStats,
  type EmailStatus,
  type JobSummary,
  type LogEvent,
  type Outreach,
  type Page,
} from "@/lib/api";
import { useJobStream } from "@/lib/useJobStream";
import { Badge, Button, Card, cn, emailStatusTone, ErrorNote, Input, Notice, Segmented, Spinner, Textarea } from "../ui";

const STATUS_LABEL: Record<string, string> = {
  pending: "Needs draft",
  drafted: "Ready",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
  bounced: "Bounced",
  replied: "Replied",
  skipped: "Not sending",
};

const TABS: { key: string; label: string; statuses: EmailStatus[] }[] = [
  { key: "drafted", label: "Ready to send", statuses: ["drafted"] },
  { key: "pending", label: "Needs draft", statuses: ["pending"] },
  { key: "sent", label: "Sent", statuses: ["sent", "replied"] },
  { key: "failed", label: "Failed", statuses: ["failed", "bounced"] },
  { key: "skipped", label: "Skipped", statuses: ["skipped"] },
  { key: "all", label: "All", statuses: [] },
];

export function OutreachPanel({
  connected,
  stats,
  refreshStats,
}: {
  connected: boolean;
  stats: EmailStats | null;
  refreshStats: () => void;
}) {
  const [tab, setTab] = useState("drafted");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [data, setData] = useState<Page<Outreach> | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobKind, setJobKind] = useState<"draft" | "send" | null>(null);
  const [sendCount, setSendCount] = useState(5);
  const [error, setError] = useState<string | null>(null);
  const { events, status } = useJobStream(jobId);
  const running = status === "running";

  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(() => {
    const statuses = TABS.find((t) => t.key === tab)?.statuses ?? [];
    const params = new URLSearchParams();
    if (statuses.length) params.set("status", statuses.join(","));
    if (query) params.set("q", query);
    api<Page<Outreach>>(`/api/emails?${params}`).then(setData).catch((e) => setError(e.message));
  }, [tab, query]);

  useEffect(load, [load]);

  // resume a running draft/send job after a page reload
  useEffect(() => {
    api<JobSummary | null>("/api/jobs/current?kind=draft,send")
      .then((j) => {
        if (j) {
          setJobId(j.id);
          setJobKind(j.kind as "draft" | "send");
        }
      })
      .catch(() => {});
  }, []);

  // refresh the list + counters as emails get drafted/sent, and when the job ends
  const emailEvents = useMemo(() => events.filter((e) => e.type === "email") as EmailJobEvent[], [events]);
  useEffect(() => {
    if (emailEvents.length || (status && status !== "running")) {
      load();
      refreshStats();
    }
  }, [emailEvents.length, status, load, refreshStats]);

  const startJob = async (kind: "draft" | "send", body: object) => {
    setError(null);
    try {
      const j = await api<JobSummary>(kind === "draft" ? "/api/emails/draft" : "/api/emails/send", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setJobKind(kind);
      setJobId(j.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const stop = () => jobId && api(`/api/jobs/${jobId}/stop`, { method: "POST" }).catch(() => {});

  const pending = stats?.pending ?? 0;
  const drafted = stats?.drafted ?? 0;
  const leftToday = stats ? Math.max(0, stats.daily_cap - stats.sent_today) : 0;
  const maxSend = Math.min(drafted, leftToday);

  return (
    <div className="space-y-4">
      {/* actions */}
      <Card className="px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => startJob("draft", {})} disabled={running || pending === 0}>
            {running && jobKind === "draft" ? <Spinner /> : null}
            {pending ? `Write ${pending} draft${pending === 1 ? "" : "s"}` : "No drafts to write"}
          </Button>
          <div className="h-6 w-px bg-line" aria-hidden />
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              onClick={() => startJob("send", { limit: Math.min(sendCount, maxSend) })}
              disabled={running || !connected || maxSend === 0}
              title={!connected ? "Connect Gmail first" : undefined}
            >
              {running && jobKind === "send" ? <Spinner className="border-white/40 border-t-white" /> : null} Send
            </Button>
            <Input
              type="number"
              min={1}
              max={Math.max(1, maxSend)}
              value={Math.min(sendCount, Math.max(1, maxSend))}
              onChange={(e) => setSendCount(Math.max(1, Number(e.target.value) || 1))}
              disabled={running || maxSend === 0}
              className="w-16 text-center"
              aria-label="How many emails to send"
            />
            <span className="whitespace-nowrap text-sm text-zinc-500">
              of {drafted} ready · {Math.max(0, leftToday)} left today
            </span>
          </div>
          {running && (
            <Button variant="danger" size="sm" className="ml-auto" onClick={stop}>
              Stop
            </Button>
          )}
        </div>
        {!connected && (
          <Notice tone="warning" className="mt-3">Connect your Gmail on the left to send. You can already write and edit drafts.</Notice>
        )}
        <JobActivity events={events} status={status} kind={jobKind} />
        <ErrorNote message={error} />
      </Card>

      {/* list */}
      <div className="flex flex-wrap items-center gap-3">
        <Segmented
          value={tab}
          onChange={(v) => {
            setTab(v);
            setOpen(null);
          }}
          options={TABS.map((t) => {
            const n = stats ? t.statuses.reduce((sum, s) => sum + (stats[s] ?? 0), 0) : 0;
            return {
              value: t.key,
              label: (
                <>
                  {t.label}
                  {t.statuses.length > 0 && <span className="ml-1.5 tabular-nums text-zinc-500">{n}</span>}
                </>
              ),
            };
          })}
        />
        <div className="w-full max-w-xs">
          <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, email or role" aria-label="Search emails" />
        </div>
      </div>

      <Card className="divide-y divide-line overflow-hidden">
        {data === null && <div className="px-5 py-10 text-center text-sm text-zinc-500">Loading…</div>}
        {data?.items.length === 0 && (
          <div className="px-5 py-10 text-center text-sm text-zinc-500">
            {tab === "drafted" && pending > 0 ? `Nothing ready yet. Click "Write ${pending} drafts" above.` : "Nothing here."}
          </div>
        )}
        {data?.items.map((o) => (
          <OutreachRow
            key={o.id}
            o={o}
            open={open === o.id}
            onToggle={() => setOpen(open === o.id ? null : o.id)}
            busy={running}
            connected={connected}
            onChanged={() => {
              load();
              refreshStats();
            }}
            onStartJob={startJob}
          />
        ))}
        {data && data.total > data.items.length && (
          <div className="px-5 py-2.5 text-xs text-zinc-500">Showing {data.items.length} of {data.total}</div>
        )}
      </Card>
    </div>
  );
}

function JobActivity({ events, status, kind }: { events: ReturnType<typeof useJobStream>["events"]; status: string | null; kind: string | null }) {
  if (!status) return null;
  const items = events.filter((e) => e.type === "email") as EmailJobEvent[];
  const logs = events.filter((e) => e.type === "log" || e.type === "error") as LogEvent[];
  const summary = events.find((e) => e.type === "summary") as Record<string, number> | undefined;
  const lastLog = logs[logs.length - 1];
  const verb = kind === "draft" ? "Drafting" : "Sending";

  return (
    <div className="mt-4 rounded-md border border-line bg-zinc-50 px-4 py-3 text-xs">
      <div className="flex items-center gap-2 text-zinc-700">
        {status === "running" ? <Spinner /> : <span className={cn("h-2 w-2 rounded-full", status === "error" ? "bg-red-600" : "bg-emerald-600")} />}
        <span className="font-medium">
          {status === "running"
            ? `${verb}… ${items.length} done${kind === "send" && items.length ? " (pausing 30–90s between emails)" : ""}`
            : summary
              ? kind === "draft"
                ? `Drafted ${summary.drafted ?? 0} email(s)`
                : `Sent ${summary.sent ?? 0}, failed ${summary.failed ?? 0}${summary.retry_later ? `, retry later ${summary.retry_later}` : ""}`
              : status === "error"
                ? "Stopped with an error"
                : "Finished"}
        </span>
      </div>
      {lastLog && (lastLog.type === "error" || lastLog.level !== "info") && (
        <p className={cn("mt-1.5", lastLog.type === "error" ? "text-red-700" : "text-amber-700")}>{lastLog.message}</p>
      )}
      {items.length > 0 && (
        <ul className="mt-2 max-h-36 space-y-1 overflow-y-auto">
          {[...items].reverse().map((e) => (
            <li key={e.seq} className="flex items-center gap-2">
              <Badge tone={e.outcome === "sent" || e.outcome === "drafted" ? "green" : e.outcome === "retry" ? "amber" : "red"}>
                {e.outcome}
              </Badge>
              <span className="truncate text-zinc-700">{e.name || e.to}</span>
              <span className="truncate font-mono text-zinc-400">{e.to}</span>
              {e.error && e.outcome !== "sent" && <span className="truncate text-red-700">{e.error}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function OutreachRow({
  o,
  open,
  onToggle,
  busy,
  connected,
  onChanged,
  onStartJob,
}: {
  o: Outreach;
  open: boolean;
  onToggle: () => void;
  busy: boolean;
  connected: boolean;
  onChanged: () => void;
  onStartJob: (kind: "draft" | "send", body: object) => void;
}) {
  return (
    <div className={cn(open && "bg-zinc-50/50")}>
      <button onClick={onToggle} className="flex w-full items-center gap-4 px-5 py-3 text-left hover:bg-zinc-50">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-ink">{o.contact.name || o.contact.email}</span>
            <span className="truncate font-mono text-xs text-zinc-500">{o.contact.email}</span>
          </div>
          <div className="mt-0.5 truncate text-xs text-zinc-500">
            {o.subject ? <span className="text-zinc-700">{o.subject}</span> : o.post?.hiring_for || "No draft yet"}
          </div>
        </div>
        {o.last_error && o.status !== "sent" && <span className="hidden max-w-56 truncate text-xs text-red-700 md:block" title={o.last_error}>{o.last_error}</span>}
        <Badge tone={emailStatusTone(o.status)}>{STATUS_LABEL[o.status] ?? o.status}</Badge>
        <span className="w-16 shrink-0 text-right text-xs text-zinc-400">{timeAgo(o.sent_at ?? o.updated_at)}</span>
      </button>
      {open && <EmailEditor key={o.id + o.updated_at} o={o} busy={busy} connected={connected} onChanged={onChanged} onStartJob={onStartJob} />}
    </div>
  );
}

function EmailEditor({
  o,
  busy,
  connected,
  onChanged,
  onStartJob,
}: {
  o: Outreach;
  busy: boolean;
  connected: boolean;
  onChanged: () => void;
  onStartJob: (kind: "draft" | "send", body: object) => void;
}) {
  const [subject, setSubject] = useState(o.subject ?? "");
  const [body, setBody] = useState(o.body ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPost, setShowPost] = useState(false);
  const readOnly = o.status === "sent" || o.status === "sending" || o.status === "replied";
  const dirty = subject !== (o.subject ?? "") || body !== (o.body ?? "");

  const patch = async (payload: object) => {
    setSaving(true);
    setError(null);
    try {
      await api(`/api/emails/${o.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3 px-5 pb-5">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
        <span>To <span className="font-mono text-zinc-800">{o.contact.email}</span></span>
        {o.contact.phone && <span>Phone <span className="font-mono text-zinc-800">{o.contact.phone}</span></span>}
        {o.post?.hiring_for && <span>Role <span className="text-zinc-800">{o.post.hiring_for}</span></span>}
        {o.post?.author_url && (
          <a href={o.post.author_url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
            LinkedIn profile
          </a>
        )}
        {o.post && (
          <button onClick={() => setShowPost(!showPost)} className="underline-offset-2 hover:underline">
            {showPost ? "Hide post" : "Show post"}
          </button>
        )}
        {o.sent_at && <span>Sent {new Date(o.sent_at).toLocaleString()}</span>}
      </div>
      {showPost && o.post && (
        <p className="max-h-48 overflow-y-auto whitespace-pre-line rounded-md border border-line bg-surface p-3 text-xs leading-5 text-zinc-700">{o.post.text}</p>
      )}

      {o.status === "pending" && !o.subject ? (
        <div className="flex items-center gap-3 rounded-md border border-dashed border-zinc-300 bg-surface px-4 py-3 text-sm text-zinc-600">
          No draft yet.
          <Button size="sm" onClick={() => onStartJob("draft", { ids: [o.id] })} disabled={busy}>Write with AI</Button>
        </div>
      ) : (
        <>
          <Input value={subject} onChange={(e) => setSubject(e.target.value)} readOnly={readOnly} placeholder="Subject" aria-label="Subject" className="font-medium" />
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            readOnly={readOnly}
            rows={Math.min(18, Math.max(8, body.split("\n").length + 1))}
            aria-label="Email body"
          />
        </>
      )}
      <ErrorNote message={error} />

      {!readOnly && (
        <div className="flex flex-wrap items-center gap-2">
          {dirty && (
            <Button size="sm" onClick={() => patch({ subject, body })} disabled={saving}>
              {saving ? <Spinner /> : null} Save changes
            </Button>
          )}
          {(o.status === "drafted" || o.status === "failed") && (
            <Button
              size="sm"
              variant="primary"
              disabled={busy || !connected || dirty}
              title={dirty ? "Save your changes first" : !connected ? "Connect Gmail first" : undefined}
              onClick={async () => {
                if (o.status === "failed") await patch({ status: "drafted" });
                onStartJob("send", { ids: [o.id], limit: 1 });
              }}
            >
              Send now
            </Button>
          )}
          {o.subject && (
            <Button size="sm" variant="ghost" onClick={() => onStartJob("draft", { ids: [o.id] })} disabled={busy}>
              Rewrite with AI
            </Button>
          )}
          {o.status !== "skipped" ? (
            <Button size="sm" variant="ghost" onClick={() => patch({ status: "skipped" })} disabled={saving} className="ml-auto">
              Don&apos;t send
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => patch({ status: o.subject ? "drafted" : "pending" })} disabled={saving} className="ml-auto">
              Restore
            </Button>
          )}
        </div>
      )}
      {o.status === "sent" && (
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => patch({ status: "replied" })}>Mark as replied</Button>
          <Button size="sm" variant="ghost" onClick={() => patch({ status: "bounced" })}>Mark as bounced</Button>
        </div>
      )}
    </div>
  );
}
