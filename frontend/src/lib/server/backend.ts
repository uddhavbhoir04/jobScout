/**
 * Server-side gateway to the Python backend (the "backend for frontend").
 *
 * The browser only ever talks to Next.js route handlers under src/app/api/**. Each handler calls
 * `forward()` for exactly one backend endpoint, so:
 *   - the backend's address and port never reach the browser;
 *   - only endpoints with a route file here are reachable (everything else is a Next.js 404);
 *   - only allow-listed headers travel in either direction;
 *   - every request carries INTERNAL_API_KEY, and the backend rejects calls without it, so the
 *     Python API is useless to anyone who reaches its port directly.
 *
 * Import this only from route handlers (server code). It reads server-only environment variables.
 */
import { headers } from "next/headers";

const BACKEND_URL = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY ?? "";

const MAX_BODY_BYTES = 8 * 1024 * 1024; // resume upload: 5 MB file, base64-encoded in JSON
const TIMEOUT_MS = 60_000; // normal requests; streams (SSE) have no timeout

// Request headers the backend needs. Everything else (host, origin, accept-encoding, ...) is dropped.
const FORWARD_REQUEST = ["cookie", "content-type", "accept", "user-agent", "accept-language"];
// Response headers the browser may see. Server, framework and internal headers are dropped.
const FORWARD_RESPONSE = ["content-type", "content-disposition", "cache-control", "x-accel-buffering", "retry-after"];

const ID_RE = /^\d{1,12}$/;
const JOB_ID_RE = /^[a-f0-9]{8,32}$/;

export function isId(value: string): boolean {
  return ID_RE.test(value);
}

export function isJobId(value: string): boolean {
  return JOB_ID_RE.test(value);
}

export function jsonError(status: number, detail: string): Response {
  return Response.json({ detail }, { status, headers: { "cache-control": "no-store" } });
}

export const notFound = () => jsonError(404, "Not found");

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/** CSRF defence for state-changing requests: they must come from this site's own pages.
 *  Browsers always send Origin (and Sec-Fetch-Site) on POST/PUT/PATCH/DELETE; a request from
 *  another site is refused even though SameSite=Lax would already keep the cookie off it. */
function isSameOrigin(request: Request, incoming: Headers): boolean {
  if (SAFE_METHODS.has(request.method)) return true;
  const site = incoming.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") return false;
  const origin = incoming.get("origin");
  if (!origin) return true; // non-browser client (no cookie-riding risk)
  const host = incoming.get("x-forwarded-host") ?? incoming.get("host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

type ForwardOptions = {
  /** Long-lived response (Server-Sent Events): no timeout, body streamed through as it arrives. */
  stream?: boolean;
};

/** Forward `request` to `backendPath` (plus the request's query string) and relay the response. */
export async function forward(request: Request, backendPath: string, options: ForwardOptions = {}): Promise<Response> {
  if (!INTERNAL_API_KEY && process.env.NODE_ENV === "production") {
    return jsonError(500, "Server misconfigured: INTERNAL_API_KEY is not set.");
  }

  const incoming = await headers(); // runtime data: keeps every API route dynamic (never prerendered)
  if (!isSameOrigin(request, incoming)) return jsonError(403, "Cross-site request blocked.");
  const outgoing = new Headers();
  for (const name of FORWARD_REQUEST) {
    const value = incoming.get(name);
    if (value) outgoing.set(name, value);
  }
  if (INTERNAL_API_KEY) outgoing.set("x-internal-key", INTERNAL_API_KEY);
  const clientIp = incoming.get("x-forwarded-for")?.split(",")[0]?.trim() || incoming.get("x-real-ip");
  if (clientIp) outgoing.set("x-forwarded-for", clientIp);

  let body: ArrayBuffer | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    const declared = Number(request.headers.get("content-length") ?? 0);
    if (declared > MAX_BODY_BYTES) return jsonError(413, "Request is too large.");
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) return jsonError(413, "Request is too large.");
  }

  const search = new URL(request.url).search;
  const signal = options.stream ? request.signal : AbortSignal.any([request.signal, AbortSignal.timeout(TIMEOUT_MS)]);

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}${backendPath}${search}`, {
      method: request.method,
      headers: outgoing,
      body,
      cache: "no-store",
      redirect: "manual",
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "TimeoutError") return jsonError(504, "The server took too long to respond.");
    return jsonError(502, 'Can\'t reach the backend. Is "jobscout serve" running?');
  }

  const out = new Headers();
  for (const name of FORWARD_RESPONSE) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  if (!out.has("cache-control")) out.set("cache-control", "no-store");
  if (options.stream) out.set("cache-control", "no-cache, no-transform");

  return new Response(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: out,
  });
}
