"""SQLite audit trail and process-safe task/budget reservations."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, state TEXT, stage TEXT, detail TEXT,
                    updated REAL, worker_model TEXT, commit_sha TEXT, pr_url TEXT);
                CREATE TABLE IF NOT EXISTS calls (
                    id INTEGER PRIMARY KEY, task_id TEXT, stage TEXT, provider TEXT,
                    model TEXT, started REAL, finished REAL, status TEXT,
                    cost REAL, detail TEXT);
                CREATE TABLE IF NOT EXISTS providers (
                    key TEXT PRIMARY KEY, disabled INTEGER DEFAULT 0,
                    cooldown REAL DEFAULT 0, reason TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id TEXT, created REAL, kind TEXT, detail TEXT);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def task(self, task_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    def create(self, task_id):
        with self.connect() as db:
            db.execute(
                "INSERT INTO tasks(id,state,stage,updated) VALUES(?,?,?,?)",
                (task_id, "queued", "requirements", time.time()),
            )

    def update(self, task_id, **fields):
        if not set(fields) <= {"state", "stage", "detail", "worker_model", "commit_sha", "pr_url"}:
            raise ValueError("Invalid state field")
        fields["updated"] = time.time()
        with self.connect() as db:
            db.execute(
                "UPDATE tasks SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
                (*fields.values(), task_id),
            )

    def event(self, task_id, kind, detail):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(task_id,created,kind,detail) VALUES(?,?,?,?)",
                (task_id, time.time(), kind, json.dumps(detail, ensure_ascii=False)),
            )

    def provider(self, key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM providers WHERE key=?", (key,)).fetchone()
            return dict(row) if row else {"disabled": False, "cooldown": 0}

    def restrict(self, key, disabled=False, cooldown=0, reason=""):
        with self.connect() as db:
            db.execute(
                "INSERT INTO providers(key,disabled,cooldown,reason) VALUES(?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET disabled=excluded.disabled, "
                "cooldown=excluded.cooldown,reason=excluded.reason",
                (key, disabled, cooldown, reason),
            )

    def reserve_call(self, task_id, stage, provider, model, policy):
        now = time.time()
        day = int(now // 86400) * 86400
        with self.transaction() as db:
            for where, args, maximum, budget in (
                (
                    "task_id=?",
                    (task_id,),
                    policy["max_calls_per_task"],
                    policy["max_reported_usd_per_task"],
                ),
                (
                    "started>=?",
                    (day,),
                    policy["max_calls_per_day"],
                    policy["max_reported_usd_per_day"],
                ),
            ):
                count, cost = db.execute(
                    f"SELECT COUNT(*),COALESCE(SUM(cost),0) FROM calls WHERE {where}", args
                ).fetchone()
                if count >= maximum or cost >= budget:
                    raise RuntimeError("Factory call/cost circuit breaker reached")
            return db.execute(
                "INSERT INTO calls(task_id,stage,provider,model,started,status) "
                "VALUES(?,?,?,?,?,?)",
                (task_id, stage, provider, model, now, "running"),
            ).lastrowid

    def finish_call(self, call_id, status, cost, detail):
        with self.connect() as db:
            db.execute(
                "UPDATE calls SET finished=?,status=?,cost=?,detail=? WHERE id=?",
                (time.time(), status, cost, json.dumps(detail, ensure_ascii=False), call_id),
            )

    def calls(self, task_id):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM calls WHERE task_id=? ORDER BY id", (task_id,))
            ]
