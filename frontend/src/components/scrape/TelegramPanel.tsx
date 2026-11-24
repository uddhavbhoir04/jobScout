"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, timeAgo, type TelegramChannel } from "@/lib/api";
import { Button, Card, CardHeader, cn, ErrorNote, Input, Label, Spinner } from "../ui";
import { PRESET_LABELS } from "./FilterPanel";
import { DEFAULT_JOB_FILTERS, experienceInvalid, JobFilterFields, type JobFilterValues } from "./JobFilters";
import { TagInput } from "./TagInput";

export type TelegramFilters = {
  keywords: string[]; // a post must mention at least one (empty = any job post with a contact)
  datePreset: string;
  dateFrom: string;
  dateTo: string;
  limit: number;
} & JobFilterValues;

const DEFAULTS: TelegramFilters = {
  keywords: ["python"],
  datePreset: "last-3d",
  dateFrom: "",
  dateTo: "",
  limit: 20,
  ...DEFAULT_JOB_FILTERS,
};

const SUGGESTED = ["python", "react", "node.js", "java", "devops", "data analyst"];
const storageKey = (userId: number) => `jobscout.telegram.user-${userId}`;

function loadFilters(userId: number): TelegramFilters {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const raw = localStorage.getItem(storageKey(userId));
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {}
  return DEFAULTS;
}

function qualityTone(pct: number | null) {
  if (pct === null) return "text-zinc-500";
  if (pct >= 40) return "text-brand-700";
  if (pct >= 15) return "text-amber-700";
  return "text-red-700";
}

