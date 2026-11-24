"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { Account } from "@/lib/api";
import { Button, Card, CardHeader, cn, Input, Label, Spinner } from "../ui";
import { DEFAULT_JOB_FILTERS, experienceInvalid, JobFilterFields, type JobFilterValues } from "./JobFilters";
import { TagInput } from "./TagInput";

export type Filters = {
  tags: string[]; // role hashtags: post must contain #hiring AND at least one of these
  datePreset: string; // a preset or "custom"
  dateFrom: string;
  dateTo: string;
  limit: number;
  accountIds: number[] | "all";
  headless: boolean;
} & JobFilterValues;

export const HIRING_TAG = "#hiring"; // always required (the backend enforces it too)

export const DEFAULT_FILTERS: Filters = {
  tags: ["#pythondeveloper"],
  datePreset: "last-7d",
  dateFrom: "",
  dateTo: "",
  limit: 20,
  accountIds: "all",
  headless: false,
  ...DEFAULT_JOB_FILTERS,
};

export const PRESET_LABELS: Record<string, string> = {
  today: "Last 24 hours",
  yesterday: "Yesterday",
  "day-before-yesterday": "Day before",
  "last-3d": "Last 3 days",
  "last-7d": "Last 7 days",
  "last-30d": "Last 30 days",
  custom: "Custom",
};

const SUGGESTED_ROLES = ["#pythondeveloper", "#processimprovement", "#projectcoordination", "#processmining", "#backenddeveloper"];
// Saved per jobscout user, so people sharing a browser don't see each other's last search.
const storageKey = (userId: number) => `jobscout.filters.user-${userId}`;
const LEGACY_KEY = "jobscout.filters"; // old browser-wide key: unknown owner, so it's dropped

export function loadFilters(userId: number): Filters {
  if (typeof window === "undefined") return DEFAULT_FILTERS;
  try {
    localStorage.removeItem(LEGACY_KEY);
    const raw = localStorage.getItem(storageKey(userId));
    if (raw) {
      const saved = JSON.parse(raw);
      const tags = Array.isArray(saved.tags) ? saved.tags.filter((t: string) => t !== HIRING_TAG) : DEFAULT_FILTERS.tags;
      return { ...DEFAULT_FILTERS, ...saved, tags };
    }
  } catch {}
  return DEFAULT_FILTERS;
}

// function RulePreview({ roles }: { roles: string[] }) {
//   const query = roles.length
//     ? `${HIRING_TAG} AND ${roles.length > 1 ? "(" + roles.join(" OR ") + ")" : roles[0]}`
//     : HIRING_TAG;
//   return (
//     <div className="space-y-1.5 rounded-md border border-line bg-zinc-50 px-3 py-2.5 text-xs leading-5 text-zinc-600">
//       <p>
//         Saves posts that contain <b className="font-medium text-zinc-900">{HIRING_TAG}</b>
//         {roles.length > 0 && (
//           <>
//             {" "}and {roles.length > 1 ? "at least one of " : ""}
//             <b className="font-medium text-zinc-900">{roles.join(", ")}</b>
//           </>
//         )}
//         .
//       </p>
//       <p className="break-words font-mono text-[11px] text-zinc-500">LinkedIn search: {query}</p>
//     </div>
//   );
// }

