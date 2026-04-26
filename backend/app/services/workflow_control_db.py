from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from app.config import Settings
from app.models.dto import WorkflowRunRecord

CONTROL_PLANE_DB_FILENAME = "control-plane.sqlite3"
LEGACY_QUEUE_DB_FILENAME = "run-queue.sqlite3"
LEGACY_QUEUE_JSON_FILENAME = "run-queue.json"
LEGACY_RUN_INDEX_FILENAME = "run-index.json"
PROJECT_REGISTRY_FILENAME = "projects.json"

_CONTROL_DB_LOCK = threading.RLock()


def control_plane_db_path(settings: Settings) -> Path:
    return settings.agents_team_home / CONTROL_PLANE_DB_FILENAME


def _legacy_queue_db_path(settings: Settings) -> Path:
    return settings.agents_team_home / LEGACY_QUEUE_DB_FILENAME


def _legacy_queue_json_path(settings: Settings) -> Path:
    return settings.agents_team_home / LEGACY_QUEUE_JSON_FILENAME


def _legacy_run_index_path(settings: Settings) -> Path:
    return settings.agents_team_home / LEGACY_RUN_INDEX_FILENAME


def _project_registry_path(settings: Settings) -> Path:
    return settings.agents_team_home / PROJECT_REGISTRY_FILENAME


