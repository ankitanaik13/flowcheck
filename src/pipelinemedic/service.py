"""Durable run records, isolated repairs, and explicit promotion/rollback."""

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone

from .agent import investigate, policy
from .config import ARTIFACTS
from .detection import checks, observe
from .pipeline import (
    REPAIRS,
    apply_repair,
    fingerprint,
    load_lab,
    make_lab,
    reference_output,
    save_lab,
    summarize,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def evaluate(lab, mode="offline"):
    started = time.perf_counter()
    alert, before = observe(lab)
    investigation = investigate(lab, alert, mode)
    proposed = investigation["diagnosis"]["repairs"]
    sandbox = lab.copy()
    verification = {"passed": False, "checks": [], "error": None, "exact_output_match": None}
    patches = []
    if proposed:
        try:
            # Evidence authorization is independent of the LLM's proposed actions.
            allowed = policy({"evidence": investigation["evidence"], "alert": alert}).repairs
            if not set(proposed).issubset(allowed):
                raise ValueError("Proposed action is unsupported by the collected evidence")
            for action in proposed:
                apply_repair(sandbox, action)
                patches.append({"action": action, **REPAIRS[action]})
            after = sandbox.execute()
            verification["checks"] = checks(sandbox, after)
            # Trusted evaluator is not an agent tool; catches plausible but wrong repairs.
            expected = reference_output(lab)
            exact = fingerprint(after) == fingerprint(expected)
            verification["exact_output_match"] = exact
            verification["passed"] = all(c["passed"] for c in verification["checks"]) and exact
        except Exception as exc:
            after = before
            verification["error"] = str(exc)[:1000]
    else:
        after = before
    status = (
        "needs_review"
        if verification["passed"]
        else (
            "repair_rejected"
            if proposed
            else "investigation_failed"
            if investigation["diagnosis"]["roots"] == ["unknown"]
            else "manual_review"
            if alert["failed_checks"]
            else "no_action"
        )
    )
    return {
        "status": status,
        "alert": alert,
        "investigation": investigation,
        "patches": patches,
        "verification": verification,
        "before": summarize(before),
        "after": summarize(after),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }, sandbox


class RunStore:
    def __init__(self, root=ARTIFACTS):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = root / "state.sqlite"
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline-run")
        self.slots = threading.BoundedSemaphore(6)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created TEXT, status TEXT, request TEXT, result TEXT, idempotency_key TEXT UNIQUE, request_hash TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run_id TEXT, timestamp TEXT, action TEXT, detail TEXT)"
            )
            db.execute("UPDATE runs SET status='interrupted' WHERE status IN ('queued','running')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, db, run_id, action, detail):
        db.execute(
            "INSERT INTO events(run_id,timestamp,action,detail) VALUES(?,?,?,?)",
            (run_id, now(), action, detail),
        )

    def create(self, request, key=None):
        encoded = json.dumps(request, sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if key:
                existing = db.execute(
                    "SELECT id,request_hash FROM runs WHERE idempotency_key=?", (key,)
                ).fetchone()
                if existing:
                    if existing["request_hash"] != digest:
                        raise ValueError("Idempotency key already used with a different request")
                    return existing["id"]
            if not self.slots.acquire(blocking=False):
                raise RuntimeError("Run queue is full; wait for an active run to finish")
            run_id = str(uuid.uuid4())
            try:
                db.execute(
                    "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                    (run_id, now(), "queued", encoded, None, key, digest),
                )
                self.event(db, run_id, "created", "Isolated fault-laboratory run queued")
            except Exception:
                self.slots.release()
                raise
        self.pool.submit(self._work, run_id, request)
        return run_id

    def _work(self, run_id, request):
        try:
            with self.connect() as db:
                db.execute("UPDATE runs SET status='running' WHERE id=?", (run_id,))
            lab = make_lab(request["date"], request["scenario"], request["seed"], request["severity"])
            directory = self.root / "runs" / run_id
            save_lab(lab, directory / "original")
            result, sandbox = evaluate(lab, request["mode"])
            if result["verification"]["passed"]:
                save_lab(sandbox, directory / "verified")
                result["verified_digest"] = fingerprint(sandbox.execute())
            with self.connect() as db:
                db.execute(
                    "UPDATE runs SET status=?,result=? WHERE id=?",
                    (result["status"], json.dumps(result), run_id),
                )
                self.event(db, run_id, "investigated", result["status"])
        except Exception as exc:
            with self.connect() as db:
                db.execute(
                    "UPDATE runs SET status='failed',result=? WHERE id=?",
                    (json.dumps({"error": str(exc)[:1000]}), run_id),
                )
                self.event(db, run_id, "failed", type(exc).__name__)
        finally:
            self.slots.release()

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            events = [
                dict(r)
                for r in db.execute(
                    "SELECT timestamp,action,detail FROM events WHERE run_id=? ORDER BY id", (run_id,)
                )
            ]
        return {
            "id": row["id"],
            "created": row["created"],
            "status": row["status"],
            "request": json.loads(row["request"]),
            "result": json.loads(row["result"]) if row["result"] else None,
            "events": events,
        }

    def list(self):
        with self.connect() as db:
            return [
                {**dict(r), "request": json.loads(r["request"])}
                for r in db.execute(
                    "SELECT id,created,status,request FROM runs ORDER BY created DESC LIMIT 100"
                )
            ]

    def transition(self, run_id, action):
        if action not in {"approve", "rollback"}:
            raise ValueError("Unknown transition")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,result FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            expected, target = (
                ("needs_review", "approved") if action == "approve" else ("approved", "rolled_back")
            )
            if row["status"] == target:
                return self.get(run_id)
            if row["status"] != expected:
                raise ValueError(f"Cannot {action} a run in state {row['status']}")
            if action == "approve":
                result = json.loads(row["result"])
                verified = load_lab(self.root / "runs" / run_id / "verified")
                if (
                    not result["verification"]["passed"]
                    or fingerprint(verified.execute()) != result["verified_digest"]
                ):
                    raise ValueError("Verified artifact has changed; approval blocked")
            db.execute("UPDATE runs SET status=? WHERE id=?", (target, run_id))
            self.event(
                db,
                run_id,
                action,
                "Demo workspace pointer changed to "
                + ("verified snapshot" if action == "approve" else "original snapshot"),
            )
        return self.get(run_id)

    def active_output(self, run_id):
        run = self.get(run_id)
        name = "verified" if run["status"] == "approved" else "original"
        lab = load_lab(self.root / "runs" / run_id / name)
        return lab.execute()

    def close(self):
        self.pool.shutdown(wait=True)
