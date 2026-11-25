"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { Account, AccountSite } from "@/lib/api";
import { Badge, Button, Card, CardHeader, cn, Input, Label, Notice, Spinner } from "../ui";
import { PRESET_LABELS } from "../scrape/FilterPanel";
import { DEFAULT_JOB_FILTERS, experienceInvalid, JobFilterFields, type JobFilterValues } from "../scrape/JobFilters";
import { TagInput } from "../scrape/TagInput";

// One auto-apply run: a site's Easy Apply jobs matching these filters, applied to with the user's account.

export type ApplyFilters = {
  keywords: string[];
  datePreset: string;
  dateFrom: string;
  dateTo: string;
  limit: number;
  dryRun: boolean;
  headless: boolean;
} & JobFilterValues;

const DEFAULTS: ApplyFilters = {
  keywords: ["python developer"],
  datePreset: "last-7d",
  dateFrom: "",
  dateTo: "",
  limit: 5,
  dryRun: true, // the first run on a site should be a dry run
  headless: false,
  ...DEFAULT_JOB_FILTERS,
};

export const SITE_NAME: Record<AccountSite, string> = { linkedin: "LinkedIn", naukri: "Naukri", indeed: "Indeed" };
const EASY_APPLY: Record<AccountSite, string> = {
  linkedin: "Easy Apply jobs",
  naukri: "jobs that apply on Naukri (not on a company site)",
  indeed: "“Easily apply” jobs",
};
const DRY_RUN_HINT: Record<AccountSite, string> = {
  linkedin: "Fills every form step but doesn't click Submit. A screenshot of the last step is saved.",
  naukri: "Opens each job and stops before Apply (Naukri applies as soon as you click).",
  indeed: "Fills every form step but doesn't click Submit. A screenshot of the last step is saved.",
};
const SUGGESTED = ["python developer", "react developer", "data analyst", "java developer", "devops engineer"];
const storageKey = (userId: number, site: AccountSite) => `jobscout.apply.${site}.user-${userId}`;

function loadFilters(userId: number, site: AccountSite): ApplyFilters {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const raw = localStorage.getItem(storageKey(userId, site));
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {}
  return DEFAULTS;
}

export function ApplyPanel({
  site,
  userId,
  accounts,
  capLeft,
  dailyCap,
  isPaid,
  running,
  starting,
  stopping,
  onStart,
  onStop,
}: {
  site: AccountSite;
  userId: number;
  accounts: Account[]; // this site's accounts; the first active one is used
  capLeft: number;
  dailyCap: number;
  isPaid: boolean;
  running: boolean;
  starting: boolean;
  stopping: boolean;
  onStart: (f: ApplyFilters) => void;
  onStop: () => void;
}) {
  const [f, setF] = useState<ApplyFilters>(() => loadFilters(userId, site));
  const account = accounts.find((a) => a.active);
  const name = SITE_NAME[site];

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(userId, site), JSON.stringify(f));
    } catch {}
  }, [f, userId, site]);

  const set = <K extends keyof ApplyFilters>(k: K, v: ApplyFilters[K]) => setF((p) => ({ ...p, [k]: v }));
  const maxSend = f.dryRun ? 50 : Math.max(0, Math.min(50, capLeft));
  const customInvalid = f.datePreset === "custom" && !f.dateFrom;
  const canStart =
    !!account && f.keywords.length > 0 && !experienceInvalid(f) && !customInvalid && maxSend > 0 && !running && !starting;

  return (
    <Card>
      <CardHeader title={`Apply on ${name}`} subtitle={`Searches ${EASY_APPLY[site]} and applies with your account.`} />
      <div className="space-y-5 px-5 py-5">
        {account ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-zinc-50/60 px-3 py-2.5 text-[13px]">
            <span className="text-zinc-600">Applying as</span>
            <span className="truncate font-medium text-ink">{account.email}</span>
            {account.last_status === "ok" ? <Badge tone="green">Logged in</Badge> : <Badge tone="amber">Needs login</Badge>}
            <Link href="/accounts" className="ml-auto text-xs text-brand-700 underline-offset-4 hover:underline">Manage</Link>
          </div>
        ) : (
          <Notice tone="warning">
            Applying needs your {name} account.{" "}
            <Link href="/accounts" className="font-medium underline underline-offset-4">Connect it on Accounts</Link>.
          </Notice>
        )}

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
          <Label hint={f.dryRun ? "Up to 50" : `${capLeft} of ${dailyCap} left today`}>Applications to send</Label>
          <Input
            type="number"
            min={1}
            max={Math.max(1, maxSend)}
            value={f.limit}
            disabled={running}
            aria-label="Applications to send"
            onChange={(e) => set("limit", Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
            className="w-24"
          />
          {!f.dryRun && capLeft <= 0 && (
            <p className="mt-1.5 text-xs text-amber-700">Today&apos;s {name} limit is used up. Raise it under Answers &amp; limits, or try tomorrow.</p>
          )}
        </div>

        <div className="space-y-3">
          <label className="flex cursor-pointer items-start gap-2.5">
            <input type="checkbox" checked={f.dryRun} disabled={running} onChange={(e) => set("dryRun", e.target.checked)}
              className="mt-0.5 h-3.5 w-3.5 accent-brand-700" />
            <span>
              <span className="block text-sm text-zinc-800">Dry run (don&apos;t submit)</span>
              <span className="block text-xs leading-5 text-zinc-500">{DRY_RUN_HINT[site]} Try this first on each site.</span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-2.5">
            <input type="checkbox" checked={!f.headless} disabled={running} onChange={(e) => set("headless", !e.target.checked)}
              className="mt-0.5 h-3.5 w-3.5 accent-brand-700" />
            <span>
              <span className="block text-sm text-zinc-800">Show browser window</span>
              <span className="block text-xs leading-5 text-zinc-500">Recommended: you can watch it, and enter an OTP if {name} asks.</span>
            </span>
          </label>
        </div>

        {!f.dryRun && (
          <Notice tone="warning">
            Applications are sent for real, {isPaid ? "with screening questions answered from your Answers and, if needed, the AI" : "with screening questions answered from your Answers"}.
            Jobs with a question it can&apos;t answer are left for you. {name} doesn&apos;t allow automated applying; there&apos;s a
            20–60 s gap between applications and a daily limit to keep your account safe.
          </Notice>
        )}

        {running ? (
          <Button variant="danger" className="w-full" onClick={onStop} disabled={stopping}>
            {stopping ? <><Spinner /> Stopping…</> : "Stop"}
          </Button>
        ) : (
          <Button variant="primary" className="w-full" disabled={!canStart} onClick={() => onStart({ ...f, limit: Math.min(f.limit, Math.max(1, maxSend)) })}>
            {starting ? <><Spinner className="border-white/40 border-t-white" /> Starting…</> : f.dryRun ? "Start dry run" : "Start applying"}
          </Button>
        )}
      </div>
    </Card>
  );
}