export function TelegramPanel({
  userId,
  running,
  starting,
  stopping,
  onStart,
  onStop,
}: {
  userId: number;
  running: boolean;
  starting: boolean;
  stopping: boolean;
  onStart: (f: TelegramFilters) => void;
  onStop: () => void;
}) {
  const [f, setF] = useState<TelegramFilters>(() => loadFilters(userId));
  const [channels, setChannels] = useState<TelegramChannel[] | null>(null);
  const [newChannel, setNewChannel] = useState("");
  const [adding, setAdding] = useState(false);
  const [checking, setChecking] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(userId), JSON.stringify(f));
    } catch {}
  }, [f, userId]);

  // Load on open, and again when a search ends: the search refreshes each channel's numbers.
  useEffect(() => {
    if (running) return;
    api<TelegramChannel[]>("/api/telegram/channels").then(setChannels).catch((e) => setError(e.message));
  }, [running]);

  const set = <K extends keyof TelegramFilters>(k: K, v: TelegramFilters[K]) => setF((p) => ({ ...p, [k]: v }));
  const replace = (c: TelegramChannel) => setChannels((list) => (list ?? []).map((x) => (x.id === c.id ? c : x)));

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!newChannel.trim()) return;
    setError(null);
    setAdding(true);
    try {
      const c = await api<TelegramChannel>("/api/telegram/channels", { method: "POST", body: JSON.stringify({ name: newChannel }) });
      setChannels((list) => [...(list ?? []), c]);
      setNewChannel("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAdding(false);
    }
  };

  const toggle = async (c: TelegramChannel) => {
    try {
      replace(await api<TelegramChannel>(`/api/telegram/channels/${c.id}?active=${!c.active}`, { method: "PATCH" }));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const recheck = async (c: TelegramChannel) => {
    setError(null);
    setChecking(c.id);
    try {
      replace(await api<TelegramChannel>(`/api/telegram/channels/${c.id}/check`, { method: "POST" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setChecking(null);
    }
  };

  const remove = async (c: TelegramChannel) => {
    if (!confirm(`Remove @${c.name}? Contacts already saved from it are kept.`)) return;
    try {
      await api(`/api/telegram/channels/${c.id}`, { method: "DELETE" });
      setChannels((list) => (list ?? []).filter((x) => x.id !== c.id));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const activeCount = channels?.filter((c) => c.active).length ?? 0;
  const customInvalid = f.datePreset === "custom" && !f.dateFrom;
  const canStart = activeCount > 0 && !experienceInvalid(f) && !customInvalid && !running && !starting;

  return (
    <Card>
      <CardHeader title="Search Telegram" subtitle="Public job channels. No Telegram account needed." />
      <div className="space-y-5 px-5 py-5">
        <div>
          <Label hint="Post needs at least one">Keywords</Label>
          <TagInput
            mode="keyword"
            value={f.keywords}
            onChange={(v) => set("keywords", v)}
            disabled={running}
            suggestions={SUGGESTED}
            placeholder="python, react, data analyst"
            ariaLabel="Keywords"
          />
          {f.keywords.length === 0 && (
            <p className="mt-1.5 text-xs text-zinc-500">No keywords: every job post with a contact is collected.</p>
          )}
        </div>

        <div>
          <Label hint={channels ? `${activeCount} of ${channels.length} on` : undefined}>Channels</Label>
          {channels === null ? (
            <div className="h-24 animate-pulse rounded-md bg-zinc-100" />
          ) : (
            <ul className="divide-y divide-line rounded-md border border-line">
              {channels.map((c) => (
                <li key={c.id} className="flex items-start gap-2.5 px-2.5 py-2">
                  <input
                    type="checkbox"
                    checked={c.active}
                    disabled={running}
                    onChange={() => toggle(c)}
                    aria-label={`Search @${c.name}`}
                    className="mt-1 h-3.5 w-3.5 accent-brand-700"
                  />
                  <div className="min-w-0 flex-1">
                    <a href={c.url} target="_blank" rel="noreferrer" className="block truncate font-mono text-[13px] text-ink underline-offset-4 hover:underline">
                      @{c.name}
                    </a>
                    <p className="truncate text-xs text-zinc-500">
                      {c.contact_pct === null ? (
                        "Not checked yet"
                      ) : (
                        <>
                          <span className={cn("font-medium", qualityTone(c.contact_pct))}>{c.contact_pct}% with contacts</span>
                          {c.posts_per_day ? ` · ${c.posts_per_day}/day` : ""}
                          {c.last_post_at ? ` · last post ${timeAgo(c.last_post_at)}` : ""}
                        </>
                      )}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button
                      type="button"
                      onClick={() => recheck(c)}
                      disabled={checking !== null || running}
                      className="rounded px-1.5 py-0.5 text-xs text-zinc-600 hover:bg-zinc-100 hover:text-ink disabled:opacity-50"
                    >
                      {checking === c.id ? <Spinner /> : "Check"}
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(c)}
                      disabled={running}
                      aria-label={`Remove @${c.name}`}
                      className="rounded px-1.5 py-0.5 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
              {channels.length === 0 && <li className="px-3 py-3 text-[13px] text-zinc-600">No channels. Add one below.</li>}
            </ul>
          )}
          <form onSubmit={add} className="mt-2 flex gap-2">
            <Input
              value={newChannel}
              onChange={(e) => setNewChannel(e.target.value)}
              placeholder="@channel or t.me link"
              aria-label="Add a Telegram channel"
              disabled={adding || running}
            />
            <Button type="submit" disabled={adding || running || !newChannel.trim()}>
              {adding ? <><Spinner /> Checking</> : "Add"}
            </Button>
          </form>
          <p className="mt-1.5 text-xs leading-5 text-zinc-500">
            Adding a channel reads its last ~60 posts and shows how many have a recruiter email or phone.
          </p>
        </div>

        <div>
          <Label>Date posted</Label>
          <div className="grid grid-cols-3 gap-1.5">
            {Object.entries(PRESET_LABELS).map(([key, label]) => (
              <button
                key={key}
                type="button"
                disabled={running}
                onClick={() => set("datePreset", key)}
                className={cn(
                  "h-8 rounded-md border text-[13px] transition-colors disabled:opacity-60",
                  f.datePreset === key
                    ? "border-brand-600 bg-brand-50 font-medium text-brand-800"
                    : "border-line bg-surface text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          {f.datePreset === "custom" && (
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Input type="date" aria-label="From" value={f.dateFrom} disabled={running} onChange={(e) => set("dateFrom", e.target.value)} />
              <Input type="date" aria-label="To" value={f.dateTo} disabled={running} onChange={(e) => set("dateTo", e.target.value)} />
            </div>
          )}
        </div>

        <JobFilterFields value={f} onChange={(patch) => setF((p) => ({ ...p, ...patch }))} disabled={running} />

        <div>
          <Label hint="Up to 100">Contacts to collect</Label>
          <div className="flex items-center gap-3">
            <input type="range" min={1} max={100} value={f.limit} disabled={running} aria-label="Contacts to collect"
              onChange={(e) => set("limit", Number(e.target.value))} className="flex-1 accent-brand-700" />
            <Input type="number" min={1} max={100} value={f.limit} disabled={running} aria-label="Contacts to collect (number)"
              onChange={(e) => set("limit", Math.max(1, Math.min(100, Number(e.target.value) || 1)))} className="w-16 text-center" />
          </div>
        </div>

        <ErrorNote message={error} />

        {running ? (
          <Button variant="danger" className="w-full" onClick={onStop} disabled={stopping}>
            {stopping ? <><Spinner /> Stopping…</> : "Stop search"}
          </Button>
        ) : (
          <Button variant="primary" className="w-full" disabled={!canStart} onClick={() => onStart(f)}>
            {starting ? <><Spinner className="border-white/40 border-t-white" /> Starting…</> : "Start search"}
          </Button>
        )}
        {activeCount === 0 && channels !== null && <p className="text-xs text-amber-700">Turn on at least one channel.</p>}
      </div>
    </Card>
  );
}
