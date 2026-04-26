from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Literal, TypedDict, cast
from uuid import uuid4

from app.config import Settings
from app.models.dto import WorkflowQueueDashboardResponse, WorkflowQueueItemRecord
from app.services.workflow_control_db import connect_control_db, control_plane_db_path, initialize_control_db
from app.services.workflow_run_store import now_iso
from app.services.workflow_worker_state import list_workflow_workers

WorkflowQueueMode = Literal["start", "resume", "retry"]
WorkflowQueueStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class WorkflowQueueItem(TypedDict):
    id: str
    run_id: str
    project_path: str | None
    mode: WorkflowQueueMode
    item_kind: Literal["run", "step"]
    target_step_id: str | None
    branch_group_id: str | None
    status: WorkflowQueueStatus
    prepared: bool
    enqueued_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None
    error: str | None
    worker_id: str | None
    heartbeat_at: str | None
    lease_expires_at: str | None


DEFAULT_WORKER_LEASE_SECONDS = 20
STALE_WORKER_GRACE_MULTIPLIER = 2
DASHBOARD_TERMINAL_ITEM_LIMIT = 8
DASHBOARD_IDLE_WORKER_LIMIT = 4
WORKER_HISTORY_RETENTION_HOURS = 12


def workflow_queue_path(settings: Settings):
    return control_plane_db_path(settings)


