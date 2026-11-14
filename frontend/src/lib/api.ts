// Same origin: every /api/* call goes to a Next.js route handler (src/app/api/**), which forwards it
// to the private Python backend. The httpOnly login cookie is sent automatically.
export const API_URL = "";

export const UNAUTHORIZED_EVENT = "jobscout:unauthorized";
const BACKEND_DOWN = 'Can\'t reach the backend. Is "jobscout serve" running?';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

// is_paid comes from the profile API; paid users get the features that cost API money (Emails).
export type User = { id: number; email: string; name: string | null; is_paid: boolean; plan: "paid" | "free" };

export type Account = {
  id: number;
  platform: string;
  email: string;
  active: boolean;
  last_login_at: string | null;
  last_status: string | null;
};

export type TelegramChannel = {
  id: number;
  name: string;
  url: string;
  title: string | null;
  subscribers: string | null;
  posts_checked: number;
  contact_pct: number | null; // % of recent posts with a recruiter email or phone
  posts_per_day: string | null;
  last_post_at: string | null;
  checked_at: string | null;
  active: boolean;
};

export type JobStatus = "running" | "done" | "error" | "stopped";

export type JobSummary = {
  id: string;
  kind: string;
  status: JobStatus;
  params: Record<string, unknown>;
  started_at: number;
  events: number;
};

export type JobEvent = { seq: number; ts: number; type: string; [key: string]: unknown };

export type PostEvent = JobEvent & {
  type: "post";
  status: "saved" | "skipped";
  reason?: string | null;
  tag: string;
  author?: string | null;
  author_url?: string | null;
  posted?: string | null;
  text: string;
  hiring_for?: string | null;
  contact_name?: string | null;
  emails?: string[];
  phones?: string[];
  post_id?: number;
  counted?: boolean; // gave at least one NEW email/phone (counts toward the target)
  note?: string | null; // why a saved post didn't count
};

export type ProgressEvent = JobEvent & { type: "progress"; scanned: number; saved: number; collected: number; limit: number };
export type LogEvent = JobEvent & { type: "log" | "error"; level?: string; message: string };
export type SummaryEvent = JobEvent & {
  type: "summary";
  run_id: number;
  scanned: number;
  saved: number;
  collected: number;
  limit: number;
  stop_reason: string;
  skipped: Record<string, number>;
  failed_accounts: string[];
  unprocessed_tags: string[];
  stopped: boolean;
};

export type Stats = {
  posts: number;
  contacts: number;
  with_email: number;
  with_phone: number;
  emails: Record<string, number>;
};

export type Contact = {
  id: number;
  name: string | null;
  email: string | null;
  phone: string | null;
  hiring_for: string | null;
  author_url: string | null;
  posts: number;
  created_at: string;
  email_status: string | null;
  sent_at: string | null;
};

export type Post = {
  id: number;
  author: string | null;
  author_url: string | null;
  url: string | null;
  hiring_for: string | null;
  contact_name: string | null;
  emails: string[];
  phones: string[];
  hashtags: string[];
  posted_at: string | null;
  scraped_at: string;
  run_id: number | null;
  text: string;
};

export type Run = {
  id: number;
  hashtags: string[];
  date_filter: string;
  limit: number;
  scanned: number;
  saved: number;
  status: string;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type Page<T> = { total: number; items: T[] };

export type EmailSettings = {
  gmail_address: string | null;
  has_app_password: boolean;
  sender_name: string | null;
  daily_cap: number;
  profile_text: string;
  resume_filename: string | null;
  resume_text_chars: number;
  verified_at: string | null;
  last_error: string | null;
  connected: boolean;
};

export type EmailStatus = "pending" | "drafted" | "sending" | "sent" | "failed" | "bounced" | "replied" | "skipped";

export type Outreach = {
  id: number;
  status: EmailStatus;
  subject: string | null;
  body: string | null;
  attempts: number;
  last_error: string | null;
  scheduled_at: string | null;
  sent_at: string | null;
  updated_at: string;
  contact: { id: number; name: string | null; email: string | null; phone: string | null };
  post: { id: number; hiring_for: string | null; author: string | null; author_url: string | null; text: string } | null;
};

export type EmailStats = Record<EmailStatus, number> & { sent_today: number; daily_cap: number };

export type EmailJobEvent = JobEvent & {
  type: "email";
  id: number;
  outcome: "drafted" | "sent" | "failed" | "retry";
  to: string;
  name: string | null;
  subject: string | null;
  error: string | null;
  source?: string;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(BACKEND_DOWN, 0);
  }
  if (!res.ok) {
    let message = res.status >= 500 ? BACKEND_DOWN : res.statusText;
    try {
      const body = await res.json();
      if (body.detail) message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT)); // session expired: back to login
    }
    throw new ApiError(message, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
