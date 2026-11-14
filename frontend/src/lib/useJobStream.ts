"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL, type JobEvent, type JobStatus } from "./api";

type StreamState = { jobId: string | null; events: JobEvent[]; status: JobStatus | null };

/** Streams a backend job's events (Server-Sent Events).
 *
 *  The first connection replays the job from the start, so a page reload mid-scrape shows everything
 *  that already happened. Any later reconnect (dev hot reload, StrictMode re-running effects, network
 *  blip) resumes after the last event we already have, and events are de-duplicated by `seq`. */
export function useJobStream(jobId: string | null) {
  const [state, setState] = useState<StreamState>({ jobId: null, events: [], status: null });
  // highest seq received per job; survives effect re-runs
  const lastSeqRef = useRef<{ jobId: string | null; seq: number }>({ jobId: null, seq: -1 });

  useEffect(() => {
    if (!jobId) return;
    if (lastSeqRef.current.jobId !== jobId) lastSeqRef.current = { jobId, seq: -1 };

    let pending: JobEvent[] = [];
    let endStatus: JobStatus | null = null;
    let frame = 0;
    const since = lastSeqRef.current.seq + 1;
    const source = new EventSource(`${API_URL}/api/jobs/${jobId}/events?since=${since}`);

    const flush = () => {
      frame = 0;
      const chunk = pending;
      pending = [];
      setState((prev) => {
        if (prev.jobId !== jobId) return { jobId, events: chunk, status: endStatus ?? "running" };
        const last = prev.events.length ? prev.events[prev.events.length - 1].seq : -1;
        const fresh = chunk.filter((e) => e.seq > last);
        return {
          jobId,
          events: fresh.length ? [...prev.events, ...fresh] : prev.events,
          status: endStatus ?? prev.status,
        };
      });
    };

    source.onmessage = (msg) => {
      const ev = JSON.parse(msg.data) as JobEvent;
      if (ev.seq <= lastSeqRef.current.seq) return; // already have it (e.g. browser auto-reconnect)
      lastSeqRef.current.seq = ev.seq;
      pending.push(ev);
      if (ev.type === "end") {
        endStatus = ev.status as JobStatus;
        source.close();
      }
      if (!frame) frame = requestAnimationFrame(flush);
    };

    return () => {
      source.close();
      if (frame) cancelAnimationFrame(frame);
      // events received but not yet flushed would be lost; rewind so the next connection re-sends them
      if (pending.length && lastSeqRef.current.jobId === jobId) {
        lastSeqRef.current.seq = pending[0].seq - 1;
      }
    };
  }, [jobId]);

  if (!jobId) return { events: [] as JobEvent[], status: null };
  if (state.jobId !== jobId) return { events: [] as JobEvent[], status: "running" as JobStatus };
  return { events: state.events, status: state.status ?? ("running" as JobStatus) };
}
