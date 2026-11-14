"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type EmailSettings, type EmailStats } from "@/lib/api";
import Link from "next/link";
import { useAuth } from "@/components/auth/AuthProvider";
import { buttonClass, Card, ErrorNote, PageHeader, StatRow } from "@/components/ui";
import { OutreachPanel } from "@/components/email/OutreachPanel";
import { ProfileCard } from "@/components/email/ProfileCard";
import { SenderCard } from "@/components/email/SenderCard";

export default function EmailsPage() {
  const { user } = useAuth();
  // RBAC: email outreach uses paid APIs (LLM + Gmail). The backend also refuses free users (403).
  return user?.is_paid ? <EmailsContent /> : <PaidOnly />;
}

function PaidOnly() {
  return (
    <div className="mx-auto max-w-lg pt-10">
      <Card className="px-6 py-8 text-center">
        <span className="inline-block rounded bg-zinc-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-zinc-600">
          Paid feature
        </span>
        <h1 className="mt-3 text-lg font-semibold tracking-[-0.01em] text-ink">Email outreach is on the paid plan</h1>
        <p className="mt-2 text-sm leading-6 text-zinc-500">
          Writing a personal email for every recruiter uses paid AI and email services, so it&apos;s available to paid
          accounts. Scraping posts and collecting recruiter emails and phone numbers stay free.
        </p>
        <div className="mt-5 flex justify-center gap-2">
          <Link href="/data" className={buttonClass("secondary")}>
            View your contacts
          </Link>
          <Link href="/" className={buttonClass("primary")}>
            Go to Scrape
          </Link>
        </div>
      </Card>
    </div>
  );
}

function EmailsContent() {
  const [settings, setSettings] = useState<EmailSettings | null>(null);
  const [stats, setStats] = useState<EmailStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshStats = useCallback(() => {
    api<EmailStats>("/api/email/stats").then(setStats).catch(() => {});
  }, []);

  useEffect(() => {
    api<EmailSettings>("/api/email/settings").then(setSettings).catch((e) => setError(e.message));
    refreshStats();
  }, [refreshStats]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Emails"
        description="Write a short, honest email to each recruiter from your resume, review it, then send it from your own Gmail."
      />
      {stats && (
        <StatRow
          items={[
            { label: "Needs draft", value: stats.pending },
            { label: "Ready to send", value: stats.drafted },
            { label: "Sent", value: stats.sent, accent: true },
            { label: "Failed", value: stats.failed },
            { label: "Sent today", value: `${stats.sent_today} / ${stats.daily_cap}` },
          ]}
        />
      )}

      <ErrorNote message={error} />

      {settings && (
        <div className="grid gap-5 lg:grid-cols-[360px_1fr]">
          <div className="space-y-5">
            <SenderCard settings={settings} onChange={setSettings} />
            <ProfileCard settings={settings} onChange={setSettings} />
          </div>
          <OutreachPanel connected={settings.connected} stats={stats} refreshStats={refreshStats} />
        </div>
      )}
    </div>
  );
}
