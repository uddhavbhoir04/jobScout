"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api, type User } from "@/lib/api";
import { Logo } from "../AppShell";
import { Button, ErrorNote, Input, Label, Spinner } from "../ui";
import { useAuth } from "./AuthProvider";

const STEPS = [
  {
    title: "Search LinkedIn hiring posts",
    body: "Pick the role hashtags you care about. Every result must also carry #hiring.",
  },
  {
    title: "Keep only posts you can act on",
    body: "Posts are saved when they include a recruiter's email, phone number or a named contact.",
  },
  {
    title: "Reach out from your own Gmail",
    body: "Review a short, honest email for each recruiter, written from your resume, then send it.",
  },
];

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { signedIn } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await api<User>(isLogin ? "/api/auth/login" : "/api/auth/register", {
        method: "POST",
        body: JSON.stringify(isLogin ? { email, password } : { email, password, name: name || null }),
      });
      const next = new URLSearchParams(window.location.search).get("next");
      signedIn(user);
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      {/* product panel */}
      <aside className="hidden flex-col justify-between border-r border-line bg-zinc-100/60 px-12 py-10 lg:flex">
        <Logo />
        <div className="max-w-md">
          <h2 className="text-[26px] font-semibold leading-tight tracking-[-0.015em] text-ink">
            From hiring post to recruiter inbox, without the copy-pasting.
          </h2>
          <ol className="mt-8 space-y-6">
            {STEPS.map((s, i) => (
              <li key={s.title} className="flex gap-4">
                <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border border-zinc-300 bg-surface text-xs font-medium tabular-nums text-zinc-700">
                  {i + 1}
                </span>
                <div>
                  <p className="text-sm font-medium text-ink">{s.title}</p>
                  <p className="mt-0.5 text-sm leading-6 text-zinc-600">{s.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
        <p className="text-xs text-zinc-500">Your LinkedIn and Gmail passwords are stored encrypted and never shown again.</p>
      </aside>

      {/* form */}
      <main className="flex flex-col px-6 py-10 sm:px-10">
        <div className="lg:hidden">
          <Logo />
        </div>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10">
          <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-ink">
            {isLogin ? "Log in" : "Create your account"}
          </h1>
          <p className="mt-1.5 text-sm text-zinc-500">
            {isLogin ? "Welcome back. Pick up where you left off." : "Free to start. Each account keeps its own data."}
          </p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            {!isLogin && (
              <div>
                <Label htmlFor="name" hint="Optional">Full name</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
              </div>
            )}
            <div>
              <Label htmlFor="email">Work or personal email</Label>
              <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                     autoComplete="email" autoFocus />
            </div>
            <div>
              <Label htmlFor="password" hint={isLogin ? undefined : "At least 8 characters"}>Password</Label>
              <Input id="password" type="password" required minLength={isLogin ? 1 : 8} value={password}
                     onChange={(e) => setPassword(e.target.value)}
                     autoComplete={isLogin ? "current-password" : "new-password"} />
            </div>
            <ErrorNote message={error} />
            <Button variant="primary" type="submit" className="h-10 w-full" disabled={busy}>
              {busy ? <Spinner className="border-white/40 border-t-white" /> : null}
              {isLogin ? "Log in" : "Create account"}
            </Button>
          </form>

          <p className="mt-6 text-sm text-zinc-600">
            {isLogin ? "New to jobscout? " : "Already have an account? "}
            <Link href={isLogin ? "/register" : "/login"} className="font-medium text-brand-700 underline-offset-4 hover:underline">
              {isLogin ? "Create an account" : "Log in"}
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
