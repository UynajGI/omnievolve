"""Bounded single-machine job executor with leases and failure retries."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from omnievolve.storage.job_store import Job, JobStore

JobHandler = Callable[[Job], str | None]


@dataclass(frozen=True)
class ExecutorReport:
    completed: int
    failed: int
    retried: int


class LocalTaskExecutor:
    """Drain a JobStore using bounded threads on one machine.

    JobStore remains the source of truth. Exceptions are persisted with
    ``fail_job`` and retried up to each job's ``max_attempts``.
    """

    def __init__(
        self,
        store: JobStore,
        handlers: Mapping[str, JobHandler],
        *,
        max_concurrency: int = 2,
        retry_backoff_sec: float = 0.25,
        poll_interval_sec: float = 0.05,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if retry_backoff_sec < 0 or poll_interval_sec < 0:
            raise ValueError("timing values must be non-negative")
        self._store = store
        self._handlers = dict(handlers)
        self._max_concurrency = max_concurrency
        self._retry_backoff = retry_backoff_sec
        self._poll_interval = poll_interval_sec

    def run_until_idle(self) -> ExecutorReport:
        completed = failed = retried = 0
        pending: dict[Future[str | None], Job] = {}
        next_claim_at = 0.0

        with ThreadPoolExecutor(max_workers=self._max_concurrency) as pool:
            while True:
                while len(pending) < self._max_concurrency and time.monotonic() >= next_claim_at:
                    job = self._store.claim_job()
                    if job is None:
                        break
                    handler = self._handlers.get(job.job_type)
                    if handler is None:
                        self._store.fail_job(job.id, f"No handler for job type {job.job_type!r}")
                        failed += 1
                        continue
                    pending[pool.submit(handler, job)] = job

                if not pending:
                    remaining_delay = next_claim_at - time.monotonic()
                    if remaining_delay > 0:
                        time.sleep(min(remaining_delay, max(self._poll_interval, 0.001)))
                        continue
                    break

                done, _ = wait(
                    pending,
                    timeout=max(self._poll_interval, 0.001),
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    for job in pending.values():
                        self._store.heartbeat(job.id)
                    continue

                for future in done:
                    job = pending.pop(future)
                    try:
                        result_ref = future.result()
                    except Exception as exc:
                        self._store.fail_job(job.id, f"{type(exc).__name__}: {exc}")
                        current = self._store.get_job(job.id)
                        if current is not None and current.status == "queued":
                            retried += 1
                            delay = self._retry_backoff * (2 ** max(current.attempt - 1, 0))
                            next_claim_at = max(next_claim_at, time.monotonic() + delay)
                        else:
                            failed += 1
                    else:
                        if self._store.complete_job(job.id, result_ref):
                            completed += 1

        return ExecutorReport(completed=completed, failed=failed, retried=retried)
