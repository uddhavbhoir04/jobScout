"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Account, type JobSummary, type Stats } from "@/lib/api";
import { useJobStream } from "@/lib/useJobStream";
import { useAuth } from "../auth/AuthProvider";
import { ErrorNote, PageHeader, Segmented, StatRow } from "../ui";
import { FilterPanel, type Filters } from "./FilterPanel";
import { jobFilterParams } from "./JobFilters";
import { LiveFeed } from "./LiveFeed";
import { TelegramPanel, type TelegramFilters } from "./TelegramPanel";

type Source = "linkedin" | "telegram";
const sourceKey = (userId: number) => `jobscout.source.user-${userId}`;

function loadSource(userId: number): Source {
  if (typeof window === "undefined") return "linkedin";
  try {
    return localStorage.getItem(sourceKey(userId)) === "telegram" ? "telegram" : "linkedin";
  } catch {
    return "linkedin";
  }
}

export function ScrapeView() {
  const { user } = useAuth();
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopRequested, setStopRequested] = useState(false);
  const [source, setSourceState] = useState<Source>(() => loadSource(user?.id ?? 0));
  const setSource = (s: Source) => {
    setSourceState(s);
    try {
      localStorage.setItem(sourceKey(user?.id ?? 0), s);
    } catch {}
  };
  const { events, status } = useJobStream(jobId);
  const running = status === "running";
  const stopping = stopRequested && running;

  const refreshStats = useCallback(() => {
    api<Stats>("/api/stats").then(setStats).catch(() => {});
  }, []);

  useEffect(() => {
    api<Account[]>("/api/accounts")
      .then(setAccounts)
      .catch((e) => {
        setAccounts([]);
        setError(e.message);
      });
    api<JobSummary | null>("/api/jobs/current?kind=scrape")
      .then((j) => {
        if (!j) return;
        setJobId(j.id);
        if (j.status === "running") setSourceState(j.params.source === "telegram" ? "telegram" : "linkedin");
      })
      .catch(() => {});
    refreshStats();
  }, [refreshStats]);

  // keep the header numbers fresh while saving
  const savedCount = events.filter((e) => e.type === "post" && e.status === "saved").length;
  useEffect(() => {
    if (savedCount) refreshStats();
  }, [savedCount, refreshStats]);

  useEffect(() => {
    if (status && status !== "running") {
      refreshStats();
      api<Account[]>("/api/accounts").then(setAccounts).catch(() => {});
    }
  }, [status, refreshStats]);

  const start = async (f: Filters) => {
    setError(null);
    setStopRequested(false);
    setStarting(true);
    try {
      const job = await api<JobSummary>("/api/scrape", {
        method: "POST",
        body: JSON.stringify({
          tags: f.tags,
          date_filter: f.datePreset === "custom" ? "today" : f.datePreset,
          date_from: f.datePreset === "custom" ? f.dateFrom || null : null,
          date_to: f.datePreset === "custom" ? f.dateTo || null : null,
          limit: f.limit,
          account_ids: f.accountIds === "all" ? null : f.accountIds,
          headless: f.headless,
          ...jobFilterParams(f),
        }),
      });
      setJobId(job.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const startTelegram = async (f: TelegramFilters) => {
    setError(null);
    setStopRequested(false);
    setStarting(true);
    try {
      const job = await api<JobSummary>("/api/scrape", {
        method: "POST",
        body: JSON.stringify({
          source: "telegram",
          keywords: f.keywords,
          date_filter: f.datePreset === "custom" ? "today" : f.datePreset,
          date_from: f.datePreset === "custom" ? f.dateFrom || null : null,
          date_to: f.datePreset === "custom" ? f.dateTo || null : null,
          limit: f.limit,
          ...jobFilterParams(f),
        }),
      });
      setJobId(job.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const stop = async () => {
    if (!jobId) return;
    setStopRequested(true);
    try {
      await api(`/api/jobs/${jobId}/stop`, { method: "POST" });
    } catch (e) {
      setError((e as Error).message);
      setStopRequested(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Scrape"
        description="Search LinkedIn hiring posts or public Telegram job channels. Posts with a recruiter email, phone number or named contact are saved to your contacts."
      />

      {stats && (
        <StatRow
          className="mb-6"
          items={[
            { label: "Contacts", value: stats.contacts },
            { label: "With email", value: stats.with_email },
            { label: "With phone", value: stats.with_phone },
            { label: "Saved posts", value: stats.posts },
          ]}
        />
      )}

      {error && <div className="mb-4"><ErrorNote message={error} /></div>}

      <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-3 lg:sticky lg:top-6 lg:self-start">
          <Segmented<Source>
            value={source}
            onChange={setSource}
            options={[
              { value: "linkedin", label: "LinkedIn" },
              { value: "telegram", label: "Telegram" },
            ]}
          />
          {source === "telegram" ? (
            <TelegramPanel key={user?.id} userId={user?.id ?? 0} running={running} starting={starting} stopping={stopping} onStart={startTelegram} onStop={stop} />
          ) : accounts === null ? (
            <div className="h-[560px] animate-pulse rounded-lg border border-line bg-surface" />
          ) : (
            <FilterPanel key={user?.id} userId={user?.id ?? 0} accounts={accounts} running={running} starting={starting} stopping={stopping} onStart={start} onStop={stop} />
          )}
        </div>
        <LiveFeed events={events} status={status} />
      </div>
    </div>
  );
}
