from __future__ import annotations

import threading
import time

from omnievolve.storage.db import Database
from omnievolve.storage.job_store import JobStore
from omnievolve.storage.local_executor import LocalTaskExecutor, PermanentJobError
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository


def test_executor_limits_concurrency_and_retries_failures(tmp_path):
    db = Database(tmp_path / "jobs.db")
    initialize_database(db)
    experiment = ExperimentRepository(db).create(
        task_id="sort", task_name="sort", config_snapshot={}
    )
    store = JobStore(db)
    job = store.create_job(
        experiment.id, "evaluate", {}, max_attempts=3, job_id="deterministic-job"
    )
    duplicate = store.create_job(
        experiment.id, "evaluate", {}, max_attempts=3, job_id="deterministic-job"
    )
    assert duplicate.id == job.id
    assert len(store.list_jobs(experiment_id=experiment.id)) == 1
    attempts = 0

    def handler(_job):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("transient")
        return "artifact"

    report = LocalTaskExecutor(
        store,
        {"evaluate": handler},
        max_concurrency=1,
        retry_backoff_sec=0,
        poll_interval_sec=0,
    ).run_until_idle()

    assert report.completed == 1
    assert report.failed == 0
    assert report.retried == 1
    assert attempts == 2
    assert store.get_job(job.id).status == "completed"


def test_executor_never_exceeds_concurrency_limit(tmp_path):
    db = Database(tmp_path / "concurrency.db")
    initialize_database(db)
    experiment = ExperimentRepository(db).create(
        task_id="matrix", task_name="matrix", config_snapshot={}
    )
    store = JobStore(db)
    for index in range(6):
        store.create_job(experiment.id, "work", {"index": index})

    lock = threading.Lock()
    active = peak = 0

    def handler(_job):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return None

    report = LocalTaskExecutor(store, {"work": handler}, max_concurrency=2).run_until_idle()
    assert report.completed == 6
    assert peak == 2


def test_permanent_errors_are_not_retried(tmp_path):
    db = Database(tmp_path / "permanent.db")
    initialize_database(db)
    experiment = ExperimentRepository(db).create(
        task_id="matrix", task_name="matrix", config_snapshot={}
    )
    store = JobStore(db)
    job = store.create_job(experiment.id, "work", {}, max_attempts=5)
    attempts = 0

    def handler(_job):
        nonlocal attempts
        attempts += 1
        raise PermanentJobError("invalid authentication")

    report = LocalTaskExecutor(
        store,
        {"work": handler},
        max_concurrency=1,
        retry_backoff_sec=0,
    ).run_until_idle()

    assert attempts == 1
    assert report.failed == 1
    assert report.retried == 0
    assert store.get_job(job.id).status == "failed"
