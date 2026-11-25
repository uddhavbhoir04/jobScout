"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { Account } from "@/lib/api";
import { Badge, Button, Card, CardHeader, cn, Input, Label, Spinner } from "../ui";
import { PRESET_LABELS } from "./FilterPanel";
import { DEFAULT_JOB_FILTERS, experienceInvalid, JobFilterFields, type JobFilterValues } from "./JobFilters";
import { TagInput } from "./TagInput";

// Naukri and Indeed: searched with the user's account for the site (Accounts page) or as a guest.
// Only jobs whose description has an email are saved.

export type Board = "naukri" | "indeed";

export type BoardFilters = {
  keywords: string[]; // job titles or skills; one search each
  datePreset: string;
  dateFrom: string;
  dateTo: string;
  limit: number;
  headless: boolean;
} & JobFilterValues;

const DEFAULTS: BoardFilters = {
  keywords: ["python developer"],
  datePreset: "last-3d",
  dateFrom: "",
  dateTo: "",
  limit: 20,
  headless: false,
  ...DEFAULT_JOB_FILTERS,
};

const SITE: Record<Board, { name: string; subtitle: string; browserHint: string }> = {
  naukri: {
    name: "Naukri",
    subtitle: "Job search on naukri.com, with your account or as a guest.",
    browserHint: "Required. Naukri blocks hidden browsers.",
  },
  indeed: {
    name: "Indeed",
    subtitle: "Job search on in.indeed.com, with your account or as a guest.",
    browserHint: "Recommended. Lets you pass Indeed's human check if one appears.",
  },
};

const SUGGESTED = ["python developer", "react developer", "data analyst", "java developer", "devops engineer"];
const storageKey = (userId: number, board: Board) => `jobscout.${board}.user-${userId}`;

function loadFilters(userId: number, board: Board): BoardFilters {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const raw = localStorage.getItem(storageKey(userId, board));
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {}
  return DEFAULTS;
}

export function BoardPanel({
  board,
  userId,
  accounts,
  running,
  starting,
  stopping,
  onStart,
  onStop,
}: {
  board: Board;
  userId: number;
  accounts: Account[]; // this site's accounts; the first active one is used
  running: boolean;
  starting: boolean;
  stopping: boolean;
  onStart: (f: BoardFilters) => void;
  onStop: () => void;
}) {
  const [f, setF] = useState<BoardFilters>(() => loadFilters(userId, board));
  const site = SITE[board];
  const account = accounts.find((a) => a.active);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(userId, board), JSON.stringify(f));
    } catch {}
  }, [f, userId, board]);

  const set = <K extends keyof BoardFilters>(k: K, v: BoardFilters[K]) => setF((p) => ({ ...p, [k]: v }));
  const customInvalid = f.datePreset === "custom" && !f.dateFrom;
  const canStart = f.keywords.length > 0 && !experienceInvalid(f) && !customInvalid && !running && !starting;

  return (
    <Card>
      <CardHeader title={`Search ${site.name}`} subtitle={site.subtitle} />
      <div className="space-y-5 px-5 py-5">
        <div className="rounded-md border border-line bg-zinc-50/60 px-3 py-2.5 text-[13px]">
          {account ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-zinc-600">Searching as</span>
              <span className="truncate font-medium text-ink">{account.email}</span>
              {account.last_status === "ok" ? <Badge tone="green">Logged in</Badge> : <Badge tone="amber">Needs login</Badge>}
              <Link href="/accounts" className="ml-auto text-xs text-brand-700 underline-offset-4 hover:underline">Manage</Link>
            </div>
          ) : (
            <p className="text-zinc-600">
              Searching as a guest.{" "}
              <Link href="/accounts" className="font-medium text-brand-700 underline-offset-4 hover:underline">Log in to {site.name}</Link>
              {board === "indeed" ? " to read more than the first page of results." : " to search with your account."}
            </p>
          )}
          {account && account.last_status !== "ok" && (
            <p className="mt-1 text-xs text-zinc-500">
              The run logs in first{" "}
              {f.headless ? "(turn on “Show browser window” so you can enter an OTP)" : "(enter any OTP in the browser window)"}; if that
              fails it searches as a guest.
            </p>
          )}
        </div>

        <div>
          <Label hint="One search each">Job titles or skills</Label>
          <TagInput
            mode="keyword"
            value={f.keywords}
            onChange={(v) => set("keywords", v)}
            disabled={running}
            suggestions={SUGGESTED}
            placeholder="python developer, data analyst"
            ariaLabel="Job titles or skills"
          />
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
          <Label hint="Up to 100">Jobs to collect</Label>
          <div className="flex items-center gap-3">
            <input type="range" min={1} max={100} value={f.limit} disabled={running} aria-label="Jobs to collect"
              onChange={(e) => set("limit", Number(e.target.value))} className="flex-1 accent-brand-700" />
            <Input type="number" min={1} max={100} value={f.limit} disabled={running} aria-label="Jobs to collect (number)"
              onChange={(e) => set("limit", Math.max(1, Math.min(100, Number(e.target.value) || 1)))} className="w-16 text-center" />
          </div>
          <p className="mt-1.5 text-xs leading-5 text-zinc-500">
            Only jobs whose description has an email are saved. Most listings don&apos;t, so expect a slow run; add more
            titles or locations for more results.
            {board === "indeed" && !account && " As a guest, Indeed shows about 15 jobs per search."}
          </p>
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
            <span className="block text-xs leading-5 text-zinc-500">{site.browserHint}</span>
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
        {f.keywords.length === 0 && <p className="text-xs text-amber-700">Add at least one job title or skill.</p>}
      </div>
    </Card>
  );
}
