from __future__ import annotations

import json
import time
import threading
from pathlib import Path

from fastapi.testclient import TestClient

import main
from utils.jobs import job_dir, write_job_debug, write_job_text, read_job_text
from utils.state import new_state, write_state, read_state


def test_run_endpoint_completes_job_with_mock_llm(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    client = TestClient(main.app)

    payload = {
        "template": "study_guide",
        "manual_text": "Newton's first law says an object at rest stays at rest unless acted on by a net force.",
        "goal": "Generate a concise study guide.",
        "extra_instructions": "Keep practice questions simple.",
        "include_review": "0",
    }
    resp = client.post("/run", data=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["stage"] == "queued"
    assert body["progress_pct"] == 0
    assert body["queue_mode"] in ("background", "rq")
    assert "job_id" in body

    job_id = body["job_id"]
    last_status = None
    for _ in range(40):
        s = client.get(f"/status/{job_id}")
        assert s.status_code == 200
        last_status = s.json()["status"]
        if last_status in ("done", "failed"):
            break
        time.sleep(0.05)

    assert last_status == "done"
    done_state = client.get(f"/status/{job_id}").json()
    assert done_state["stage"] == "done"
    assert done_state["progress_pct"] == 100
    assert Path("outputs", f"{job_id}.pdf").exists()
    assert Path("outputs", job_id, "debug.json").exists()


def test_run_endpoint_marks_failed_when_llm_config_missing(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    client = TestClient(main.app)

    payload = {
        "template": "study_guide",
        "manual_text": "Basic notes text for testing failure behavior.",
        "goal": "Generate a concise study guide.",
        "extra_instructions": "Keep concise.",
        "include_review": "0",
    }
    resp = client.post("/run", data=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    final_status = None
    final_error = ""
    for _ in range(40):
        s = client.get(f"/status/{job_id}")
        assert s.status_code == 200
        data = s.json()
        final_status = data["status"]
        final_error = data.get("error", "") or ""
        if final_status in ("done", "failed"):
            break
        time.sleep(0.05)

    assert final_status == "failed"
    final = client.get(f"/status/{job_id}").json()
    assert final["stage"] == "failed"
    assert final["progress_pct"] == 100
    assert "Missing LLM_API_KEY" in final_error


def test_status_includes_timings_from_debug_file():
    client = TestClient(main.app)
    job_id = "Abcd1234Efgh5678"
    jdir = job_dir(job_id)
    st = new_state(job_id)
    st.status = "running"
    st.stage = "writer"
    st.progress_pct = 60
    write_state(jdir, st)
    (jdir / "debug.json").write_text(
        json.dumps(
            {
                "agent_status": {"timings_ms": {"research": 10, "writer": 20}},
                "pipeline_duration_ms": 44,
                "quality": {"ok": False, "issues": [{"detail": "Section 'Discussion' is too short."}]},
            }
        ),
        encoding="utf-8",
    )

    resp = client.get(f"/status/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["timings_ms"]["research"] == 10
    assert body["pipeline_duration_ms"] == 44
    assert body["quality_ok"] is False
    assert body["quality_issue_count"] == 1


def test_cancel_endpoint_sets_cancellation_requested():
    client = TestClient(main.app)
    job_id = "Zyxw9876Vuts5432"
    jdir = job_dir(job_id)
    st = new_state(job_id)
    st.status = "running"
    st.stage = "writer"
    st.progress_pct = 55
    write_state(jdir, st)

    resp = client.post(f"/cancel/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "Cancellation requested."

    after = client.get(f"/status/{job_id}").json()
    assert after["cancellation_requested"] is True
    assert after["stage"] == "cancel_requested"


def test_worker_transitions_to_canceled_when_cancel_requested(monkeypatch):
    job_id = "Cancel1234Job5678"
    jdir = job_dir(job_id)
    st = new_state(job_id)
    write_state(jdir, st)

    def fake_run_pipeline(
        *,
        job_id: str,
        manual_text: str,
        goal: str,
        csv_path: str | None,
        extra_instructions: str,
        template_cfg: dict | None,
        include_review: bool,
        progress_cb=None,
        should_cancel=None,
    ):
        if progress_cb:
            progress_cb("research", {"progress_pct": 20})
        for _ in range(80):
            if should_cancel and should_cancel():
                raise main.CancelledError("Job canceled by user.")
            time.sleep(0.01)
        return {
            "theory": "",
            "data_summary": {},
            "report": "",
            "review": "",
            "figures": "",
            "report_sections": {},
            "agent_status": {"timings_ms": {}},
        }

    monkeypatch.setattr(main, "run_pipeline", fake_run_pipeline)

    worker = threading.Thread(
        target=main._execute_job,
        kwargs={
            "job_id": job_id,
            "manual_text": "m",
            "goal": "g",
            "csv_path": None,
            "extra_instructions": "",
            "template": "study_guide",
            "template_cfg": {"include_plots": False, "include_review": False},
            "include_review_bool": False,
            "csv_info": {"preview_head": []},
            "meta": {"title": "x", "template": "Study Guide", "name": "", "course": "", "group": "", "date": ""},
        },
        daemon=True,
    )
    worker.start()

    time.sleep(0.1)
    main.cancel_job(job_id)
    worker.join(timeout=3)

    final = read_state(jdir)
    assert final is not None
    assert final.status == "canceled"
    assert final.stage == "canceled"
    assert final.progress_pct == 100


def test_template_configs_exposes_form_schema():
    client = TestClient(main.app)
    resp = client.get("/template-configs")
    assert resp.status_code == 200
    body = resp.json()
    assert "templates" in body
    assert "form_schema" in body["templates"]["study_guide"]
    assert "runtime" in body
    assert "run_rate_limit_enabled" in body["runtime"]
    assert "use_rq_queue" in body["runtime"]


def test_run_rejects_csv_for_study_guide():
    client = TestClient(main.app)
    payload = {
        "template": "study_guide",
        "manual_text": "notes",
        "goal": "study",
        "extra_instructions": "",
    }
    files = {"data_csv": ("x.csv", b"a,b\n1,2\n", "text/csv")}
    resp = client.post("/run", data=payload, files=files)
    assert resp.status_code == 400
    assert "does not accept CSV uploads" in resp.json()["detail"]


def test_run_rejects_review_for_template_without_review():
    client = TestClient(main.app)
    payload = {
        "template": "data_insights",
        "manual_text": "context notes",
        "goal": "Summarize trends clearly.",
        "extra_instructions": "",
        "include_review": "1",
    }
    files = {"data_csv": ("x.csv", b"a,b\n1,2\n", "text/csv")}
    resp = client.post("/run", data=payload, files=files)
    assert resp.status_code == 400
    assert "does not support reviewer feedback" in resp.json()["detail"]


def test_cancel_and_cleanup_require_admin_key_when_configured(monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(main, "ADMIN_API_KEY", "secret")

    job_id = "Admin1234Check567"
    st = new_state(job_id)
    write_state(job_dir(job_id), st)

    no_auth_cancel = client.post(f"/cancel/{job_id}")
    assert no_auth_cancel.status_code == 401
    yes_auth_cancel = client.post(f"/cancel/{job_id}", headers={"X-Admin-Key": "secret"})
    assert yes_auth_cancel.status_code == 200

    no_auth_cleanup = client.post("/cleanup")
    assert no_auth_cleanup.status_code == 401
    yes_auth_cleanup = client.post("/cleanup", headers={"X-Admin-Key": "secret"})
    assert yes_auth_cleanup.status_code == 200


def test_run_rate_limit(monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(main, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(main, "RATE_LIMIT_MAX_REQUESTS", 1)
    monkeypatch.setattr(main, "RATE_LIMIT_WINDOW_SECONDS", 60)
    main.RATE_LIMIT_BUCKETS.clear()

    payload = {
        "template": "study_guide",
        "manual_text": "notes",
        "goal": "study",
        "extra_instructions": "",
        "include_review": "0",
    }
    r1 = client.post("/run", data=payload)
    assert r1.status_code == 200

    r2 = client.post("/run", data=payload)
    assert r2.status_code == 429


def test_retry_endpoint_requeues_failed_job(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    client = TestClient(main.app)

    old_job = "RetryOld12345678"
    old_dir = job_dir(old_job)
    st = new_state(old_job)
    st.status = "failed"
    st.stage = "failed"
    st.progress_pct = 100
    write_state(old_dir, st)
    (old_dir / "debug.json").write_text(
        json.dumps(
            {
                "request_payload": {
                    "template": "study_guide",
                    "manual_text": "retry notes",
                    "goal": "retry goal",
                    "csv_path": None,
                    "extra_instructions": "",
                    "include_review_bool": False,
                    "csv_info": {"rows": 0, "columns": [], "numeric_columns": [], "preview_head": []},
                    "meta": {"title": "Study Guide", "template": "Study Guide", "name": "", "course": "", "group": "", "date": ""},
                }
            }
        ),
        encoding="utf-8",
    )

    resp = client.post(f"/retry/{old_job}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["retry_of"] == old_job
    assert body["job_id"] != old_job

    new_state_payload = client.get(f"/status/{body['job_id']}").json()
    assert new_state_payload["status"] in ("queued", "running", "done")


def test_retry_rejects_non_failed_jobs():
    client = TestClient(main.app)
    job_id = "RetryNotAllowed01"
    st = new_state(job_id)
    st.status = "done"
    write_state(job_dir(job_id), st)
    resp = client.post(f"/retry/{job_id}")
    assert resp.status_code == 400


def test_recent_jobs_returns_sorted_items():
    client = TestClient(main.app)

    older = "RecentOld12345678"
    newer = "RecentNew12345678"

    st_old = new_state(older)
    st_old.status = "done"
    st_old.updated_at = "2026-01-01T00:00:00Z"
    write_state(job_dir(older), st_old)

    st_new = new_state(newer)
    st_new.status = "running"
    st_new.updated_at = "2026-01-02T00:00:00Z"
    st_new.stage = "writer"
    st_new.progress_pct = 55
    write_state(job_dir(newer), st_new)

    resp = client.get("/recent-jobs?limit=2&show_all=true")
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert len(jobs) >= 2
    # Newer should appear before older due to updated_at sort desc.
    ids = [j["job_id"] for j in jobs[:2]]
    assert ids[0] == newer
    assert ids[1] == older
    assert "job_url" in jobs[0]
    assert "download_url" in jobs[0]


def test_get_and_save_draft():
    client = TestClient(main.app)
    job_id = "Draft1234Abcd5678"
    jdir = job_dir(job_id)
    st = new_state(job_id)
    st.status = "done"
    write_state(jdir, st)
    write_job_text(
        job_id,
        "report.txt",
        "Objective:\nOld objective\n\nConclusion:\nOld conclusion",
    )
    write_job_debug(
        job_id,
        {
            "template": "lab_report",
            "template_display_name": "Lab / Technical Report",
            "request_payload": {
                "template": "lab_report",
                "manual_text": "m",
                "goal": "g",
                "csv_path": None,
                "extra_instructions": "",
                "include_review_bool": False,
                "csv_info": {"preview_head": []},
                "meta": {"title": "t", "template": "Lab / Technical Report", "name": "", "course": "", "group": "", "date": ""},
            },
            "meta": {"title": "t", "template": "Lab / Technical Report", "name": "", "course": "", "group": "", "date": ""},
        },
    )

    g = client.get(f"/draft/{job_id}")
    assert g.status_code == 200
    assert "Objective" in g.json()["headers"]

    s = client.post(f"/draft/{job_id}", json={"report_text": "Objective:\nNew\n\nConclusion:\nUpdated"})
    assert s.status_code == 200
    assert read_job_text(job_id, "report.txt").startswith("Objective:\nNew")


def test_regenerate_section_updates_report(monkeypatch):
    client = TestClient(main.app)
    job_id = "Regen1234Abcd5678"
    jdir = job_dir(job_id)
    st = new_state(job_id)
    st.status = "done"
    write_state(jdir, st)
    write_job_text(
        job_id,
        "report.txt",
        "Objective:\nOld objective\n\nIntroduction:\nIntro text\n\nTheoretical Background:\nT\n\nApparatus & Procedure:\nA\n\nResults:\nR\n\nDiscussion:\nD\n\nConclusion:\nC\n\nReferences:\nRef",
    )
    write_job_text(job_id, "theory.txt", "theory")
    write_job_debug(
        job_id,
        {
            "template": "lab_report",
            "template_display_name": "Lab / Technical Report",
            "agent_status": {"data": {"payload": {"data_summary": {}}}},
            "request_payload": {
                "template": "lab_report",
                "manual_text": "m",
                "goal": "g",
                "csv_path": None,
                "extra_instructions": "",
                "include_review_bool": False,
                "csv_info": {"preview_head": []},
                "meta": {"title": "t", "template": "Lab / Technical Report", "name": "", "course": "", "group": "", "date": ""},
            },
            "meta": {"title": "t", "template": "Lab / Technical Report", "name": "", "course": "", "group": "", "date": ""},
        },
    )

    monkeypatch.setattr(main, "chat", lambda system, user: "Regenerated objective text.")
    r = client.post(
        f"/regenerate-section/{job_id}",
        json={"section": "Objective", "instructions": "Make it concise."},
    )
    assert r.status_code == 200
    updated = read_job_text(job_id, "report.txt")
    assert "Objective:\nRegenerated objective text." in updated

    rb = client.post(f"/rebuild/{job_id}")
    assert rb.status_code == 200


def test_get_draft_falls_back_when_template_missing():
    client = TestClient(main.app)
    job_id = "DraftFallback1234"
    st = new_state(job_id)
    st.status = "done"
    write_state(job_dir(job_id), st)
    write_job_text(job_id, "report.txt", "Objective:\nLegacy objective\n\nConclusion:\nLegacy conclusion")
    write_job_debug(job_id, {"template": "", "template_display_name": ""})

    resp = client.get(f"/draft/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_text"].startswith("Objective:")
    assert "headers" in body


def test_quality_fix_endpoint_updates_quality(monkeypatch):
    client = TestClient(main.app)
    job_id = "QualityFix1234Abcd"
    st = new_state(job_id)
    st.status = "done"
    write_state(job_dir(job_id), st)
    write_job_text(
        job_id,
        "report.txt",
        "Objective:\nshort\n\nIntroduction:\nintro\n\nTheoretical Background:\nback\n\nApparatus & Procedure:\nproc\n\nResults:\nshort\n\nDiscussion:\nshort\n\nConclusion:\nshort\n\nReferences:\nref",
    )
    write_job_text(job_id, "theory.txt", "theory")
    write_job_debug(
        job_id,
        {
            "template": "lab_report",
            "template_display_name": "Lab / Technical Report",
            "agent_status": {"data": {"payload": {"data_summary": {}}}},
            "request_payload": {
                "template": "lab_report",
                "manual_text": "m",
                "goal": "g",
                "csv_path": None,
                "extra_instructions": "",
                "include_review_bool": False,
                "csv_info": {"preview_head": []},
                "meta": {"title": "t", "template": "Lab / Technical Report", "name": "", "course": "", "group": "", "date": ""},
            },
            "meta": {"title": "t", "template": "Lab / Technical Report", "name": "", "course": "", "group": "", "date": ""},
        },
    )

    def fake_writer_run(*, job_id: str, ctx: dict):
        txt = (
            "Objective:\nA clear objective for the full dataset and method context.\n\n"
            "Introduction:\nThis lab is intended to evaluate temperature trends from a measured dataset.\n\n"
            "Theoretical Background:\nBackground with assumptions and model references.\n\n"
            "Apparatus & Procedure:\nProcedure with intervals and assumptions.\n\n"
            "Results:\nThe dataset summary includes mean, min, and max values and uses full dataset statistics for interpretation.\n\n"
            "Discussion:\nThis section discusses assumption choices, limitation sources, and possible error mechanisms in measurement.\n\n"
            "Conclusion:\nConclusion summarizing main trend and implications from dataset.\n\n"
            "References:\nManual and notes."
        )
        return type("R", (), {"ok": True, "payload": {"report_text": txt, "sections": {}}, "error": None})()

    monkeypatch.setattr(main, "writer_run", fake_writer_run)
    r = client.post(f"/quality-fix/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "quality_issue_count" in body
