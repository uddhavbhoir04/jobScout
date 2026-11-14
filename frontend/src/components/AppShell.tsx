"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "./auth/AuthProvider";
import { cn } from "./ui";

/* 16px line icons, 1.5 stroke, drawn for this app (no icon font). */
const I = {
  search: <><circle cx="7" cy="7" r="4.25" /><path d="M10.25 10.25 13.5 13.5" /></>,
  link: <><path d="M6.5 9.5 9.5 6.5" /><path d="M7.25 4.5 8.5 3.25a2.5 2.5 0 0 1 3.5 3.5L10.75 8" /><path d="M8.75 11.5 7.5 12.75a2.5 2.5 0 0 1-3.5-3.5L5.25 8" /></>,
  mail: <><rect x="2.25" y="3.5" width="11.5" height="9" rx="1.25" /><path d="m2.75 4.5 5.25 4 5.25-4" /></>,
  table: <><rect x="2.25" y="2.75" width="11.5" height="10.5" rx="1.25" /><path d="M2.25 6.25h11.5M6.25 6.25v7" /></>,
  menu: <><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" /></>,
  close: <><path d="m4 4 8 8M12 4l-8 8" /></>,
  out: <><path d="M6.5 13.25H4a1.25 1.25 0 0 1-1.25-1.25V4A1.25 1.25 0 0 1 4 2.75h2.5" /><path d="M10.5 11 13.5 8l-3-3M13.25 8H6.5" /></>,
};

export function Icon({ name, className }: { name: keyof typeof I; className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
         strokeLinejoin="round" className={cn("h-4 w-4 shrink-0", className)} aria-hidden>
      {I[name]}
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <span className="grid h-7 w-7 place-items-center rounded-md bg-brand-700 text-[13px] font-semibold leading-none text-white">
        j
      </span>
      {!compact && <span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">jobscout</span>}
    </span>
  );
}

type NavItem = { href: string; label: string; icon: keyof typeof I; paidOnly?: boolean };
const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Find leads",
    items: [
      { href: "/", label: "Scrape", icon: "search" },
      { href: "/accounts", label: "LinkedIn accounts", icon: "link" },
    ],
  },
  { group: "Outreach", items: [{ href: "/emails", label: "Emails", icon: "mail", paidOnly: true }] },
  { group: "Data", items: [{ href: "/data", label: "Contacts & posts", icon: "table" }] },
];

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  if (!user) return null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center border-b border-line px-4">
        <Link href="/" onClick={onNavigate}><Logo /></Link>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4" aria-label="Main">
        {NAV.map((section) => {
          const items = section.items.filter((i) => !i.paidOnly || user.is_paid);
          if (!items.length) return null;
          return (
            <div key={section.group}>
              <p className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-[0.06em] text-zinc-500">{section.group}</p>
              <ul className="space-y-0.5">
                {items.map((item) => {
                  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13.5px] transition-colors",
                          active ? "bg-zinc-100 font-medium text-ink" : "text-zinc-600 hover:bg-zinc-100/70 hover:text-ink",
                        )}
                      >
                        <Icon name={item.icon} className={active ? "text-brand-700" : "text-zinc-500"} />
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}

        {!user.is_paid && (
          <div className="mx-1 rounded-md border border-line bg-zinc-50 px-3 py-2.5 text-xs leading-5 text-zinc-600">
            <span className="font-medium text-zinc-800">Free plan.</span> Email outreach (AI-written emails sent from your
            Gmail) is available on the paid plan.
          </div>
        )}
      </nav>

      <div className="border-t border-line p-3">
        <div className="flex items-center gap-2.5 rounded-md px-1.5 py-1.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-zinc-200 text-xs font-semibold uppercase text-zinc-700">
            {(user.name || user.email).slice(0, 1)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-[13px] font-medium text-ink">{user.name || user.email.split("@")[0]}</span>
              <span className={cn(
                "shrink-0 rounded px-1 py-px text-[10px] font-semibold uppercase tracking-wide",
                user.is_paid ? "bg-brand-700 text-white" : "bg-zinc-200 text-zinc-600",
              )}>
                {user.is_paid ? "Paid" : "Free"}
              </span>
            </div>
            <div className="truncate text-xs text-zinc-500">{user.email}</div>
          </div>
          <button
            onClick={logout}
            title="Log out"
            aria-label="Log out"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-zinc-500 hover:bg-zinc-100 hover:text-ink"
          >
            <Icon name="out" />
          </button>
        </div>
      </div>
    </div>
  );
}

/** Logged-in layout: fixed sidebar on desktop, top bar + drawer on small screens. */
export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="min-h-dvh">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 border-r border-line bg-surface lg:block">
        <SidebarNav />
      </aside>

      {/* mobile top bar */}
      <div className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-surface px-4 lg:hidden">
        <Link href="/"><Logo /></Link>
        <button onClick={() => setOpen(true)} aria-label="Open menu" className="grid h-9 w-9 place-items-center rounded-md hover:bg-zinc-100">
          <Icon name="menu" />
        </button>
      </div>
      {open && (
        <div className="fixed inset-0 z-30 lg:hidden" key={pathname}>
          <div className="absolute inset-0 bg-zinc-950/30" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 border-r border-line bg-surface shadow-pop">
            <button onClick={() => setOpen(false)} aria-label="Close menu"
                    className="absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-md hover:bg-zinc-100">
              <Icon name="close" />
            </button>
            <SidebarNav onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <main className="lg:pl-60">
        <div className="mx-auto w-full max-w-[1200px] px-4 py-6 sm:px-8 sm:py-8">{children}</div>
      </main>
    </div>
  );
}
