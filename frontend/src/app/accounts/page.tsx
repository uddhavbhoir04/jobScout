"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, timeAgo, type Account, type AccountSite, type JobSummary, type LogEvent } from "@/lib/api";
import { useJobStream } from "@/lib/useJobStream";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorNote, Input, Label, Notice, PageHeader, Segmented, Spinner } from "@/components/ui";

const SITE: Record<AccountSite, { name: string; passwordHint?: string; tip: string }> = {
  linkedin: { name: "LinkedIn", tip: "Tip: a secondary LinkedIn account is safer for automated searching." },
  naukri: {
    name: "Naukri",
    tip: "Logged in, Naukri searches use your account. If Naukri asks for an OTP, enter it in the browser window.",
  },
  indeed: {
    name: "Indeed",
    passwordHint: "Optional",
    tip: "Indeed usually emails you a code: enter it in the browser window that opens. Logged in, searches read more than one page of results.",
  },
};

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [site, setSite] = useState<AccountSite>("linkedin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [adding, setAdding] = useState(false);
  const [login, setLogin] = useState<{ jobId: string; accountId: number; site: AccountSite } | null>(null);
  const { events, status } = useJobStream(login?.jobId ?? null);

  const load = useCallback(() => {
    api<Account[]>("/api/accounts").then(setAccounts).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    if (status && status !== "running") load();
  }, [status, load]);

  const startLogin = async (id: number, accountSite: AccountSite) => {
    setError(null);
    try {
      const job = await api<JobSummary>(`/api/accounts/${id}/login`, { method: "POST" });
      setLogin({ jobId: job.id, accountId: id, site: accountSite });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setAdding(true);
    try {
      const acc = await api<Account>("/api/accounts", { method: "POST", body: JSON.stringify({ platform: site, email, password }) });
      setEmail("");
      setPassword("");
      load();
      await startLogin(acc.id, acc.platform);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAdding(false);
    }
  };

  const toggle = async (a: Account) => {
    await api(`/api/accounts/${a.id}?active=${!a.active}`, { method: "PATCH" }).catch((e) => setError(e.message));
    load();
  };

  const remove = async (a: Account) => {
    if (!confirm(`Remove ${a.email}? Scraped data is kept.`)) return;
    await api(`/api/accounts/${a.id}`, { method: "DELETE" }).catch((e) => setError(e.message));
    load();
  };

  const loginRunning = status === "running";
  const loginLogs = events.filter((e) => e.type === "log" || e.type === "error") as LogEvent[];
  const loginResult = events.find((e) => e.type === "login") as { ok?: boolean } | undefined;

  return (
    <div>
      <PageHeader
        title="Accounts"
        description="The LinkedIn, Naukri and Indeed logins jobscout searches with. Only you can see or use them. Passwords are stored encrypted, and logging in opens a browser window so you can finish any OTP or security check yourself. Naukri and Indeed also work without an account, as a guest."
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-4">
          {error && <ErrorNote message={error} />}

          {login && (
            <Notice tone={loginRunning ? "info" : loginResult?.ok ? "success" : "error"}>
              <div className="flex items-center gap-2">
                {loginRunning ? <Spinner /> : null}
                <span className="font-medium">
                  {loginRunning
                    ? "Waiting for you to finish logging in, in the browser window that just opened."
                    : loginResult?.ok
                      ? "Logged in. The session is saved for future searches."
                      : `The login didn't finish. Try again, and complete any check ${SITE[login.site].name} shows.`}
                </span>
                {!loginRunning && (
                  <button className="ml-auto text-xs underline-offset-4 hover:underline" onClick={() => setLogin(null)}>
                    Dismiss
                  </button>
                )}
              </div>
              {loginLogs.length > 0 && (
                <div className="mt-2 font-mono text-[11px] leading-5 opacity-80">
                  {loginLogs.map((l) => (
                    <div key={l.seq}>{l.message}</div>
                  ))}
                </div>
              )}
            </Notice>
          )}

          <Card>
            <CardHeader
              title="Connected"
              subtitle={accounts ? `${accounts.length} ${accounts.length === 1 ? "account" : "accounts"}` : undefined}
            />
            {accounts === null ? (
              <div className="px-5 py-10 text-center text-sm text-zinc-500">Loading…</div>
            ) : accounts.length === 0 ? (
              <EmptyState title="No accounts yet">Connect one on the right. LinkedIn needs one; Naukri and Indeed are optional.</EmptyState>
            ) : (
              <ul className="divide-y divide-line">
                {accounts.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-3 px-5 py-4">
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-zinc-100 text-xs font-semibold uppercase text-zinc-600">
                      {a.email.slice(0, 2)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium text-ink">{a.email}</span>
                        <Badge dot={false}>{SITE[a.platform]?.name ?? a.platform}</Badge>
                        {!a.active ? (
                          <Badge>Paused</Badge>
                        ) : a.last_status === "ok" ? (
                          <Badge tone="green">Connected</Badge>
                        ) : (
                          <Badge tone="amber">Needs login</Badge>
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-zinc-500">Last login {timeAgo(a.last_login_at)}</p>
                    </div>
                    <div className="flex gap-1">
                      <Button size="sm" onClick={() => startLogin(a.id, a.platform)} disabled={loginRunning}>
                        {loginRunning && login?.accountId === a.id ? <Spinner /> : null} Log in
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => toggle(a)}>{a.active ? "Pause" : "Resume"}</Button>
                      <Button size="sm" variant="ghost" onClick={() => remove(a)} className="text-red-700! hover:bg-red-50 hover:text-red-800!">
                        Remove
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <Card className="lg:self-start">
          <CardHeader title="Connect an account" subtitle="A browser window opens to log in right after you add it." />
          <form onSubmit={add} className="space-y-4 px-5 py-5">
            <Segmented<AccountSite>
              value={site}
              onChange={setSite}
              options={[
                { value: "linkedin", label: "LinkedIn" },
                { value: "naukri", label: "Naukri" },
                { value: "indeed", label: "Indeed" },
              ]}
            />
            <div>
              <Label htmlFor="acc-email">{SITE[site].name} email</Label>
              <Input id="acc-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
            </div>
            <div>
              <Label htmlFor="acc-password" hint={SITE[site].passwordHint}>{SITE[site].name} password</Label>
              <Input id="acc-password" type="password" required={site !== "indeed"} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
            </div>
            <Button variant="primary" type="submit" className="w-full" disabled={adding || loginRunning}>
              {adding ? <Spinner className="border-white/40 border-t-white" /> : null} Connect account
            </Button>
            <p className="text-xs leading-5 text-zinc-500">{SITE[site].tip}</p>
          </form>
        </Card>
      </div>
    </div>
  );
}