export function FilterPanel({
  userId,
  accounts,
  running,
  starting,
  stopping,
  onStart,
  onStop,
}: {
  userId: number;
  accounts: Account[];
  running: boolean;
  starting: boolean;
  stopping: boolean;
  onStart: (f: Filters) => void;
  onStop: () => void;
}) {
  // Rendered only in the browser (see ScrapeView) and re-mounted per user (key={userId}),
  // so reading this user's saved filters on first render is safe.
  const [f, setF] = useState<Filters>(() => loadFilters(userId));

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(userId), JSON.stringify(f));
    } catch {}
  }, [f, userId]);

  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setF((p) => ({ ...p, [k]: v }));
  const active = accounts.filter((a) => a.active);
  const selected = f.accountIds === "all" ? active.map((a) => a.id) : f.accountIds;
  const toggleAccount = (id: number) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
    set("accountIds", next.length === active.length ? "all" : next);
  };

  const customInvalid = f.datePreset === "custom" && !f.dateFrom;
  const canStart =
    f.tags.length > 0 && selected.length > 0 && !customInvalid && !experienceInvalid(f) && !running && !starting;

  return (
    <Card>
      <CardHeader title="New search" subtitle="Saved only when a post has an email, phone number or named contact." />
      <div className="space-y-5 px-5 py-5">
        <div>
          <Label hint="Always included">Hiring hashtag</Label>
          <div className="flex h-9 items-center gap-2 rounded-md border border-line bg-zinc-50 px-2">
            <span className="inline-flex items-center gap-1 rounded bg-brand-50 px-2 py-0.5 font-mono text-xs font-medium text-brand-800 ring-1 ring-inset ring-brand-200">
              {HIRING_TAG}
            </span>
            <span className="text-xs text-zinc-500">every saved post must have it</span>
          </div>
        </div>

        <div>
          <Label hint="Post needs at least one">Role hashtags</Label>
          <TagInput
            value={f.tags}
            onChange={(v) => set("tags", v.filter((t) => t !== HIRING_TAG))}
            disabled={running}
            suggestions={SUGGESTED_ROLES}
            placeholder="#processimprovement, #processmining"
          />
          {f.tags.length === 0 && <p className="mt-1.5 text-xs text-amber-700">Add at least one role hashtag.</p>}
        </div>

        {/* <RulePreview roles={f.tags} /> */}

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
              <Input type="date" value={f.dateFrom} disabled={running} onChange={(e) => set("dateFrom", e.target.value)} />
              <Input type="date" value={f.dateTo} disabled={running} onChange={(e) => set("dateTo", e.target.value)} />
            </div>
          )}
        </div>

        <JobFilterFields value={f} onChange={(patch) => setF((p) => ({ ...p, ...patch }))} disabled={running} />

        <div>
          <Label hint="Runs until reached, up to 100">Contacts to collect</Label>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={1}
              max={100}
              value={f.limit}
              disabled={running}
              onChange={(e) => set("limit", Number(e.target.value))}
              className="flex-1 accent-brand-700"
            />
            <Input
              type="number"
              min={1}
              max={100}
              value={f.limit}
              disabled={running}
              onChange={(e) => set("limit", Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
              className="w-16 text-center"
            />
          </div>
        </div>

        <div>
          <Label hint={<Link href="/accounts" className="text-brand-700 underline-offset-4 hover:underline">Manage</Link>}>LinkedIn accounts</Label>
          {active.length === 0 ? (
            <p className="rounded-md border border-dashed border-zinc-300 px-3 py-3 text-[13px] text-zinc-600">
              No active LinkedIn account. <Link href="/accounts" className="font-medium text-brand-700 underline-offset-4 hover:underline">Connect one</Link> to start.
            </p>
          ) : (
            <div className="space-y-1">
              {active.map((a) => (
                <label key={a.id} className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-zinc-50">
                  <input
                    type="checkbox"
                    checked={selected.includes(a.id)}
                    disabled={running}
                    onChange={() => toggleAccount(a.id)}
                    className="h-3.5 w-3.5 accent-brand-700"
                  />
                  <span className="truncate text-sm text-zinc-800">{a.email}</span>
                  {a.last_status && a.last_status !== "ok" && (
                    <span className="ml-auto text-xs text-amber-700">Needs login</span>
                  )}
                </label>
              ))}
            </div>
          )}
        </div>

        <label className="flex cursor-pointer items-start gap-2.5">
          <input
            type="checkbox"
            checked={!f.headless}
            disabled={running}
            onChange={(e) => set("headless", !e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 accent-brand-700"
          />
          <span>
            <span className="block text-sm text-zinc-800">Show browser window</span>
            <span className="block text-xs leading-5 text-zinc-500">Recommended. Lets you finish a LinkedIn security check if one appears.</span>
          </span>
        </label>

        {running ? (
          <Button variant="danger" className="w-full" onClick={onStop} disabled={stopping}>
            {stopping ? <><Spinner /> Stopping…</> : "Stop search"}
          </Button>
        ) : (
          <Button variant="primary" className="w-full" disabled={!canStart} onClick={() => onStart(f)}>
            {starting ? <><Spinner className="border-white/40 border-t-white" /> Starting…</> : "Start search"}
          </Button>
        )}
      </div>
    </Card>
  );
}
