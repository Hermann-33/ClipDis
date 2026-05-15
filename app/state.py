from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import state_db_path
from app.secrets import redact


logger = logging.getLogger(__name__)

JOB_STATES = {
    "detected",
    "waiting_for_file_ready",
    "queued",
    "processing",
    "processed",
    "uploading",
    "uploaded",
    "archived",
    "failed",
    "skipped",
}
ACTIVE_STATES = {"detected", "waiting_for_file_ready", "queued", "processing", "processed", "uploading"}
COMPLETED_STATES = {"uploaded", "archived", "skipped"}
VALID_TRANSITIONS = {
    "detected": {"waiting_for_file_ready", "queued", "failed", "skipped"},
    "waiting_for_file_ready": {"queued", "detected", "failed", "skipped"},
    "queued": {"processing", "failed", "skipped"},
    "processing": {"processed", "queued", "failed"},
    "processed": {"uploading", "failed"},
    "uploading": {"uploaded", "processed", "failed"},
    "uploaded": {"archived", "failed"},
    "archived": set(),
    "failed": {"queued", "skipped"},
    "skipped": set(),
}


class InvalidTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class JobIdentity:
    fingerprint: str
    source_path: str
    original_filename: str
    original_size: int | None
    original_mtime: float | None


class StateStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or state_db_path()

    def initialize_database(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT UNIQUE NOT NULL,
                    source_path TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    original_size INTEGER,
                    original_mtime REAL,
                    status TEXT NOT NULL,
                    previous_status TEXT,
                    compressed_path TEXT,
                    compressed_size INTEGER,
                    discord_message_id TEXT,
                    discord_response_code INTEGER,
                    archive_path TEXT,
                    cleanup_status TEXT,
                    cleanup_error TEXT,
                    error_category TEXT,
                    error_message TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    detected_at TEXT,
                    processing_started_at TEXT,
                    uploaded_at TEXT,
                    archived_at TEXT,
                    skipped_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    event_type TEXT NOT NULL,
                    message TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
                CREATE INDEX IF NOT EXISTS idx_events_job_id ON events(job_id);
                CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
                """
            )
            _ensure_column(conn, "jobs", "archive_path", "TEXT")
            _ensure_column(conn, "jobs", "cleanup_status", "TEXT")
            _ensure_column(conn, "jobs", "cleanup_error", "TEXT")

    def create_or_get_job(self, source_path: str | Path) -> dict[str, Any]:
        self.initialize_database()
        identity = build_job_identity(source_path)
        now = utc_now()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE fingerprint = ?", (identity.fingerprint,)).fetchone()
            if row:
                return row_to_dict(row)
            cursor = conn.execute(
                """
                INSERT INTO jobs (
                    fingerprint, source_path, original_filename, original_size, original_mtime,
                    status, created_at, updated_at, detected_at
                ) VALUES (?, ?, ?, ?, ?, 'detected', ?, ?, ?)
                """,
                (
                    identity.fingerprint,
                    identity.source_path,
                    identity.original_filename,
                    identity.original_size,
                    identity.original_mtime,
                    now,
                    now,
                    now,
                ),
            )
            job_id = int(cursor.lastrowid)
            self.add_event(job_id, "job_created", "Job detected.", {"source_path": identity.source_path}, conn=conn)
            return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        self.initialize_database()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return row_to_dict(row) if row else None

    def get_job_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        self.initialize_database()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE fingerprint = ?", (fingerprint,)).fetchone()
            return row_to_dict(row) if row else None

    def get_latest_job_by_source_path(self, source_path: str | Path) -> dict[str, Any] | None:
        self.initialize_database()
        normalized = str(Path(source_path).expanduser().resolve(strict=False)).lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE lower(source_path) = ? ORDER BY created_at DESC LIMIT 1",
                (normalized,),
            ).fetchone()
            return row_to_dict(row) if row else None

    def list_jobs(self, status: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        self.initialize_database()
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        with self._connect() as conn:
            if status:
                _ensure_known_status(status)
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            return [row_to_dict(row) for row in rows]

    def list_recent_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_jobs(limit=limit)

    def list_failed_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_jobs(status="failed", limit=limit)

    def count_by_status(self) -> dict[str, int]:
        self.initialize_database()
        counts = {state: 0 for state in JOB_STATES}
        with self._connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status").fetchall()
        for row in rows:
            counts[row["status"]] = int(row["count"])
        return counts

    def get_queue_summary(self) -> dict[str, Any]:
        counts = self.count_by_status()
        queued_count = sum(counts.get(state, 0) for state in ("detected", "waiting_for_file_ready", "queued"))
        processing = self._first_job_with_statuses(("processing", "uploading"))
        last_uploaded = self._latest_job_with_statuses(("uploaded", "archived"))
        last_failed = self._latest_job_with_statuses(("failed",))
        return {
            "counts": counts,
            "queue_count": queued_count,
            "failed_count": counts.get("failed", 0),
            "processed_count": counts.get("processed", 0),
            "uploaded_count": counts.get("uploaded", 0),
            "archived_count": counts.get("archived", 0),
            "current_job": processing,
            "last_uploaded": last_uploaded,
            "last_failed": last_failed,
        }

    def transition_job(
        self,
        job_id: int,
        new_status: str,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize_database()
        _ensure_known_status(new_status)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise KeyError(f"Job {job_id} does not exist.")
            current = row["status"]
            if new_status not in VALID_TRANSITIONS[current]:
                error = f"Invalid job transition: {current} -> {new_status}"
                logger.error("%s for job %s.", error, job_id)
                raise InvalidTransitionError(error)

            now = utc_now()
            updates: dict[str, Any] = {
                "status": new_status,
                "previous_status": current,
                "updated_at": now,
            }
            if new_status == "processing":
                updates["processing_started_at"] = now
            elif new_status == "uploaded":
                updates["uploaded_at"] = now
            elif new_status == "archived":
                updates["archived_at"] = now
            elif new_status == "skipped":
                updates["skipped_at"] = now

            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                (*updates.values(), job_id),
            )
            self.add_event(job_id, f"transition_to_{new_status}", message, metadata, conn=conn)
            return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def set_archive_result(self, job_id: int, archive_path: str) -> dict[str, Any]:
        self.initialize_database()
        with self._connect() as conn:
            now = utc_now()
            conn.execute(
                "UPDATE jobs SET archive_path = ?, updated_at = ? WHERE id = ?",
                (archive_path, now, job_id),
            )
            self.add_event(job_id, "archive_path_set", metadata={"archive_path": archive_path}, conn=conn)
            return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def set_archive_error(self, job_id: int, category: str, message: str) -> dict[str, Any]:
        self.initialize_database()
        with self._connect() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE jobs
                SET error_category = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (category, redact(message), now, job_id),
            )
            self.add_event(job_id, "archive_failed", redact(message), {"category": category}, conn=conn)
            return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def set_cleanup_result(self, job_id: int, status: str, error: str | None = None) -> dict[str, Any]:
        self.initialize_database()
        with self._connect() as conn:
            now = utc_now()
            conn.execute(
                "UPDATE jobs SET cleanup_status = ?, cleanup_error = ?, updated_at = ? WHERE id = ?",
                (status, redact(error) if error else None, now, job_id),
            )
            self.add_event(job_id, "cleanup_result_set", redact(error) if error else None, {"status": status}, conn=conn)
            return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def mark_failed(self, job_id: int, category: str, message: str, retryable: bool = True) -> dict[str, Any]:
        self.initialize_database()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise KeyError(f"Job {job_id} does not exist.")
            if row["status"] not in ACTIVE_STATES and row["status"] != "uploaded":
                raise InvalidTransitionError(f"Cannot mark {row['status']} job as failed.")
            now = utc_now()
            conn.execute(
                """
                UPDATE jobs
                SET status = 'failed', previous_status = ?, error_category = ?, error_message = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (row["status"], category, redact(message), now, job_id),
            )
            self.add_event(
                job_id,
                "failed",
                redact(message),
                {"category": category, "retryable": retryable},
                conn=conn,
            )
            return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def retry_job(self, job_id: int) -> dict[str, Any]:
        self.initialize_database()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise KeyError(f"Job {job_id} does not exist.")
            if row["status"] != "failed":
                raise InvalidTransitionError(f"Only failed jobs can be retried; job is {row['status']}.")
            if int(row["retry_count"]) >= int(row["max_retries"]):
                raise InvalidTransitionError("Job has reached max retries.")
            now = utc_now()
            conn.execute(
                """
                UPDATE jobs
                SET status = 'queued', previous_status = 'failed', retry_count = retry_count + 1,
                    error_category = NULL, error_message = NULL, updated_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )
            self.add_event(job_id, "retry_requested", "Failed job queued for retry.", conn=conn)
            return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def increment_retry(self, job_id: int) -> dict[str, Any]:
        self.initialize_database()
        with self._connect() as conn:
            now = utc_now()
            conn.execute("UPDATE jobs SET retry_count = retry_count + 1, updated_at = ? WHERE id = ?", (now, job_id))
            self.add_event(job_id, "retry_incremented", conn=conn)
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise KeyError(f"Job {job_id} does not exist.")
            return row_to_dict(row)

    def set_compressed_output(self, job_id: int, compressed_path: str, compressed_size: int | None) -> dict[str, Any]:
        self.initialize_database()
        with self._connect() as conn:
            now = utc_now()
            conn.execute(
                "UPDATE jobs SET compressed_path = ?, compressed_size = ?, updated_at = ? WHERE id = ?",
                (compressed_path, compressed_size, now, job_id),
            )
            self.add_event(job_id, "compressed_output_set", metadata={"compressed_size": compressed_size}, conn=conn)
            return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def set_discord_result(self, job_id: int, response_code: int, message_id: str | None = None) -> dict[str, Any]:
        self.initialize_database()
        with self._connect() as conn:
            now = utc_now()
            conn.execute(
                """
                UPDATE jobs
                SET discord_response_code = ?, discord_message_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (response_code, message_id, now, job_id),
            )
            self.add_event(job_id, "discord_result_set", metadata={"response_code": response_code}, conn=conn)
            return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def mark_archived(self, job_id: int) -> dict[str, Any]:
        return self.transition_job(job_id, "archived", "Original archived.")

    def add_event(
        self,
        job_id: int | None,
        event_type: str,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        owns_conn = conn is None
        active_conn = conn or self._connect()
        try:
            active_conn.execute(
                """
                INSERT INTO events (job_id, event_type, message, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    event_type,
                    redact(message) if message else None,
                    json.dumps(metadata or {}, sort_keys=True),
                    utc_now(),
                ),
            )
            if owns_conn:
                active_conn.commit()
        finally:
            if owns_conn:
                active_conn.close()

    def cleanup_old_completed(self, days: int = 30) -> int:
        self.initialize_database()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE status IN ('uploaded', 'archived', 'skipped') AND updated_at < ?",
                (cutoff,),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            if not ids:
                return 0
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM events WHERE job_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
            return len(ids)

    def reset_incomplete_jobs_on_startup(self) -> int:
        self.initialize_database()
        now = utc_now()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, status FROM jobs WHERE status IN ('processing', 'uploading', 'waiting_for_file_ready')"
            ).fetchall()
            for row in rows:
                if row["status"] == "waiting_for_file_ready":
                    new_status = "detected"
                elif row["status"] == "uploading":
                    new_status = "processed"
                else:
                    new_status = "queued"
                conn.execute(
                    "UPDATE jobs SET status = ?, previous_status = ?, updated_at = ? WHERE id = ?",
                    (new_status, row["status"], now, row["id"]),
                )
                self.add_event(
                    int(row["id"]),
                    "startup_recovered",
                    f"Recovered {row['status']} job to {new_status}.",
                    conn=conn,
                )
            return len(rows)

    def _first_job_with_statuses(self, statuses: tuple[str, ...]) -> dict[str, Any] | None:
        self.initialize_database()
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY updated_at ASC LIMIT 1",
                statuses,
            ).fetchone()
            return row_to_dict(row) if row else None

    def _latest_job_with_statuses(self, statuses: tuple[str, ...]) -> dict[str, Any] | None:
        self.initialize_database()
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY updated_at DESC LIMIT 1",
                statuses,
            ).fetchone()
            return row_to_dict(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def initialize_database() -> None:
    StateStore().initialize_database()


def build_job_identity(source_path: str | Path) -> JobIdentity:
    path = Path(source_path).expanduser()
    absolute = str(path.resolve(strict=False)).lower()
    filename = path.name
    size: int | None = None
    mtime: float | None = None
    try:
        stat = path.stat()
        size = int(stat.st_size)
        mtime = float(stat.st_mtime)
    except OSError:
        pass
    fingerprint = "|".join(
        [
            absolute,
            filename.lower(),
            "" if size is None else str(size),
            "" if mtime is None else f"{mtime:.6f}",
        ]
    )
    return JobIdentity(fingerprint, str(path.resolve(strict=False)), filename, size, mtime)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_known_status(status: str) -> None:
    if status not in JOB_STATES:
        raise ValueError(f"Unknown job status: {status}")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
