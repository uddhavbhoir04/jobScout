"use client";

import { useEffect, useState } from "react";
import { api, API_URL, timeAgo, type Contact, type Page, type Post, type Run } from "@/lib/api";
import { Badge, buttonClass, Card, cn, emailStatusTone, EmptyState, ErrorNote, Input, PageHeader, Segmented } from "@/components/ui";

type Tab = "contacts" | "posts" | "runs";

export default function DataPage() {
  const [tab, setTab] = useState<Tab>("contacts");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div>
      <PageHeader
        title="Contacts & posts"
        description="Everyone you've found, the posts they came from, and your search history. Each email and phone number appears once."
        actions={
          <div className="flex gap-2">
            <a href={`${API_URL}/api/contacts.xlsx`} className={buttonClass("secondary", "md")}>
              Export Excel
            </a>
            <a href={`${API_URL}/api/contacts.csv`} className={buttonClass("secondary", "md")}>
              Export CSV
            </a>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Segmented<Tab>
          value={tab}
          onChange={setTab}
          options={[
            { value: "contacts", label: "Contacts" },
            { value: "posts", label: "Posts" },
            { value: "runs", label: "Search history" },
          ]}
        />
        {tab !== "runs" && (
          <div className="w-full max-w-xs">
            <Input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={tab === "contacts" ? "Search name, email, phone, role" : "Search author, role or text"}
              aria-label={`Search ${tab}`}
            />
          </div>
        )}
      </div>

      {error && <div className="mb-4"><ErrorNote message={error} /></div>}

      {tab === "contacts" && <ContactsTable query={query} onError={setError} />}
      {tab === "posts" && <PostsList query={query} onError={setError} />}
      {tab === "runs" && <RunsTable onError={setError} />}
    </div>
  );
}

function ContactsTable({ query, onError }: { query: string; onError: (m: string) => void }) {
  const [data, setData] = useState<Page<Contact> | null>(null);
  useEffect(() => {
    api<Page<Contact>>(`/api/contacts?q=${encodeURIComponent(query)}`).then(setData).catch((e) => onError(e.message));
  }, [query, onError]);

  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line bg-zinc-50 text-xs text-zinc-500">
            <tr>
              <Th>Name</Th>
              <Th>Email</Th>
              <Th>Phone</Th>
              <Th>Hiring for</Th>
              <Th className="whitespace-nowrap">Outreach</Th>
              <Th className="text-right">Posts</Th>
              <Th>Added</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {data?.items.map((c) => (
              <tr key={c.id} className="transition-colors hover:bg-zinc-50">
                <Td className="whitespace-nowrap">
                  {c.author_url ? (
                    <a href={c.author_url} target="_blank" rel="noreferrer" className="font-medium text-ink underline-offset-4 hover:underline">
                      {c.name || "—"}
                    </a>
                  ) : (
                    <span className="font-medium text-ink">{c.name || "—"}</span>
                  )}
                </Td>
                <Td className="whitespace-nowrap font-mono text-[12.5px] text-zinc-800">{c.email || <Muted />}</Td>
                <Td className="whitespace-nowrap font-mono text-[12.5px] text-zinc-800">{c.phone || <Muted />}</Td>
                <Td className="text-zinc-600" title={c.hiring_for ?? undefined}>
                  <div className="max-w-[22rem] truncate">{c.hiring_for || <Muted />}</div>
                </Td>
                <Td>{c.email_status ? <Badge tone={emailStatusTone(c.email_status)}>{STATUS_LABEL[c.email_status] ?? c.email_status}</Badge> : <Muted />}</Td>
                <Td className="text-right tabular-nums">{c.posts}</Td>
                <Td className="whitespace-nowrap text-xs text-zinc-500">{timeAgo(c.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && data.total === 0 ? (
        <EmptyState title={query ? "No contacts match your search" : "No contacts yet"}>
          {query ? "Try a different name, email or role." : "Run a search on the Scrape page. Recruiters with an email or phone number show up here."}
        </EmptyState>
      ) : (
        <Footer loaded={data !== null} shown={data?.items.length ?? 0} total={data?.total ?? 0} noun="contacts" />
      )}
    </Card>
  );
}

function PostsList({ query, onError }: { query: string; onError: (m: string) => void }) {
  const [data, setData] = useState<Page<Post> | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    api<Page<Post>>(`/api/posts?q=${encodeURIComponent(query)}`).then(setData).catch((e) => onError(e.message));
  }, [query, onError]);

  return (
    <Card className="divide-y divide-line">
      {data?.items.map((p) => (
        <article key={p.id} className="px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            {p.author_url ? (
              <a href={p.author_url} target="_blank" rel="noreferrer" className="text-sm font-medium text-zinc-900 hover:underline">
                {p.author || "Unknown"}
              </a>
            ) : (
              <span className="text-sm font-medium text-ink">{p.author || "Unknown"}</span>
            )}
            <span className="text-xs text-zinc-500">Posted about {timeAgo(p.posted_at)} · search #{p.run_id}</span>
            <span className="ml-auto flex flex-wrap gap-1">{p.hashtags.map((h) => <Badge key={h} dot={false}><span className="font-mono">{h}</span></Badge>)}</span>
          </div>
          {p.hiring_for && <p className="mt-1.5 text-sm text-zinc-700">{p.hiring_for}</p>}
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[12.5px] text-zinc-800">
            {p.emails.map((e) => <span key={e}>{e}</span>)}
            {p.phones.map((ph) => <span key={ph}>{ph}</span>)}
          </div>
          <button onClick={() => setOpen(open === p.id ? null : p.id)} className="mt-2 text-xs font-medium text-zinc-500 hover:text-ink">
            {open === p.id ? "Hide post" : "Read post"}
          </button>
          {open === p.id && <p className="mt-2 whitespace-pre-line rounded-md bg-zinc-50 p-3 text-xs leading-5 text-zinc-700">{p.text}</p>}
        </article>
      ))}
      {data && data.items.length === 0 && (
        <EmptyState title={query ? "No posts match your search" : "No saved posts yet"}>
          {query ? "Try a different word or role." : "Posts you save while scraping appear here with their full text."}
        </EmptyState>
      )}
      {data && data.total > data.items.length && (
        <p className="px-5 py-2.5 text-xs text-zinc-500">Showing {data.items.length} of {data.total}</p>
      )}
      {data === null && <p className="px-5 py-10 text-center text-sm text-zinc-500">Loading…</p>}
    </Card>
  );
}

