"""SQLite database for HF model test tracking.

Single-file local DB — no credentials needed. Path can be overridden via
HF_DASHBOARD_DB env var. Schema is created on first import.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator


def _default_db_path() -> str:
    """Default DB lives on local disk because the repo lives on a CIFS mount,
    which doesn't support SQLite file locking. Override with HF_DASHBOARD_DB.
    """
    local_dir = os.path.expanduser("~/.hf_dashboard")
    os.makedirs(local_dir, exist_ok=True)
    return os.path.join(local_dir, "hf_dashboard.db")


DB_PATH = os.environ.get("HF_DASHBOARD_DB") or _default_db_path()

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS hf_model_tests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name          TEXT NOT NULL,
    hf_url              TEXT,
    backend             TEXT NOT NULL,
    gpu_name            TEXT NOT NULL DEFAULT '',
    release_version     TEXT NOT NULL DEFAULT '',
    test_status         TEXT NOT NULL DEFAULT 'pending',
    out_file_path       TEXT,
    ai_verdict          TEXT,
    ai_reason           TEXT,
    ai_full_analysis    TEXT,
    job_name            TEXT,
    build_number        TEXT,
    bug_id              TEXT,
    hf_release_date     TEXT,
    requires_s3_upload  INTEGER NOT NULL DEFAULT 0,
    s3_uploaded         INTEGER NOT NULL DEFAULT 0,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(model_name, backend, gpu_name, release_version)
);

CREATE INDEX IF NOT EXISTS idx_hf_model_tests_status
    ON hf_model_tests(test_status);
CREATE INDEX IF NOT EXISTS idx_hf_model_tests_backend
    ON hf_model_tests(backend);

CREATE TABLE IF NOT EXISTS hf_models (
    model_name          TEXT PRIMARY KEY,
    hf_url              TEXT,
    release_date        TEXT,
    source_collection   TEXT,
    architecture        TEXT,
    param_count         TEXT,
    requires_s3_upload  INTEGER NOT NULL DEFAULT 0,
    s3_uploaded         INTEGER NOT NULL DEFAULT 0,
    s3_path             TEXT,
    review_status       TEXT NOT NULL DEFAULT 'pending',
    notes               TEXT,
    ai_backend_suggestion TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_hf_models_review_status
    ON hf_models(review_status);

CREATE TABLE IF NOT EXISTS jenkins_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id        INTEGER,
    build_number    INTEGER,            -- populated once Jenkins assigns it
    job_name        TEXT NOT NULL,
    branch          TEXT,
    release_version TEXT,
    triggered_at    TEXT NOT NULL DEFAULT (datetime('now')),
    started_at      TEXT,
    finished_at     TEXT,
    duration_sec    INTEGER DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'queued',
                    -- queued / building / SUCCESS / FAILURE / ABORTED / UNSTABLE / ANALYZED / ERROR
    params_json     TEXT,
    log_path        TEXT,
    analyzed_at     TEXT,
    analyze_summary TEXT,
    notes           TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jenkins_runs_status
    ON jenkins_runs(status);
CREATE INDEX IF NOT EXISTS idx_jenkins_runs_build
    ON jenkins_runs(job_name, build_number);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Yield a thread-safe SQLite connection with row factory enabled."""
    with _LOCK:
        conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            conn.close()