def _row_to_item(row: sqlite3.Row) -> WorkflowQueueItem:
    return {
        "id": str(row["id"]),
        "run_id": str(row["run_id"]),
        "project_path": str(row["project_path"]) if row["project_path"] is not None else None,
        "mode": cast(WorkflowQueueMode, row["mode"]),
        "item_kind": cast(Literal["run", "step"], row["item_kind"] or "run"),
        "target_step_id": str(row["target_step_id"]) if row["target_step_id"] is not None else None,
        "branch_group_id": str(row["branch_group_id"]) if row["branch_group_id"] is not None else None,
        "status": cast(WorkflowQueueStatus, row["status"]),
        "prepared": bool(row["prepared"]),
        "enqueued_at": str(row["enqueued_at"]),
        "updated_at": str(row["updated_at"]),
        "started_at": str(row["started_at"]) if row["started_at"] is not None else None,
        "completed_at": str(row["completed_at"]) if row["completed_at"] is not None else None,
        "error": str(row["error"]) if row["error"] is not None else None,
        "worker_id": str(row["worker_id"]) if row["worker_id"] is not None else None,
        "heartbeat_at": str(row["heartbeat_at"]) if row["heartbeat_at"] is not None else None,
        "lease_expires_at": str(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
    }


def _empty_queue_item(
    *,
    run_id: str,
    project_path: str | None,
    mode: WorkflowQueueMode,
    prepared: bool,
    item_kind: Literal["run", "step"] = "run",
    target_step_id: str | None = None,
    branch_group_id: str | None = None,
) -> WorkflowQueueItem:
    now = now_iso()
    return {
        "id": f"job-{uuid4().hex[:12]}",
        "run_id": run_id,
        "project_path": project_path,
        "mode": mode,
        "item_kind": item_kind,
        "target_step_id": target_step_id,
        "branch_group_id": branch_group_id,
        "status": "queued",
        "prepared": prepared,
        "enqueued_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "error": None,
        "worker_id": None,
        "heartbeat_at": None,
        "lease_expires_at": None,
    }


def read_workflow_queue(settings: Settings) -> list[WorkflowQueueItem]:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        rows = connection.execute(
            """
            SELECT
                id,
                run_id,
                project_path,
                mode,
                item_kind,
                target_step_id,
                branch_group_id,
                status,
                prepared,
                enqueued_at,
                updated_at,
                started_at,
                completed_at,
                error,
                worker_id,
                heartbeat_at,
                lease_expires_at
            FROM workflow_run_queue
            ORDER BY enqueued_at ASC, id ASC
            """
        ).fetchall()
        return [_row_to_item(row) for row in rows]
    finally:
        connection.close()


def has_active_workflow_queue_item(run_id: str, settings: Settings) -> bool:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        row = connection.execute(
            """
            SELECT 1
            FROM workflow_run_queue
            WHERE run_id = ?
              AND status IN ('queued', 'running')
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def enqueue_workflow_run(
    *,
    run_id: str,
    project_path: str | None,
    mode: WorkflowQueueMode,
    prepared: bool,
    item_kind: Literal["run", "step"] = "run",
    target_step_id: str | None = None,
    branch_group_id: str | None = None,
    settings: Settings,
) -> WorkflowQueueItem:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT
                id,
                run_id,
                project_path,
                mode,
                item_kind,
                target_step_id,
                branch_group_id,
                status,
                prepared,
                enqueued_at,
                updated_at,
                started_at,
                completed_at,
                error,
                worker_id,
                heartbeat_at,
                lease_expires_at
            FROM workflow_run_queue
            WHERE run_id = ?
              AND item_kind = ?
              AND COALESCE(target_step_id, '') = COALESCE(?, '')
              AND status IN ('queued', 'running')
            ORDER BY enqueued_at ASC, id ASC
            LIMIT 1
            """,
            (run_id, item_kind, target_step_id),
        ).fetchone()
        if row is not None:
            connection.commit()
            return _row_to_item(row)

        item = _empty_queue_item(
            run_id=run_id,
            project_path=project_path,
            mode=mode,
            prepared=prepared,
            item_kind=item_kind,
            target_step_id=target_step_id,
            branch_group_id=branch_group_id,
        )
        connection.execute(
            """
            INSERT INTO workflow_run_queue (
                id,
                run_id,
                project_path,
                mode,
                item_kind,
                target_step_id,
                branch_group_id,
                status,
                prepared,
                enqueued_at,
                updated_at,
                started_at,
                completed_at,
                error,
                worker_id,
                heartbeat_at,
                lease_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["run_id"],
                item["project_path"],
                item["mode"],
                item["item_kind"],
                item["target_step_id"],
                item["branch_group_id"],
                item["status"],
                1 if item["prepared"] else 0,
                item["enqueued_at"],
                item["updated_at"],
                item["started_at"],
                item["completed_at"],
                item["error"],
                item["worker_id"],
                item["heartbeat_at"],
                item["lease_expires_at"],
            ),
        )
        connection.commit()
        return item
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def claim_next_workflow_queue_item(settings: Settings, worker_id: str, lease_seconds: int = DEFAULT_WORKER_LEASE_SECONDS) -> WorkflowQueueItem | None:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _requeue_expired_running_items(connection)
        _mark_stale_workers(connection)
        row = connection.execute(
            """
            SELECT
                id,
                run_id,
                project_path,
                mode,
                item_kind,
                target_step_id,
                branch_group_id,
                status,
                prepared,
                enqueued_at,
                updated_at,
                started_at,
                completed_at,
                error,
                worker_id,
                heartbeat_at,
                lease_expires_at
            FROM workflow_run_queue
            WHERE status = 'queued'
            ORDER BY enqueued_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            connection.commit()
            return None

        claimed_at = now_iso()
        lease_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        connection.execute(
            """
            UPDATE workflow_run_queue
            SET status = 'running',
                started_at = ?,
                updated_at = ?,
                error = NULL,
                worker_id = ?,
                heartbeat_at = ?,
                lease_expires_at = ?
            WHERE id = ?
              AND status = 'queued'
            """,
            (claimed_at, claimed_at, worker_id, claimed_at, lease_expires_at, row["id"]),
        )
        claimed_row = connection.execute(
            """
            SELECT
                id,
                run_id,
                project_path,
                mode,
                item_kind,
                target_step_id,
                branch_group_id,
                status,
                prepared,
                enqueued_at,
                updated_at,
                started_at,
                completed_at,
                error,
                worker_id,
                heartbeat_at,
                lease_expires_at
            FROM workflow_run_queue
            WHERE id = ?
            """,
            (row["id"],),
        ).fetchone()
        connection.commit()
        return _row_to_item(claimed_row) if claimed_row is not None else None
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def complete_workflow_queue_item(
    *,
    item_id: str,
    status: Literal["completed", "failed", "cancelled"],
    settings: Settings,
    error: str | None = None,
) -> None:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        completed_at = now_iso()
        connection.execute(
            """
            UPDATE workflow_run_queue
            SET status = ?,
                completed_at = ?,
                updated_at = ?,
                error = ?,
                worker_id = NULL,
                heartbeat_at = NULL,
                lease_expires_at = NULL
            WHERE id = ?
            """,
            (status, completed_at, completed_at, error, item_id),
        )
    finally:
        connection.close()


def cancel_active_workflow_queue_items(run_id: str, settings: Settings, *, reason: str) -> None:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        cancelled_at = now_iso()
        connection.execute(
            """
            UPDATE workflow_run_queue
            SET status = 'cancelled',
                completed_at = ?,
                updated_at = ?,
                error = ?,
                worker_id = NULL,
                heartbeat_at = NULL,
                lease_expires_at = NULL
            WHERE run_id = ?
              AND status IN ('queued', 'running')
            """,
            (cancelled_at, cancelled_at, reason, run_id),
        )
    finally:
        connection.close()


def delete_workflow_queue_items(run_id: str, settings: Settings) -> None:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        connection.execute(
            """
            DELETE FROM workflow_run_queue
            WHERE run_id = ?
            """,
            (run_id,),
        )
    finally:
        connection.close()


def requeue_interrupted_workflow_queue_items(settings: Settings) -> int:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        return _requeue_all_running_items(connection)
    finally:
        connection.close()


def heartbeat_workflow_queue_item(
    *,
    item_id: str,
    worker_id: str,
    settings: Settings,
    lease_seconds: int = DEFAULT_WORKER_LEASE_SECONDS,
) -> None:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        heartbeat = now_iso()
        lease_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        connection.execute(
            """
            UPDATE workflow_run_queue
            SET updated_at = ?,
                heartbeat_at = ?,
                lease_expires_at = ?
            WHERE id = ?
              AND worker_id = ?
              AND status = 'running'
            """,
            (heartbeat, heartbeat, lease_expires_at, item_id, worker_id),
        )
    finally:
        connection.close()


def get_workflow_queue_dashboard(settings: Settings) -> WorkflowQueueDashboardResponse:
    _cleanup_stale_runtime_state(settings)
    all_items = [WorkflowQueueItemRecord.model_validate(item) for item in read_workflow_queue(settings)]
    active_items = [item for item in all_items if item.status in {"queued", "running"}]
    terminal_items = sorted(
        [item for item in all_items if item.status in {"completed", "failed", "cancelled"}],
        key=lambda item: item.updated_at,
        reverse=True,
    )
    items = active_items + terminal_items[:DASHBOARD_TERMINAL_ITEM_LIMIT]

    all_workers = list_workflow_workers(settings)
    attention_workers = [worker for worker in all_workers if worker.status in {"running", "stale"}]
    idle_workers = [worker for worker in all_workers if worker.status == "idle"]
    workers = attention_workers + idle_workers[:DASHBOARD_IDLE_WORKER_LIMIT]
    stale_count = sum(1 for item in all_items if _is_stale(item.lease_expires_at, item.status))
    return WorkflowQueueDashboardResponse(
        items=items,
        workers=workers,
        queued_count=sum(1 for item in all_items if item.status == "queued"),
        running_count=sum(1 for item in all_items if item.status == "running"),
        terminal_count=sum(1 for item in all_items if item.status in {"completed", "failed", "cancelled"}),
        stale_count=stale_count,
        stale_worker_count=sum(1 for worker in all_workers if worker.status == "stale"),
        hidden_terminal_count=max(len(terminal_items) - DASHBOARD_TERMINAL_ITEM_LIMIT, 0),
        hidden_worker_count=max(len(all_workers) - len(workers), 0),
    )


def has_active_run_queue_item(run_id: str, settings: Settings) -> bool:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        row = connection.execute(
            """
            SELECT 1
            FROM workflow_run_queue
            WHERE run_id = ?
              AND item_kind = 'run'
              AND status IN ('queued', 'running')
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def has_active_branch_group_items(branch_group_id: str, settings: Settings) -> bool:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        row = connection.execute(
            """
            SELECT 1
            FROM workflow_run_queue
            WHERE branch_group_id = ?
              AND item_kind = 'step'
              AND status IN ('queued', 'running')
            LIMIT 1
            """,
            (branch_group_id,),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def has_active_step_queue_item(run_id: str, settings: Settings) -> bool:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        row = connection.execute(
            """
            SELECT 1
            FROM workflow_run_queue
            WHERE run_id = ?
              AND item_kind = 'step'
              AND status IN ('queued', 'running')
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def _is_stale(lease_expires_at: str | None, status: str) -> bool:
    if status != "running" or not lease_expires_at:
        return False
    try:
        return datetime.fromisoformat(lease_expires_at) < datetime.now(timezone.utc)
    except ValueError:
        return False


def _requeue_expired_running_items(connection: sqlite3.Connection) -> int:
    requeued_at = now_iso()
    cursor = connection.execute(
        """
        UPDATE workflow_run_queue
        SET status = 'queued',
            updated_at = ?,
            started_at = NULL,
            completed_at = NULL,
            error = 'Worker lease expired before this queue item reached a terminal state.',
            worker_id = NULL,
            heartbeat_at = NULL,
            lease_expires_at = NULL
        WHERE status = 'running'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < ?
        """,
        (requeued_at, requeued_at),
    )
    return int(cursor.rowcount)


def _mark_stale_workers(connection: sqlite3.Connection) -> int:
    now = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(seconds=DEFAULT_WORKER_LEASE_SECONDS * STALE_WORKER_GRACE_MULTIPLIER)).isoformat()
    now_iso_value = now.isoformat()
    cursor = connection.execute(
        """
        UPDATE workflow_workers
        SET status = 'stale',
            stale_reason = CASE
                WHEN current_item_id IS NOT NULL AND EXISTS (
                    SELECT 1
                    FROM workflow_run_queue q
                    WHERE q.id = workflow_workers.current_item_id
                      AND (
                        q.status != 'running'
                        OR (q.lease_expires_at IS NOT NULL AND q.lease_expires_at < ?)
                      )
                ) THEN 'Worker heartbeat is stale or its claimed queue item lost the lease.'
                ELSE 'Worker heartbeat has not been refreshed within the stale grace window.'
            END
        WHERE status = 'running'
          AND (
            last_heartbeat_at < ?
            OR (
                current_item_id IS NOT NULL
                AND EXISTS (
                    SELECT 1
                    FROM workflow_run_queue q
                    WHERE q.id = workflow_workers.current_item_id
                      AND (
                        q.status != 'running'
                        OR (q.lease_expires_at IS NOT NULL AND q.lease_expires_at < ?)
                      )
                )
            )
          )
        """,
        (now_iso_value, stale_cutoff, now_iso_value),
    )
    return int(cursor.rowcount)


def _cleanup_stale_runtime_state(settings: Settings) -> tuple[int, int]:
    initialize_control_db(settings)
    connection = connect_control_db(settings)
    try:
        connection.execute("BEGIN IMMEDIATE")
        requeued = _requeue_expired_running_items(connection)
        stale_workers = _mark_stale_workers(connection)
        _prune_historical_workers(connection)
        connection.commit()
        return requeued, stale_workers
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _requeue_all_running_items(connection: sqlite3.Connection) -> int:
    requeued_at = now_iso()
    cursor = connection.execute(
        """
        UPDATE workflow_run_queue
        SET status = 'queued',
            updated_at = ?,
            started_at = NULL,
            completed_at = NULL,
            error = 'Worker restarted before this queue item reached a terminal state.',
            worker_id = NULL,
            heartbeat_at = NULL,
            lease_expires_at = NULL
        WHERE status = 'running'
        """,
        (requeued_at,),
    )
    return int(cursor.rowcount)


def _prune_historical_workers(connection: sqlite3.Connection) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=WORKER_HISTORY_RETENTION_HOURS)).isoformat()
    cursor = connection.execute(
        """
        DELETE FROM workflow_workers
        WHERE status IN ('idle', 'stale')
          AND current_item_id IS NULL
          AND current_run_id IS NULL
          AND last_heartbeat_at < ?
        """,
        (cutoff,),
    )
    return int(cursor.rowcount)