function RunsTable({ onError }: { onError: (m: string) => void }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  useEffect(() => {
    api<Run[]>("/api/runs?limit=50").then(setRuns).catch((e) => onError(e.message));
  }, [onError]);
  return (
    <Card className="overflow-hidden">
      {runs && runs.length === 0 ? (
        <EmptyState title="No searches yet">Your search history appears here after your first run.</EmptyState>
      ) : (
      <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line bg-zinc-50 text-xs text-zinc-500">
          <tr>
            <Th>Search</Th>
            <Th>Hashtags</Th>
            <Th>Posted</Th>
            <Th className="text-right">Checked</Th>
            <Th className="text-right">Collected</Th>
            <Th>Status</Th>
            <Th>Started</Th>
            <Th><span className="sr-only">Export</span></Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {runs?.map((r) => (
            <tr key={r.id}>
              <Td className="tabular-nums text-zinc-500">#{r.id}</Td>
              <Td className="font-mono text-[12.5px] text-zinc-700">{r.hashtags.join(" ")}</Td>
              <Td className="whitespace-nowrap text-zinc-600">{r.date_filter.replace(/-/g, " ")}</Td>
              <Td className="text-right tabular-nums">{r.scanned}</Td>
              <Td className="text-right tabular-nums font-medium">{r.saved}/{r.limit}</Td>
              <Td>
                <Badge tone={r.status === "completed" ? "green" : r.status === "failed" ? "red" : "blue"}>
                  {r.status === "completed" ? "Completed" : r.status === "failed" ? "Failed" : "Running"}
                </Badge>
              </Td>
              <Td className="whitespace-nowrap text-xs text-zinc-500">{timeAgo(r.started_at)}</Td>
              <Td className="text-right">
                {r.status !== "running" && (
                  <a href={`${API_URL}/api/contacts.xlsx?run_id=${r.id}`} className={cn(buttonClass("secondary", "sm"), "whitespace-nowrap")}>
                    Export Excel
                  </a>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      )}
    </Card>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return <th scope="col" className={cn("px-4 py-2.5 font-medium", className)}>{children}</th>;
}

function Td({ children, className, title }: { children: React.ReactNode; className?: string; title?: string }) {
  return <td className={cn("px-4 py-3 align-middle", className)} title={title}>{children}</td>;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "Needs draft",
  drafted: "Ready to send",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
  bounced: "Bounced",
  replied: "Replied",
  skipped: "Not sending",
};

function Muted() {
  return <span className="text-zinc-300">—</span>;
}

function Footer({ loaded, shown, total, noun }: { loaded: boolean; shown: number; total: number; noun: string }) {
  return (
    <div className="border-t border-line px-4 py-2.5 text-xs text-zinc-500">
      {!loaded ? "Loading…" : total === 0 ? `No ${noun} yet.` : `Showing ${shown} of ${total} ${noun}`}
    </div>
  );
}
