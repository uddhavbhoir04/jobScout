"""Background jobs (scrape, login) with an append-only event log that the UI streams."""
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    kind: str
    params: dict[str, Any]
    user_id: int | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    events: list[dict] = field(default_factory=list)
    status: str = "running"          # running | done | error | stopped
    started_at: float = field(default_factory=time.time)
    stop_requested: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def emit(self, event: dict) -> None:
        with self._lock:
            event = {"seq": len(self.events), "ts": time.time(), **event}
            self.events.append(event)

    def since(self, seq: int) -> list[dict]:
        with self._lock:
            return self.events[seq:]

    def summary(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "params": self.params,
                "started_at": self.started_at, "events": len(self.events)}


class _JobLogHandler(logging.Handler):
    """Forward jobscout log lines from the job's thread into the job's event log."""

    def __init__(self, job: Job, thread_id: int):
        super().__init__(level=logging.INFO)
        self.job, self.thread_id = job, thread_id

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self.thread_id or not record.name.startswith("jobscout"):
            return
        self.job.emit({"type": "log", "level": record.levelname.lower(), "message": record.getMessage()})


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def running(self, kind: str | tuple[str, ...] | None = None, user_id: int | None = None) -> Job | None:
        kinds = (kind,) if isinstance(kind, str) else kind
        with self._lock:
            for job in reversed(list(self.jobs.values())):
                if job.status == "running" and (kinds is None or job.kind in kinds) and job.user_id == user_id:
                    return job
        return None

    def count_running(self, kinds: tuple[str, ...], where: Callable[["Job"], bool] | None = None) -> int:
        """Running jobs of these kinds across all users (optionally only those matching `where`)."""
        with self._lock:
            return sum(1 for j in self.jobs.values()
                       if j.status == "running" and j.kind in kinds and (where is None or where(j)))

    def latest(self, kind: str | tuple[str, ...], user_id: int | None = None) -> Job | None:
        kinds = (kind,) if isinstance(kind, str) else kind
        with self._lock:
            for job in reversed(list(self.jobs.values())):
                if job.kind in kinds and job.user_id == user_id:
                    return job
        return None

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def start(self, kind: str, params: dict, target: Callable[[Job], Any], user_id: int | None = None) -> Job:
        job = Job(kind=kind, params=params, user_id=user_id)
        with self._lock:
            self.jobs[job.id] = job

        def runner() -> None:
            handler = _JobLogHandler(job, threading.get_ident())
            root = logging.getLogger("jobscout")
            root.addHandler(handler)
            root.setLevel(logging.INFO)
            try:
                target(job)
                if job.status == "running":
                    job.status = "stopped" if job.stop_requested else "done"
            except Exception as e:  # surface every failure to the UI
                job.status = "error"
                job.emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
            finally:
                root.removeHandler(handler)
                job.emit({"type": "end", "status": job.status})

        threading.Thread(target=runner, name=f"job-{kind}-{job.id}", daemon=True).start()
        return job


manager = JobManager()
