"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Account, type AccountSite, type ApplySettings, type JobSummary } from "@/lib/api";
import { useJobStream } from "@/lib/useJobStream";
import { useAuth } from "@/components/auth/AuthProvider";
import { ErrorNote, PageHeader, Segmented } from "@/components/ui";
import { AnswersCard } from "@/components/apply/AnswersCard";
import { ApplicationsList } from "@/components/apply/ApplicationsList";
import { ApplyPanel, type ApplyFilters } from "@/components/apply/ApplyPanel";
import { jobFilterParams } from "@/components/scrape/JobFilters";
import { LiveFeed } from "@/components/scrape/LiveFeed";

type Tab = "run" | "answers" | "applications";
const SITES: AccountSite[] = ["linkedin", "naukri", "indeed"];

export default function ApplyPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("run");
  const [site, setSite] = useState<AccountSite>("linkedin");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [settings, setSettings] = useState<ApplySettings | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopRequested, setStopRequested] = useState(false);
  const { events, status } = useJobStream(jobId);
  const running = status === "running";

  const loadSettings = useCallback(() => {
    api<ApplySettings>("/api/apply/settings").then(setSettings).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    api<Account[]>("/api/accounts").then(setAccounts).catch((e) => setError(e.message));
    loadSettings();
    api<JobSummary | null>("/api/jobs/current?kind=apply")
      .then((j) => {
        if (!j) return;
        setJobId(j.id);
        const s = j.params.source as AccountSite;
        if (j.status === "running" && SITES.includes(s)) setSite(s);
      })
      .catch(() => {});
  }, [loadSettings]);

  // refresh today's counts as applications go out, and the accounts' login state at the end
  const sent = events.filter((e) => e.type === "post" && e.status === "saved").length;
  useEffect(() => {
    if (sent) loadSettings();
  }, [sent, loadSettings]);
  useEffect(() => {
    if (status && status !== "running") {
      loadSettings();
      api<Account[]>("/api/accounts").then(setAccounts).catch(() => {});
    }
  }, [status, loadSettings]);

  const start = async (f: ApplyFilters) => {
    setError(null);
    setStopRequested(false);
    setStarting(true);
    try {
      const job = await api<JobSummary>("/api/apply", {
        method: "POST",
        body: JSON.stringify({
          source: site,
          keywords: f.keywords,
          date_filter: f.datePreset === "custom" ? "today" : f.datePreset,
          date_from: f.datePreset === "custom" ? f.dateFrom || null : null,
          date_to: f.datePreset === "custom" ? f.dateTo || null : null,
          limit: f.limit,
          dry_run: f.dryRun,
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

  const capLeft = settings ? Math.max(0, settings.daily_cap - (settings.applied_today[site] ?? 0)) : 0;

  return (
    <div>
      <PageHeader
        title="Auto apply"
        description="Applies to Easy Apply jobs on LinkedIn, Naukri and Indeed with your accounts, answering screening questions from your answers. Jobs it can't answer for are left for you."
      />
      {error && <div className="mb-4"><ErrorNote message={error} /></div>}

      <div className="mb-5">
        <Segmented<Tab>
          value={tab}
          onChange={setTab}
          options={[
            { value: "run", label: "Run" },
            { value: "answers", label: "Answers & limits" },
            { value: "applications", label: "Applications" },
          ]}
        />
      </div>

      {tab === "run" && (
        <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
          <div className="space-y-3 lg:sticky lg:top-6 lg:self-start">
            <Segmented<AccountSite>
              value={site}
              onChange={(s) => !running && setSite(s)}
              options={[
                { value: "linkedin", label: "LinkedIn" },
                { value: "naukri", label: "Naukri" },
                { value: "indeed", label: "Indeed" },
              ]}
            />
            <ApplyPanel
              key={`${site}-${user?.id}`}
              site={site}
              userId={user?.id ?? 0}
              accounts={accounts.filter((a) => a.platform === site)}
              capLeft={capLeft}
              dailyCap={settings?.daily_cap ?? 25}
              isPaid={!!user?.is_paid}
              running={running}
              starting={starting}
              stopping={stopRequested && running}
              onStart={start}
              onStop={stop}
            />
          </div>
          <LiveFeed events={events} status={status} />
        </div>
      )}

      {tab === "answers" && settings && (
        <div className="max-w-3xl">
          <AnswersCard key={user?.id} settings={settings} isPaid={!!user?.is_paid} onSaved={setSettings} />
        </div>
      )}

      {tab === "applications" && <ApplicationsList refreshKey={sent + (status === "running" ? 0 : 1)} onError={setError} />}
    </div>
  );
}
