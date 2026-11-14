"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, UNAUTHORIZED_EVENT, type User } from "@/lib/api";
import { Spinner } from "../ui";

const PUBLIC_PATHS = ["/login", "/register"];

type AuthState = {
  user: User | null;
  signedIn: (u: User) => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Loads the logged-in user and keeps logged-out visitors on /login. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [checked, setChecked] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    api<User>("/api/profile")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setChecked(true));
    const onUnauthorized = () => setUser(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  useEffect(() => {
    if (!checked) return;
    if (!user && !isPublic) router.replace(pathname === "/" ? "/login" : `/login?next=${encodeURIComponent(pathname)}`);
    if (user && isPublic) router.replace("/");
  }, [checked, user, isPublic, pathname, router]);

  const signedIn = useCallback((u: User) => setUser(u), []);
  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
      router.replace("/login");
    }
  }, [router]);

  const waiting = !checked || (!user && !isPublic) || (user && isPublic);
  return (
    <AuthContext.Provider value={{ user, signedIn, logout }}>
      {waiting ? (
        <div className="grid min-h-dvh place-items-center text-sm text-zinc-500">
          <span className="flex items-center gap-2">
            <Spinner /> Loading…
          </span>
        </div>
      ) : (
        children
      )}
    </AuthContext.Provider>
  );
}