def init_db() -> None:
    """Create tables if they don't exist + run any pending migrations."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_add_release_version(conn)


def _migrate_add_release_version(conn) -> None:
    """If a pre-release-tracking hf_model_tests exists, rebuild it with the
    `release_version` column and the new 4-column unique constraint.

    SQLite can't ALTER a UNIQUE constraint in place, so we recreate the table.
    The migration is a no-op if `release_version` already exists.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(hf_model_tests)").fetchall()}
    if "release_version" in cols:
        return  # already migrated

    conn.executescript(
        """
        BEGIN;
        CREATE TABLE hf_model_tests_new (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name          TEXT NOT NULL,
            hf_url              TEXT,
            backend             TEXT NOT NULL,
            gpu_name            TEXT NOT NULL DEFAULT '',
            release_version     TEXT NOT NULL DEFAULT '',
            test_status         TEXT NOT NULL DEFAULT 'pending',
            out_file_path       TEXT,
            ai_verdict          TEXT,
            ai_reason           TEXT,
            ai_full_analysis    TEXT,
            job_name            TEXT,
            build_number        TEXT,
            bug_id              TEXT,
            hf_release_date     TEXT,
            requires_s3_upload  INTEGER NOT NULL DEFAULT 0,
            s3_uploaded         INTEGER NOT NULL DEFAULT 0,
            notes               TEXT,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(model_name, backend, gpu_name, release_version)
        );
        INSERT INTO hf_model_tests_new (
            id, model_name, hf_url, backend, gpu_name,
            test_status, out_file_path, ai_verdict, ai_reason, ai_full_analysis,
            job_name, build_number, bug_id, hf_release_date,
            requires_s3_upload, s3_uploaded, notes, created_at, updated_at
        )
        SELECT
            id, model_name, hf_url, backend, gpu_name,
            test_status, out_file_path, ai_verdict, ai_reason, ai_full_analysis,
            job_name, build_number, bug_id, hf_release_date,
            requires_s3_upload, s3_uploaded, notes, created_at, updated_at
        FROM hf_model_tests;
        DROP TABLE hf_model_tests;
        ALTER TABLE hf_model_tests_new RENAME TO hf_model_tests;
        CREATE INDEX IF NOT EXISTS idx_hf_model_tests_status   ON hf_model_tests(test_status);
        CREATE INDEX IF NOT EXISTS idx_hf_model_tests_backend  ON hf_model_tests(backend);
        CREATE INDEX IF NOT EXISTS idx_hf_model_tests_release  ON hf_model_tests(release_version);
        COMMIT;
        """
    )


def upsert_test(
    model_name: str,
    backend: str,
    gpu_name: str = "",
    release_version: str = "",
    **fields: Any,
) -> int:
    """Insert or update a test row keyed by
    (model_name, backend, gpu_name, release_version). Returns the row id.

    Rows for different `release_version` values are kept independently so a
    release-N test run never overwrites release-N-1 results.
    """
    fields["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id FROM hf_model_tests "
            "WHERE model_name=? AND backend=? AND gpu_name=? AND release_version=?",
            (model_name, backend, gpu_name, release_version),
        )
        row = cur.fetchone()
        if row:
            row_id = row["id"]
            if fields:
                set_clause = ", ".join(f"{k}=?" for k in fields)
                values = list(fields.values()) + [row_id]
                conn.execute(f"UPDATE hf_model_tests SET {set_clause} WHERE id=?", values)
            return row_id
        cols = ["model_name", "backend", "gpu_name", "release_version"] + list(fields.keys())
        placeholders = ", ".join(["?"] * len(cols))
        values = [model_name, backend, gpu_name, release_version] + list(fields.values())
        cur = conn.execute(
            f"INSERT INTO hf_model_tests ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )
        return cur.lastrowid


def list_release_versions() -> list[str]:
    """Distinct release_version values in hf_model_tests, newest first by use."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT release_version, MAX(updated_at) AS u FROM hf_model_tests "
            "GROUP BY release_version ORDER BY u DESC"
        )
        return [r["release_version"] for r in cur.fetchall()]


def delete_tests_for_model(model_name: str, release_version: str | None = None) -> int:
    """Delete all rows for a (model_name [, release_version]) — returns rows deleted."""
    with get_conn() as conn:
        if release_version is None:
            cur = conn.execute(
                "DELETE FROM hf_model_tests WHERE model_name=?", (model_name,)
            )
        else:
            cur = conn.execute(
                "DELETE FROM hf_model_tests WHERE model_name=? AND release_version=?",
                (model_name, release_version),
            )
        return cur.rowcount


def delete_test_cell(
    model_name: str, backend: str, gpu_name: str = "", release_version: str = ""
) -> int:
    """Delete one cell in the matrix. Returns rows deleted (0 or 1)."""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM hf_model_tests "
            "WHERE model_name=? AND backend=? AND gpu_name=? AND release_version=?",
            (model_name, backend, gpu_name, release_version),
        )
        return cur.rowcount


# ── jenkins_runs ──────────────────────────────────────────────────────────

def insert_run(**fields: Any) -> int:
    """Create a new run row. Returns the row id."""
    fields["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    cols = list(fields.keys())
    placeholders = ", ".join(["?"] * len(cols))
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO jenkins_runs ({', '.join(cols)}) VALUES ({placeholders})",
            list(fields.values()),
        )
        return cur.lastrowid


def update_run(run_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [run_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE jenkins_runs SET {set_clause} WHERE id=?", values)


def get_run(run_id: int) -> dict | None:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM jenkins_runs WHERE id=?", (run_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_runs(limit: int = 200, status: str | None = None) -> list[dict]:
    """All runs ordered by most recent first."""
    with get_conn() as conn:
        if status:
            cur = conn.execute(
                "SELECT * FROM jenkins_runs WHERE status=? "
                "ORDER BY datetime(triggered_at) DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM jenkins_runs ORDER BY datetime(triggered_at) DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in cur.fetchall()]


def list_active_runs() -> list[dict]:
    """Runs the watcher should be polling — queued or still building."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM jenkins_runs WHERE status IN ('queued', 'building') "
            "ORDER BY datetime(triggered_at) ASC"
        )
        return [dict(r) for r in cur.fetchall()]


