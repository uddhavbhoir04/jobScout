"use client";

import type { ReactNode } from "react";
import { AppShell } from "./AppShell";
import { useAuth } from "./auth/AuthProvider";

/** Logged in: sidebar app shell. Logged out (login / sign-up): the page renders its own full-screen layout. */
export function Frame({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return user ? <AppShell>{children}</AppShell> : <>{children}</>;
}
