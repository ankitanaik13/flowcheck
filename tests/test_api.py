import time

import pytest
from fastapi.testclient import TestClient

from pipelinemedic.api import create_app
from pipelinemedic.service import RunStore


@pytest.fixture
def client(tmp_path):
    store = RunStore(tmp_path)
    with TestClient(create_app(store)) as c:
        yield c, store
    store.close()


def wait(c, run_id):
    for _ in range(200):
        run = c.get("/api/runs/" + run_id).json()
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(0.05)
    raise AssertionError("Run did not finish")


def test_health_overview_and_security_headers(client):
    c, _ = client
    r = c.get("/api/health")
    assert r.status_code == 200 and r.json()["dataset_ready"]
    assert r.headers["x-content-type-options"] == "nosniff"
    overview = c.get("/api/overview").json()
    assert overview["dataset"]["rows"] == 541909
    assert len(overview["scenarios"]) == 10


def test_create_approve_rollback_and_export(client):
    c, store = client
    r = c.post("/api/runs", json={"scenario": "compound"})
    assert r.status_code == 202
    run_id = r.json()["id"]
    run = wait(c, run_id)
    assert run["status"] == "needs_review"
    original = store.active_output(run_id)
    assert c.post(f"/api/runs/{run_id}/approve").json()["status"] == "approved"
    approved = store.active_output(run_id)
    assert len(approved) < len(original)
    assert c.post(f"/api/runs/{run_id}/approve").status_code == 200
    assert c.post(f"/api/runs/{run_id}/rollback").json()["status"] == "rolled_back"
    assert len(store.active_output(run_id)) == len(original)
    assert c.get(f"/api/runs/{run_id}/export").status_code == 200
    assert c.post(f"/api/runs/{run_id}/approve").status_code == 409


def test_idempotency_and_conflict(client):
    c, _ = client
    headers = {"Idempotency-Key": "repeat-1"}
    a = c.post("/api/runs", json={"scenario": "clean"}, headers=headers)
    b = c.post("/api/runs", json={"scenario": "clean"}, headers=headers)
    assert a.json()["id"] == b.json()["id"]
    assert c.post("/api/runs", json={"scenario": "compound"}, headers=headers).status_code == 409
    wait(c, a.json()["id"])


@pytest.mark.parametrize(
    "payload",
    [
        {"scenario": "evil"},
        {"mode": "remote"},
        {"date": "1900-01-01"},
        {"date": "2011-08-15"},
        {"seed": -1},
        {"severity": 2},
        {"severity": float("inf")},
        {"unexpected": "input"},
    ],
)
def test_invalid_requests(client, payload):
    c, _ = client
    if payload.get("severity") == float("inf"):
        r = c.post("/api/runs", content='{"severity":1e999}', headers={"Content-Type": "application/json"})
    else:
        r = c.post("/api/runs", json=payload)
    assert r.status_code == 422


def test_cross_origin_write_is_rejected(client):
    c, _ = client
    assert c.post("/api/runs", json={}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_unknown_run_and_path_rejected(client):
    c, _ = client
    assert c.get("/api/runs/not-a-uuid").status_code == 422
    assert c.get("/api/runs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_cannot_approve_clean_run(client):
    c, _ = client
    rid = c.post("/api/runs", json={"scenario": "clean"}).json()["id"]
    wait(c, rid)
    assert c.post(f"/api/runs/{rid}/approve").status_code == 409


def test_verified_artifact_tampering_blocks_approval(client):
    c, store = client
    rid = c.post("/api/runs", json={"scenario": "join_fanout"}).json()["id"]
    wait(c, rid)
    path = store.root / "runs" / rid / "verified" / "transform.sql"
    path.write_text(path.read_text() + "\nLIMIT 1")
    assert c.post(f"/api/runs/{rid}/approve").status_code == 409


def test_optional_api_auth(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("PIPELINEMEDIC_TOKEN", "testing-secret")
    assert c.get("/api/health").status_code == 401
    assert c.get("/api/health", headers={"Authorization": "Bearer testing-secret"}).status_code == 200


def test_queue_limit_returns_429(client):
    c, store = client
    for _ in range(6):
        assert store.slots.acquire(blocking=False)
    try:
        assert c.post("/api/runs", json={}).status_code == 429
    finally:
        for _ in range(6):
            store.slots.release()


def test_restart_marks_unfinished_runs_interrupted(tmp_path):
    import json
    import uuid

    store = RunStore(tmp_path)
    rid = str(uuid.uuid4())
    with store.connect() as db:
        db.execute(
            "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
            (rid, "2026-01-01", "running", json.dumps({}), None, None, "hash"),
        )
    store.close()
    restarted = RunStore(tmp_path)
    try:
        assert restarted.get(rid)["status"] == "interrupted"
    finally:
        restarted.close()


def test_runs_are_isolated_under_concurrent_execution(client):
    c, store = client
    a = c.post("/api/runs", json={"scenario": "join_fanout", "seed": 41}).json()["id"]
    b = c.post("/api/runs", json={"scenario": "unit_scale", "seed": 81}).json()["id"]
    assert wait(c, a)["status"] == "needs_review"
    assert wait(c, b)["status"] == "needs_review"
    c.post(f"/api/runs/{a}/approve")
    assert c.get(f"/api/runs/{b}").json()["status"] == "needs_review"
    assert len(list((store.root / "runs").iterdir())) == 2


def test_request_body_limit_and_unknown_action(client):
    c, _ = client
    assert c.post("/api/runs", content="x" * 9000).status_code == 413
    assert c.post("/api/runs/00000000-0000-0000-0000-000000000000/delete").status_code == 409
