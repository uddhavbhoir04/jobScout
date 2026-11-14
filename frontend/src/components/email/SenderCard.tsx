"use client";

import { useState, type FormEvent } from "react";
import { api, timeAgo, type EmailSettings } from "@/lib/api";
import { Badge, Button, Card, CardHeader, ErrorNote, Input, Label, Notice, Spinner } from "../ui";

/** Connect the Gmail account outreach emails are sent from (Gmail address + App Password). */
export function SenderCard({ settings, onChange }: { settings: EmailSettings; onChange: (s: EmailSettings) => void }) {
  const [editing, setEditing] = useState(!settings.connected);
  const [gmail, setGmail] = useState(settings.gmail_address ?? "");
  const [appPassword, setAppPassword] = useState("");
  const [senderName, setSenderName] = useState(settings.sender_name ?? "");
  const [dailyCap, setDailyCap] = useState(settings.daily_cap);
  const [busy, setBusy] = useState<null | "save" | "test" | "self">(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setBusy("save");
    try {
      const s = await api<EmailSettings>("/api/email/settings", {
        method: "PUT",
        body: JSON.stringify({
          gmail_address: gmail,
          app_password: appPassword || null,
          sender_name: senderName,
          daily_cap: dailyCap,
        }),
      });
      onChange(s);
      setAppPassword("");
      if (s.connected) {
        setBusy("test");
        const r = await api<{ ok: boolean; message: string }>("/api/email/test", { method: "POST", body: "{}" });
        setNotice({ ok: r.ok, text: r.message });
        onChange(await api<EmailSettings>("/api/email/settings"));
        if (r.ok) setEditing(false);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const test = async (sendToSelf: boolean) => {
    setNotice(null);
    setBusy(sendToSelf ? "self" : "test");
    try {
      const r = await api<{ ok: boolean; message: string }>("/api/email/test", {
        method: "POST",
        body: JSON.stringify({ send_to_self: sendToSelf }),
      });
      setNotice({ ok: r.ok, text: r.message });
      onChange(await api<EmailSettings>("/api/email/settings"));
    } catch (err) {
      setNotice({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    if (!confirm("Remove the saved App Password? Sending stops until you connect again.")) return;
    await api("/api/email/settings/password", { method: "DELETE" });
    onChange(await api<EmailSettings>("/api/email/settings"));
    setEditing(true);
  };

  const status = settings.connected ? (
    settings.verified_at ? <Badge tone="green">Connected</Badge> : <Badge tone="amber">Not verified</Badge>
  ) : (
    <Badge tone="amber">Not connected</Badge>
  );

  return (
    <Card>
      <CardHeader title="Gmail sender" subtitle="Emails go out from this address, as you." action={status} />
      <div className="space-y-4 px-5 py-5">
        {!editing && settings.connected ? (
          <>
            <div className="text-sm">
              <div className="font-medium text-ink">
                {settings.sender_name ? `${settings.sender_name} <${settings.gmail_address}>` : settings.gmail_address}
              </div>
              <div className="mt-0.5 text-xs text-zinc-500">
                Up to {settings.daily_cap} emails a day ·{" "}
                {settings.verified_at ? `verified ${timeAgo(settings.verified_at)}` : "login not verified yet"}
              </div>
            </div>
            {settings.last_error && <ErrorNote message={settings.last_error} />}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => test(false)} disabled={!!busy}>
                {busy === "test" ? <Spinner /> : null} Test login
              </Button>
              <Button size="sm" onClick={() => test(true)} disabled={!!busy}>
                {busy === "self" ? <Spinner /> : null} Send me a test email
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>Edit</Button>
              <Button size="sm" variant="ghost" onClick={disconnect} className="text-red-700! hover:bg-red-50">Disconnect</Button>
            </div>
          </>
        ) : (
          <form onSubmit={save} className="space-y-4">
            <div>
              <Label>Gmail address</Label>
              <Input type="email" required value={gmail} onChange={(e) => setGmail(e.target.value)} placeholder="you@gmail.com" />
            </div>
            <div>
              <Label hint={settings.has_app_password ? "saved; leave empty to keep" : "16 letters"}>App Password</Label>
              <Input
                type="password"
                value={appPassword}
                required={!settings.has_app_password}
                onChange={(e) => setAppPassword(e.target.value)}
                placeholder={settings.has_app_password ? "••••••••••••••••" : "abcd efgh ijkl mnop"}
                autoComplete="new-password"
              />
              <p className="mt-1.5 text-xs leading-5 text-zinc-500">
                Not your normal Gmail password. Turn on 2-Step Verification, then create one at{" "}
                <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer" className="font-medium text-zinc-800 underline">
                  Google Account → App passwords
                </a>
                .
              </p>
            </div>
            <div className="grid grid-cols-[1fr_96px] gap-3">
              <div>
                <Label hint="shown to recipients">Your name</Label>
                <Input value={senderName} onChange={(e) => setSenderName(e.target.value)} placeholder="Your name" />
              </div>
              <div>
                <Label>Per day</Label>
                <Input type="number" min={1} max={200} value={dailyCap} onChange={(e) => setDailyCap(Math.max(1, Math.min(200, Number(e.target.value) || 1)))} />
              </div>
            </div>
            <ErrorNote message={error} />
            <div className="flex gap-2">
              <Button variant="primary" type="submit" disabled={!!busy}>
                {busy ? <Spinner /> : null} {busy === "test" ? "Testing login…" : "Save & test"}
              </Button>
              {settings.connected && (
                <Button type="button" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
              )}
            </div>
          </form>
        )}
        {notice && (
          <Notice tone={notice.ok ? "success" : "error"}>{notice.text}</Notice>
        )}
      </div>
    </Card>
  );
}