def connect_control_db(settings: Settings) -> sqlite3.Connection:
    settings.agents_team_home.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(control_plane_db_path(settings), timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_run_queue (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            project_path TEXT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            prepared INTEGER NOT NULL,
            enqueued_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT NULL,
            completed_at TEXT NULL,
            error TEXT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_run_queue_status_enqueued
        ON workflow_run_queue (status, enqueued_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_run_queue_run_status
        ON workflow_run_queue (run_id, status)
        """
    )
    _ensure_column(connection, "workflow_run_queue", "worker_id", "TEXT NULL")
    _ensure_column(connection, "workflow_run_queue", "heartbeat_at", "TEXT NULL")
    _ensure_column(connection, "workflow_run_queue", "lease_expires_at", "TEXT NULL")
    _ensure_column(connection, "workflow_run_queue", "item_kind", "TEXT NOT NULL DEFAULT 'run'")
    _ensure_column(connection, "workflow_run_queue", "target_step_id", "TEXT NULL")
    _ensure_column(connection, "workflow_run_queue", "branch_group_id", "TEXT NULL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id TEXT PRIMARY KEY,
            project_path TEXT NOT NULL,
            runtime_path TEXT NOT NULL,
            run_path TEXT NOT NULL,
            report_path TEXT NOT NULL,
            changes_path TEXT NOT NULL,
            log_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_project_created
        ON workflow_runs (project_path, created_at DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_updated
        ON workflow_runs (updated_at DESC)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_workers (
            worker_id TEXT PRIMARY KEY,
            thread_name TEXT NOT NULL,
            process_id INTEGER NOT NULL,
            host TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            last_heartbeat_at TEXT NOT NULL,
            current_item_id TEXT NULL,
            current_run_id TEXT NULL,
            stale_reason TEXT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_workers_status_heartbeat
        ON workflow_workers (status, last_heartbeat_at DESC)
        """
    )
    _ensure_column(connection, "workflow_workers", "stale_reason", "TEXT NULL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_agent_sessions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            title TEXT NOT NULL,
            agent_role TEXT NOT NULL,
            backend TEXT NOT NULL,
            execution TEXT NOT NULL,
            status TEXT NOT NULL,
            owner_worker_id TEXT NULL,
            provider TEXT NULL,
            session_ref TEXT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NULL,
            summary TEXT NULL,
            error TEXT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_agent_sessions_run_started
        ON workflow_agent_sessions (run_id, started_at ASC)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_agent_session_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_agent_session_events_session_sequence
        ON workflow_agent_session_events (session_id, sequence ASC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_agent_session_events_run_sequence
        ON workflow_agent_session_events (run_id, sequence ASC)
        """
    )


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_spec: str) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing = {str(row[1]) for row in rows}
    if column_name in existing:
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_spec}")


def _read_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _queue_table_has_rows(connection: sqlite3.Connection) -> bool:
    row = connection.execute("SELECT 1 FROM workflow_run_queue LIMIT 1").fetchone()
    return row is not None


def _run_table_has_rows(connection: sqlite3.Connection) -> bool:
    row = connection.execute("SELECT 1 FROM workflow_runs LIMIT 1").fetchone()
    return row is not None


def _migrate_legacy_queue_db(connection: sqlite3.Connection, settings: Settings) -> None:
    legacy_db_path = _legacy_queue_db_path(settings)
    if not legacy_db_path.exists() or legacy_db_path == control_plane_db_path(settings):
        return

    legacy_connection = sqlite3.connect(legacy_db_path)
    legacy_connection.row_factory = sqlite3.Row
    try:
        rows = legacy_connection.execute(
            """
            SELECT
                id,
                run_id,
                project_path,
                mode,
                status,
                prepared,
                enqueued_at,
                updated_at,
                started_at,
                completed_at,
                error
            FROM workflow_run_queue
            """
        ).fetchall()
    except sqlite3.Error:
        return
    finally:
        legacy_connection.close()

    if not rows:
        return

    connection.executemany(
        """
        INSERT OR IGNORE INTO workflow_run_queue (
            id,
            run_id,
            project_path,
            mode,
            status,
            prepared,
            enqueued_at,
            updated_at,
            started_at,
            completed_at,
            error,
            item_kind,
            target_step_id,
            branch_group_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["id"],
                row["run_id"],
                row["project_path"],
                row["mode"],
                row["status"],
                row["prepared"],
                row["enqueued_at"],
                row["updated_at"],
                row["started_at"],
                row["completed_at"],
                row["error"],
                "run",
                None,
                None,
            )
            for row in rows
        ],
    )


def _migrate_legacy_queue_json(connection: sqlite3.Connection, settings: Settings) -> None:
    payload = _read_json(_legacy_queue_json_path(settings))
    if not isinstance(payload, list):
        return

    rows: list[tuple[object, ...]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                (
                    str(item["id"]),
                    str(item["run_id"]),
                    str(item["project_path"]) if item.get("project_path") else None,
                    str(item["mode"]),
                    str(item["status"]),
                    1 if bool(item.get("prepared", False)) else 0,
                    str(item["enqueued_at"]),
                    str(item.get("updated_at") or item["enqueued_at"]),
                    str(item["started_at"]) if item.get("started_at") else None,
                    str(item["completed_at"]) if item.get("completed_at") else None,
                    str(item["error"]) if item.get("error") else None,
                )
            )
        except KeyError:
            continue

    if not rows:
        return

    connection.executemany(
        """
        INSERT OR IGNORE INTO workflow_run_queue (
            id,
            run_id,
            project_path,
            mode,
            status,
            prepared,
            enqueued_at,
            updated_at,
            started_at,
            completed_at,
            error,
            item_kind,
            target_step_id,
            branch_group_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _legacy_run_payloads(settings: Settings) -> list[dict]:
    candidate_paths: dict[str, Path] = {}

    run_index_payload = _read_json(_legacy_run_index_path(settings))
    if isinstance(run_index_payload, list):
        for row in run_index_payload:
            if not isinstance(row, dict):
                continue
            run_path = row.get("run_path")
            if not isinstance(run_path, str) or not run_path:
                continue
            candidate = Path(run_path) / "run.json"
            candidate_paths[str(candidate)] = candidate

    project_registry_payload = _read_json(_project_registry_path(settings))
    if isinstance(project_registry_payload, list):
        for row in project_registry_payload:
            if not isinstance(row, dict):
                continue
            runtime_path = row.get("runtime_path")
            if not isinstance(runtime_path, str) or not runtime_path:
                continue
            runs_dir = Path(runtime_path) / "runs"
            if not runs_dir.exists():
                continue
            for run_dir in runs_dir.iterdir():
                candidate = run_dir / "run.json"
                candidate_paths[str(candidate)] = candidate

    payloads: list[dict] = []
    for candidate in candidate_paths.values():
        data = _read_json(candidate)
        if not isinstance(data, dict):
            continue
        try:
            record = WorkflowRunRecord.model_validate(data)
        except Exception:  # noqa: BLE001
            continue
        payloads.append(record.model_dump(mode="json"))
    return payloads


def _migrate_legacy_runs(connection: sqlite3.Connection, settings: Settings) -> None:
    payloads = _legacy_run_payloads(settings)
    if not payloads:
        return

    connection.executemany(
        """
        INSERT OR IGNORE INTO workflow_runs (
            id,
            project_path,
            runtime_path,
            run_path,
            report_path,
            changes_path,
            log_path,
            created_at,
            updated_at,
            status,
            payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                payload["id"],
                payload["project_path"],
                payload["runtime_path"],
                payload["run_path"],
                payload["report_path"],
                payload["changes_path"],
                payload["log_path"],
                payload["created_at"],
                payload["updated_at"],
                payload["status"],
                json.dumps(payload, ensure_ascii=False),
            )
            for payload in payloads
        ],
    )


def initialize_control_db(settings: Settings) -> None:
    with _CONTROL_DB_LOCK:
        connection = connect_control_db(settings)
        try:
            _create_schema(connection)
            if not _queue_table_has_rows(connection):
                _migrate_legacy_queue_db(connection, settings)
                if not _queue_table_has_rows(connection):
                    _migrate_legacy_queue_json(connection, settings)
            if not _run_table_has_rows(connection):
                _migrate_legacy_runs(connection, settings)
        finally:
            connection.close()
