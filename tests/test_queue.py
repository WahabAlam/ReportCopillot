from __future__ import annotations

from fastapi import BackgroundTasks

import utils.queue as qmod


def test_enqueue_job_uses_background_when_rq_disabled(monkeypatch):
    monkeypatch.delenv("USE_RQ_QUEUE", raising=False)
    bg = BackgroundTasks()
    out = qmod.enqueue_job(
        background_tasks=bg,
        worker_callable=lambda **_: None,
        worker_path="main._execute_job",
        worker_kwargs={"job_id": "x"},
    )
    assert out.mode == "background"
    assert out.job_id is None


def test_enqueue_job_uses_rq_when_enabled(monkeypatch):
    monkeypatch.setenv("USE_RQ_QUEUE", "1")
    monkeypatch.setattr(qmod, "_enqueue_rq", lambda **_: "rq123")
    bg = BackgroundTasks()
    out = qmod.enqueue_job(
        background_tasks=bg,
        worker_callable=lambda **_: None,
        worker_path="main._execute_job",
        worker_kwargs={"job_id": "x"},
    )
    assert out.mode == "rq"
    assert out.job_id == "rq123"


def test_enqueue_job_falls_back_when_rq_fails(monkeypatch):
    monkeypatch.setenv("USE_RQ_QUEUE", "1")
    monkeypatch.setenv("RQ_FALLBACK_TO_BACKGROUND", "1")

    def boom(**_):
        raise RuntimeError("redis down")

    monkeypatch.setattr(qmod, "_enqueue_rq", boom)
    bg = BackgroundTasks()
    out = qmod.enqueue_job(
        background_tasks=bg,
        worker_callable=lambda **_: None,
        worker_path="main._execute_job",
        worker_kwargs={"job_id": "x"},
    )
    assert out.mode == "background"