def delete_run(run_id: int) -> int:
    """Delete one row from jenkins_runs. Returns rows deleted (0 or 1)."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM jenkins_runs WHERE id=?", (run_id,))
        return cur.rowcount


def list_tests(backend: str | None = None) -> list[dict]:
    """Return all test rows, optionally filtered by backend."""
    with get_conn() as conn:
        if backend:
            cur = conn.execute(
                "SELECT * FROM hf_model_tests WHERE backend=? ORDER BY model_name",
                (backend,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM hf_model_tests ORDER BY model_name, backend"
            )
        return [dict(row) for row in cur.fetchall()]


def list_models() -> list[str]:
    """Return distinct model names ordered by most recent activity."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT model_name, MAX(updated_at) AS u FROM hf_model_tests "
            "GROUP BY model_name ORDER BY u DESC"
        )
        return [row["model_name"] for row in cur.fetchall()]


def get_test(test_id: int) -> dict | None:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM hf_model_tests WHERE id=?", (test_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def update_test_fields(test_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [test_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE hf_model_tests SET {set_clause} WHERE id=?", values)


# ── hf_models (Inbox) ─────────────────────────────────────────────────────

def upsert_hf_model(model_name: str, **fields: Any) -> None:
    """Insert or merge-update a row in hf_models keyed by model_name.

    For existing rows we update only the provided fields; pre-existing values
    (e.g. user-edited s3_path, notes) are preserved if not overwritten.
    """
    fields["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT model_name FROM hf_models WHERE model_name=?", (model_name,)
        )
        if cur.fetchone():
            set_clause = ", ".join(f"{k}=?" for k in fields)
            values = list(fields.values()) + [model_name]
            conn.execute(
                f"UPDATE hf_models SET {set_clause} WHERE model_name=?", values
            )
            return
        cols = ["model_name"] + list(fields.keys())
        placeholders = ", ".join(["?"] * len(cols))
        values = [model_name] + list(fields.values())
        conn.execute(
            f"INSERT INTO hf_models ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )


def list_hf_models(review_status: str | None = None) -> list[dict]:
    """Return rows from hf_models, optionally filtered by review_status."""
    with get_conn() as conn:
        if review_status:
            cur = conn.execute(
                "SELECT * FROM hf_models WHERE review_status=? "
                "ORDER BY datetime(created_at) DESC",
                (review_status,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM hf_models ORDER BY datetime(created_at) DESC"
            )
        return [dict(row) for row in cur.fetchall()]


def get_hf_model(model_name: str) -> dict | None:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM hf_models WHERE model_name=?", (model_name,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def delete_hf_model(model_name: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM hf_models WHERE model_name=?", (model_name,))


init_db()
