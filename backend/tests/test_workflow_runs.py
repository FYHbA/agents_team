from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models.dto import CodexCommandSpec, CodexSessionBridgeResponse, CodexSessionSummary, MemoryEntry, WorkflowRunCreateRequest
from app.services import workflow_run_execution as execution_service
from app.services import workflow_backend_codex_delegate as delegate_service
from app.services.workflow_agent_sessions import append_agent_session_event, finish_agent_session, start_agent_session
from app.services.workflow_backend_planner import execute_planner_backend, planning_brief_path
from app.services.workflow_control_db import connect_control_db
from app.services.workflow_backend_research import execute_research_backend, project_snapshot_path
from app.services.workflow_backend_verify import execute_verify_backend, verification_brief_path
from app.services.workflow_memory import global_memory_path, project_memory_path
from app.services.workflow_run_queue import complete_workflow_queue_item, enqueue_workflow_run, read_workflow_queue, workflow_queue_path
from app.services.workflow_run_steps import WorkflowCancellationRequested
from app.services.workflow_run_store import now_iso, run_store_path, save_record
from app.services.workflow_runs import (
    approve_workflow_run_dangerous_commands,
    cancel_workflow_run,
    create_workflow_run,
    delete_workflow_run,
    execute_workflow_run_now,
    get_workflow_queue_dashboard,
    get_workflow_run,
    list_agent_sessions,
    list_workflow_runs,
    read_workflow_run_artifacts,
    read_workflow_run_log,
    resume_workflow_run_now,
    retry_workflow_run_now,
    start_workflow_run,
)


def _write_report_artifacts(record) -> None:
    Path(record.changes_path).write_text("# Changes\n\n- simulated\n", encoding="utf-8")
    Path(record.report_path).write_text("# Report\n\nSimulated report.\n", encoding="utf-8")


def _patch_final_reporter(monkeypatch) -> None:
    class _UnavailableCapabilities:
        codex_cli_available = False

    monkeypatch.setattr(delegate_service, "get_codex_capabilities", lambda settings: _UnavailableCapabilities())


def _seed_memory(path: Path, entries: list[MemoryEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([entry.model_dump(mode="json") for entry in entries], indent=2), encoding="utf-8")


def _approve_run(record, test_settings) -> None:
    approve_workflow_run_dangerous_commands(record.id, record.project_path, test_settings)


def _wait_for_terminal(record, test_settings, timeout: float = 3):
    deadline = time.monotonic() + timeout
    final_record = record
    while time.monotonic() < deadline:
        final_record = get_workflow_run(record.id, record.project_path, test_settings)
        if final_record.status != "running":
            return final_record
        time.sleep(0.05)
    return final_record


def _wait_for_queue_status(run_id: str, expected_status: str, test_settings, timeout: float = 3) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        queue_items = read_workflow_queue(test_settings)
        if any(item["run_id"] == run_id and item["status"] == expected_status for item in queue_items):
            return True
        time.sleep(0.05)
    return False


def test_workflow_run_is_persisted_and_listed(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Implement the first workflow run persistence layer and verify the saved outputs.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    run_path = Path(record.run_path)
    assert run_path.exists()
    assert run_store_path(test_settings).exists()
    assert Path(record.report_path).exists()
    assert Path(record.changes_path).exists()
    assert Path(record.log_path).exists()
    assert record.step_runs
    assert all(step.status == "pending" for step in record.step_runs)
    assert all(step.backend for step in record.step_runs)
    assert any(step.step_id == "plan" and step.backend == "planner_backend" for step in record.step_runs)

    listed = list_workflow_runs(str(project_path), test_settings)
    assert listed
    assert listed[0].id == record.id

    loaded = get_workflow_run(record.id, str(project_path), test_settings)
    assert loaded.id == record.id
    assert loaded.git_strategy == "manual"
    assert loaded.attempt_count == 0
    assert loaded.requires_dangerous_command_confirmation is True
    assert loaded.dangerous_commands_confirmed_at is None


def test_workflow_run_copies_command_previews_into_steps_and_step_runs(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    (project_path / "tests").mkdir()
    (project_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "build": "vite build",
                    "test": "vitest run",
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.workflow_runs.build_session_bridge",
        lambda *args, **kwargs: CodexSessionBridgeResponse(
            session=CodexSessionSummary(id="sess-1", thread_name="Test Session", updated_at=now_iso()),
            project_path=str(project_path),
            session_log_path=None,
            can_resume=True,
            commands=[
                CodexCommandSpec(
                    argv=["codex", "exec", "resume", "sess-1", "prompt"],
                    cwd=str(project_path),
                    mode="non_interactive",
                    purpose="Resume the selected Codex session in non-interactive mode.",
                )
            ],
            strategies=["exec_resume"],
            warnings=[],
        ),
    )

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Run regression tests and benchmark the build output.",
            project_path=str(project_path),
            codex_session_id="sess-1",
        ),
        test_settings,
    )

    implement_step = next(step for step in record.steps if step.id == "implement")
    verify_tests_step = next(step for step in record.steps if step.id == "verify_tests")
    verify_tests_run = next(step for step in record.step_runs if step.step_id == "verify_tests")

    assert implement_step.command_previews
    assert implement_step.command_previews[0].source == "codex_bridge"
    assert [preview.label for preview in verify_tests_step.command_previews] == ["python -m pytest", "npm run test"]
    assert [preview.label for preview in verify_tests_run.command_previews] == ["python -m pytest", "npm run test"]


def test_workflow_run_requires_dangerous_command_approval_before_execute(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Run repository checks only after the user approves command-backed execution.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    with pytest.raises(HTTPException, match="Approve the run first"):
        execute_workflow_run_now(record.id, str(project_path), test_settings)

    approved = approve_workflow_run_dangerous_commands(record.id, str(project_path), test_settings)
    assert approved.dangerous_commands_confirmed_at is not None


def test_workflow_run_supports_partial_command_approval_before_full_unlock(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    (project_path / "tests").mkdir()
    (project_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "build": "vite build",
                    "test": "vitest run",
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Run regression tests and benchmark the build output.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    verify_tests = next(step for step in record.steps if step.id == "verify_tests")
    first_command_id = verify_tests.command_previews[0].command_id

    partially_approved = approve_workflow_run_dangerous_commands(
        record.id,
        str(project_path),
        test_settings,
        command_ids=[first_command_id],
    )
    assert partially_approved.dangerous_commands_confirmed_at is None
    refreshed_tests = next(step for step in partially_approved.steps if step.id == "verify_tests")
    assert refreshed_tests.command_previews[0].confirmed_at is not None
    assert refreshed_tests.command_previews[1].confirmed_at is None

    with pytest.raises(HTTPException, match="Approve the remaining"):
        execute_workflow_run_now(record.id, str(project_path), test_settings)

    fully_approved = approve_workflow_run_dangerous_commands(record.id, str(project_path), test_settings)
    assert fully_approved.dangerous_commands_confirmed_at is not None


def test_start_immediately_keeps_run_planned_until_dangerous_commands_are_approved(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Create a run that would normally start immediately after planning.",
            project_path=str(project_path),
            start_immediately=True,
        ),
        test_settings,
    )

    assert record.status == "planned"
    assert record.dangerous_commands_confirmed_at is None
    assert any("explicit approval" in warning.lower() for warning in record.warnings)


def test_workflow_run_delete_removes_records_and_artifacts(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Delete a completed run and all of its stored UI state.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    Path(record.last_message_path).write_text("Final message for deletion coverage.\n", encoding="utf-8")
    queue_item = enqueue_workflow_run(
        run_id=record.id,
        project_path=str(project_path),
        mode="start",
        prepared=True,
        settings=test_settings,
    )
    complete_workflow_queue_item(item_id=queue_item["id"], status="completed", settings=test_settings)

    step_run = next(step for step in record.step_runs if step.step_id == "implement")
    session = start_agent_session(
        record=record,
        step_run=step_run,
        settings=test_settings,
        worker_id="worker-delete",
    )
    append_agent_session_event(
        settings=test_settings,
        event_type="agent_message",
        payload={"text": "Preparing this run for deletion."},
    )
    finish_agent_session(
        session_id=session.id,
        settings=test_settings,
        status="completed",
        summary="Deletion coverage session completed.",
    )

    deleted = delete_workflow_run(record.id, str(project_path), test_settings)
    assert deleted.run_id == record.id
    assert deleted.project_path == str(project_path)

    with pytest.raises(HTTPException, match=f"Run not found: {record.id}"):
        get_workflow_run(record.id, str(project_path), test_settings)

    assert not Path(record.run_path).exists()
    assert not Path(record.report_path).exists()

    connection = connect_control_db(test_settings)
    try:
        run_count = connection.execute("SELECT COUNT(*) FROM workflow_runs WHERE id = ?", (record.id,)).fetchone()[0]
        queue_count = connection.execute("SELECT COUNT(*) FROM workflow_run_queue WHERE run_id = ?", (record.id,)).fetchone()[0]
        session_count = connection.execute("SELECT COUNT(*) FROM workflow_agent_sessions WHERE run_id = ?", (record.id,)).fetchone()[0]
        event_count = connection.execute(
            "SELECT COUNT(*) FROM workflow_agent_session_events WHERE run_id = ?",
            (record.id,),
        ).fetchone()[0]
    finally:
        connection.close()

    assert run_count == 0
    assert queue_count == 0
    assert session_count == 0
    assert event_count == 0


def test_workflow_run_delete_rejects_active_queue_items(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Try to delete a queued workflow run before it is safe.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    enqueue_workflow_run(
        run_id=record.id,
        project_path=str(project_path),
        mode="start",
        prepared=True,
        settings=test_settings,
    )

    with pytest.raises(HTTPException, match="Cannot delete a queued or running run"):
        delete_workflow_run(record.id, str(project_path), test_settings)


def test_background_start_persists_and_completes_queue_item(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "implement":
            Path(record.last_message_path).write_text("Implemented through the persistent queue.", encoding="utf-8")
            return "Implemented through the persistent queue."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- queued execution\n", encoding="utf-8")
            return "Reviewed queued execution."
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Reported queued execution."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Run this workflow through the persistent queue worker.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    started = start_workflow_run(record.id, str(project_path), test_settings)
    assert started.status == "running"
    assert workflow_queue_path(test_settings).exists()

    completed = _wait_for_terminal(record, test_settings)
    assert completed.status == "completed"
    assert _wait_for_queue_status(record.id, "completed", test_settings)
    dashboard = get_workflow_queue_dashboard(test_settings)
    assert dashboard.items
    assert dashboard.workers
    assert any(worker.worker_id for worker in dashboard.workers)


def test_recover_workflow_queue_resumes_orphaned_running_run(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "implement":
            Path(record.last_message_path).write_text("Recovered and completed after restart.", encoding="utf-8")
            return "Recovered implementation."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- recovered run\n", encoding="utf-8")
            return "Reviewed recovered run."
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Reported recovered run."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Recover an orphaned running workflow after a backend restart.",
            project_path=str(project_path),
        ),
        test_settings,
    )
    approved = approve_workflow_run_dangerous_commands(record.id, str(project_path), test_settings)
    approved.status = "running"
    approved.started_at = now_iso()
    approved.attempt_count = 1
    approved.updated_at = now_iso()
    save_record(approved, test_settings)

    recovered_count = execution_service.recover_workflow_queue(test_settings)
    assert recovered_count == 1

    queue_items = read_workflow_queue(test_settings)
    recovered_item = next(item for item in queue_items if item["run_id"] == record.id)
    assert recovered_item["status"] == "queued"
    assert recovered_item["mode"] == "resume"
    assert recovered_item["prepared"] is False

    assert execution_service.process_workflow_queue_once(test_settings) is True
    completed = get_workflow_run(record.id, str(project_path), test_settings)
    assert completed.status == "completed"
    assert completed.attempt_count == 2


def test_queue_dashboard_requeues_expired_items_and_marks_stale_workers(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Run regression tests and benchmark the build output.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    enqueue_workflow_run(
        run_id=record.id,
        project_path=str(project_path),
        mode="start",
        prepared=True,
        settings=test_settings,
    )
    queued_item = read_workflow_queue(test_settings)[0]
    connection = connect_control_db(test_settings)
    try:
        connection.execute(
            """
            UPDATE workflow_run_queue
            SET status = 'running',
                worker_id = 'worker-stale',
                heartbeat_at = '2026-01-01T00:00:00+00:00',
                lease_expires_at = '2026-01-01T00:00:00+00:00'
            WHERE id = ?
            """,
            (queued_item["id"],),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO workflow_workers (
                worker_id,
                thread_name,
                process_id,
                host,
                status,
                started_at,
                last_heartbeat_at,
                current_item_id,
                current_run_id,
                stale_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "worker-stale",
                "workflow-queue-worker-0",
                123,
                "localhost",
                "running",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                queued_item["id"],
                record.id,
                None,
            ),
        )
    finally:
        connection.close()

    dashboard = get_workflow_queue_dashboard(test_settings)
    refreshed_item = next(item for item in dashboard.items if item.id == queued_item["id"])
    stale_worker = next(worker for worker in dashboard.workers if worker.worker_id == "worker-stale")

    assert refreshed_item.status == "queued"
    assert dashboard.stale_worker_count >= 1
    assert stale_worker.status == "stale"
    assert stale_worker.stale_reason


def test_workflow_run_executes_to_completion(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "implement":
            (Path(record.project_path) / "implemented.txt").write_text("done\n", encoding="utf-8")
            Path(record.last_message_path).write_text("Implemented implemented.txt and reviewed the result.", encoding="utf-8")
            return "Executed a fake Codex implementation step."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- implemented.txt\n", encoding="utf-8")
            return "Captured a fake review summary."
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Wrote a fake report."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Implement the first real workflow execution loop for this repository.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    executed = execute_workflow_run_now(record.id, str(project_path), test_settings)
    assert executed.status == "completed"
    assert executed.attempt_count == 1
    assert executed.started_at is not None
    assert executed.completed_at is not None
    assert executed.error is None
    assert any(step.step_id == "implement" and step.status == "completed" for step in executed.step_runs)
    assert any(step.step_id == "report" and step.status == "completed" for step in executed.step_runs)
    assert Path(executed.report_path).read_text(encoding="utf-8")
    assert Path(executed.log_path).read_text(encoding="utf-8")
    assert (project_path / "implemented.txt").exists()

    log = read_workflow_run_log(executed.id, str(project_path), test_settings)
    assert log.run_id == executed.id
    assert "Workflow start started" in log.content

    agent_sessions = list_agent_sessions(executed.id, test_settings)
    assert agent_sessions
    assert any(session.step_id == "implement" and session.status == "completed" for session in agent_sessions)


def test_agent_sessions_can_return_structured_chat_events(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Implement structured chat events for a workflow run.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    step_run = next(step for step in record.step_runs if step.step_id == "implement")
    session = start_agent_session(
        record=record,
        step_run=step_run,
        settings=test_settings,
        worker_id="worker-test",
    )
    append_agent_session_event(
        settings=test_settings,
        event_type="agent_message",
        payload={"text": "I am inspecting the repo before editing."},
    )
    append_agent_session_event(
        settings=test_settings,
        event_type="command_execution",
        payload={
            "command_id": "cmd-1",
            "label": "rg --files",
            "command": "rg --files",
            "status": "completed",
            "output": "calculator.py",
            "exit_code": 0,
        },
    )
    append_agent_session_event(
        settings=test_settings,
        event_type="agent_message",
        payload={"text": "Implemented the calculator and verified the entrypoint."},
    )
    finish_agent_session(
        session_id=session.id,
        settings=test_settings,
        status="completed",
        summary="Implemented the calculator and verified the entrypoint.",
    )

    sessions = list_agent_sessions(record.id, test_settings)
    loaded = next(item for item in sessions if item.id == session.id)
    assert loaded.status == "completed"
    assert [event.event_type for event in loaded.events] == [
        "agent_message",
        "command_execution",
        "agent_message",
        "session_summary",
    ]
    assert loaded.has_structured_timeline is True
    assert loaded.thinking_messages == ["I am inspecting the repo before editing."]
    assert loaded.final_message == "Implemented the calculator and verified the entrypoint."
    assert loaded.collapsed_preview == "Implemented the calculator and verified the entrypoint."
    assert len(loaded.commands) == 1
    assert loaded.commands[0].command == "rg --files"
    assert loaded.events[0].payload["text"] == "I am inspecting the repo before editing."
    assert loaded.events[1].payload["command"] == "rg --files"


def test_failed_run_can_resume_without_repeating_completed_steps(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)
    counts = {"implement": 0, "verify": 0}

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "implement":
            counts["implement"] += 1
            (Path(record.project_path) / "implemented.txt").write_text("done\n", encoding="utf-8")
            return f"Implement attempt {counts['implement']}"
        if step_run.step_id == "verify":
            counts["verify"] += 1
            if counts["verify"] == 1:
                raise RuntimeError("verify failed once")
            return "Verify recovered on resume."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- resume path\n", encoding="utf-8")
            return "Review regenerated."
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Report regenerated."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Implement resume semantics after a verification failure.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    failed = execute_workflow_run_now(record.id, str(project_path), test_settings)
    assert failed.status == "failed"
    assert counts == {"implement": 1, "verify": 1}
    assert any(step.step_id == "verify" and step.status == "failed" for step in failed.step_runs)

    resumed = resume_workflow_run_now(record.id, str(project_path), test_settings)
    assert resumed.status == "completed"
    assert resumed.attempt_count == 2
    assert counts == {"implement": 1, "verify": 2}
    assert any(step.step_id == "implement" and step.status == "completed" for step in resumed.step_runs)
    assert any(step.step_id == "verify" and step.status == "completed" for step in resumed.step_runs)


def test_parallel_verify_wave_runs_ready_steps_concurrently(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)
    barrier = threading.Barrier(2)
    started: list[str] = []

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id in {"verify_tests", "verify_build"}:
            started.append(step_run.step_id)
            barrier.wait(timeout=2)
            return f"Completed {step_run.step_id} in the parallel wave."
        if step_run.step_id == "implement":
            Path(record.last_message_path).write_text("Implemented before running the parallel verify wave.", encoding="utf-8")
            return "Implementation completed."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- parallel wave\n", encoding="utf-8")
            return "Review completed."
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Report completed."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Benchmark the build and compare regression results across a multi-step matrix.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    executed = execute_workflow_run_now(record.id, str(project_path), test_settings)
    assert executed.status == "completed"
    assert set(started) == {"verify_tests", "verify_build"}
    assert any(step.step_id == "verify_tests" and step.status == "completed" for step in executed.step_runs)
    assert any(step.step_id == "verify_build" and step.status == "completed" for step in executed.step_runs)


def test_parallel_verify_branches_can_be_claimed_by_different_workers(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)
    first_branch_started = threading.Event()
    second_branch_started = threading.Event()
    branch_counter = {"count": 0}
    branch_lock = threading.Lock()

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id in {"verify_tests", "verify_build"}:
            with branch_lock:
                branch_counter["count"] += 1
                current_branch = branch_counter["count"]
            if current_branch == 1:
                first_branch_started.set()
                assert second_branch_started.wait(timeout=5)
            else:
                second_branch_started.set()
                assert first_branch_started.wait(timeout=5)
            return f"Completed {step_run.step_id} on a queued branch worker."
        if step_run.step_id == "implement":
            Path(record.last_message_path).write_text("Implementation completed before queued parallel verification.", encoding="utf-8")
            return "Implementation completed."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- queued parallel verification\n", encoding="utf-8")
            return "Review completed."
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Report completed."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Benchmark multi-environment regressions and compare build outputs in parallel.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    started = start_workflow_run(record.id, str(project_path), test_settings)
    assert started.status == "running"
    completed = _wait_for_terminal(record, test_settings, timeout=5)
    assert completed.status == "completed"

    sessions = list_agent_sessions(completed.id, test_settings)
    verify_sessions = [session for session in sessions if session.step_id in {"verify_tests", "verify_build"}]
    assert len(verify_sessions) == 2
    assert len({session.owner_worker_id for session in verify_sessions}) == 2


def test_failed_parallel_branch_still_allows_review_and_report(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "verify_build":
            raise RuntimeError("build verification failed")
        if step_run.step_id == "verify_tests":
            return "Regression tests passed."
        if step_run.step_id == "implement":
            Path(record.last_message_path).write_text("Implemented before partial review flow.", encoding="utf-8")
            return "Implementation completed."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- partial review path\n", encoding="utf-8")
            return "Review still executed after one branch failed."
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Report still executed after partial failure."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Compare build regressions and benchmark test outputs across multiple verification branches.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    executed = execute_workflow_run_now(record.id, str(project_path), test_settings)
    assert executed.status == "failed"
    assert any(step.step_id == "verify_build" and step.status == "failed" for step in executed.step_runs)
    assert any(step.step_id == "verify_tests" and step.status == "completed" for step in executed.step_runs)
    assert any(step.step_id == "review" and step.status == "completed" for step in executed.step_runs)
    assert any(step.step_id == "report" and step.status == "completed" for step in executed.step_runs)


def test_failed_run_can_retry_from_the_beginning(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)
    counts = {"implement": 0, "verify": 0}

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "implement":
            counts["implement"] += 1
            return f"Implement attempt {counts['implement']}"
        if step_run.step_id == "verify":
            counts["verify"] += 1
            if counts["verify"] == 1:
                raise RuntimeError("verify failed once")
            return "Verify recovered on retry."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- retry path\n", encoding="utf-8")
            return "Review regenerated."
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Report regenerated."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Implement retry semantics after a verification failure.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    failed = execute_workflow_run_now(record.id, str(project_path), test_settings)
    assert failed.status == "failed"

    retried = retry_workflow_run_now(record.id, str(project_path), test_settings)
    assert retried.status == "completed"
    assert retried.attempt_count == 2
    assert counts == {"implement": 2, "verify": 2}
    assert any(step.step_id == "implement" and step.status == "completed" for step in retried.step_runs)


def test_running_run_can_be_cancelled(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)
    implement_started = threading.Event()

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "implement":
            implement_started.set()
            while not should_cancel():
                time.sleep(0.02)
            raise WorkflowCancellationRequested("Workflow execution was cancelled by the user.")
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Report regenerated."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Implement cancellation semantics for a running workflow.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    started = start_workflow_run(record.id, str(project_path), test_settings)
    assert started.status == "running"
    assert implement_started.wait(timeout=2)

    cancel_result = cancel_workflow_run(record.id, str(project_path), test_settings)
    assert cancel_result.cancel_requested_at is not None

    deadline = time.monotonic() + 3
    final_record = cancel_result
    while time.monotonic() < deadline:
        final_record = get_workflow_run(record.id, str(project_path), test_settings)
        if final_record.status != "running":
            break
        time.sleep(0.05)

    assert final_record.status == "cancelled"
    assert final_record.cancel_requested_at is not None
    assert final_record.cancelled_at is not None
    assert any(step.step_id == "implement" and step.status == "cancelled" for step in final_record.step_runs)


def test_workflow_run_artifacts_bundle_supports_cockpit_review(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)
    (project_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "plan":
            (Path(record.run_path) / "planning-brief.md").write_text("# Planning Brief\n\nPlanner backend output.\n", encoding="utf-8")
            return "Planner backend produced a planning brief."
        if step_run.step_id == "research":
            snapshot_path = Path(record.run_path) / "project-snapshot.md"
            snapshot_path.write_text("# Project Snapshot\n\n- README.md\n", encoding="utf-8")
            return "Captured a fake project snapshot."
        if step_run.step_id == "implement":
            Path(record.last_message_path).write_text("Implemented the cockpit artifacts and summarized the run.", encoding="utf-8")
            return "Executed a fake Codex implementation step."
        if step_run.step_id == "verify":
            Path(record.run_path, "verification-brief.md").write_text("# Verification Brief\n\nDelegated verify output.\n", encoding="utf-8")
            return "Captured a fake verification summary."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- frontend/src/App.tsx\n", encoding="utf-8")
            return "Captured a fake review summary."
        if step_run.step_id == "report":
            return "Wrote a fake report."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Research the repository and generate readable workflow artifacts for cockpit review.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    executed = execute_workflow_run_now(record.id, str(project_path), test_settings)
    artifacts = read_workflow_run_artifacts(executed.id, str(project_path), test_settings)

    assert artifacts.run_id == executed.id
    documents = {document.key: document for document in artifacts.documents}
    assert documents["planning_brief"].available is True
    assert "Planning Brief" in documents["planning_brief"].content
    assert documents["report"].available is True
    assert "Codex Final Message" in documents["report"].content
    assert "Implemented the cockpit artifacts" in documents["report"].content
    assert documents["changes"].available is True
    assert "frontend/src/App.tsx" in documents["changes"].content
    assert documents["last_message"].available is True
    assert "summarized the run" in documents["last_message"].content
    assert documents["project_snapshot"].available is True
    assert "README.md" in documents["project_snapshot"].content
    assert documents["verification_brief"].available is True
    assert "Verification Brief" in documents["verification_brief"].content
    assert documents["parallel_branches"].available is True


def test_parallel_branch_summary_artifact_captures_parallel_steps(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id in {"verify_tests", "verify_build"}:
            return f"Completed {step_run.step_id}."
        if step_run.step_id == "implement":
            return "Implementation completed."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- branch artifact\n", encoding="utf-8")
            return "Review completed."
        if step_run.step_id == "report":
            _write_report_artifacts(record)
            return "Report completed."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Benchmark multi-environment regressions and compare build outputs in parallel.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    executed = execute_workflow_run_now(record.id, str(project_path), test_settings)
    artifacts = read_workflow_run_artifacts(executed.id, str(project_path), test_settings)
    documents = {document.key: document for document in artifacts.documents}

    assert "verify_tests" in documents["parallel_branches"].content
    assert "verify_build" in documents["parallel_branches"].content


def test_workflow_memory_is_recalled_and_written_back(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)

    _seed_memory(
        project_memory_path(project_path),
        [
            MemoryEntry(
                id="mem-project-1",
                scope="project",
                created_at="2026-04-22T10:00:00+00:00",
                source_run_id="run-old-project",
                attempt_count=1,
                title="Previous API failure",
                summary="The workflow failed around verify when the API contract drifted.",
                details="Remember to re-check the verify step after API changes.",
                tags=["api", "verify", "failure"],
            )
        ],
    )
    _seed_memory(
        global_memory_path(test_settings),
        [
            MemoryEntry(
                id="mem-global-1",
                scope="global",
                created_at="2026-04-22T12:00:00+00:00",
                source_run_id="run-old-global",
                attempt_count=1,
                title="Keep handoffs concise",
                summary="Strong handoffs include the final message, risks, and verification status.",
                details="Use the report and final message to seed future collaboration context.",
                tags=["handoff", "verification", "report"],
            )
        ],
    )

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "implement":
            Path(record.last_message_path).write_text("Implemented the memory integration and preserved handoff context.", encoding="utf-8")
            return "Executed the memory-aware implementation step."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- backend/app/services/workflow_memory.py\n", encoding="utf-8")
            return "Captured the memory integration changes."
        if step_run.step_id == "report":
            return "Wrote the final report."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Review the API memory handoff and improve verification reporting.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    assert len(record.memory_context.recalled_project) == 1
    assert record.memory_context.recalled_project[0].title == "Previous API failure"
    assert len(record.memory_context.recalled_global) == 1
    assert record.memory_context.recalled_global[0].title == "Keep handoffs concise"
    assert record.memory_guidance.planner
    assert record.memory_guidance.reviewer
    assert record.memory_guidance.reporter

    _approve_run(record, test_settings)
    executed = execute_workflow_run_now(record.id, str(project_path), test_settings)
    assert len(executed.memory_context.written_project) == 3
    assert len(executed.memory_context.written_global) == 1
    assert {entry.entry_kind for entry in executed.memory_context.written_project} == {
        "research_finding",
        "verification_finding",
        "handoff",
    }
    assert "memory integration" in executed.memory_context.written_global[0].summary.lower()

    project_memory_entries = json.loads(project_memory_path(project_path).read_text(encoding="utf-8"))
    global_memory_entries = json.loads(global_memory_path(test_settings).read_text(encoding="utf-8"))
    assert len(project_memory_entries) == 4
    assert len(global_memory_entries) == 2

    artifacts = read_workflow_run_artifacts(executed.id, str(project_path), test_settings)
    documents = {document.key: document for document in artifacts.documents}
    assert documents["memory_context"].available is True
    assert "Planner Guidance" in documents["memory_context"].content
    assert "Reviewer Checklist" in documents["memory_context"].content
    assert "Reporter Priorities" in documents["memory_context"].content
    assert "Recalled Project Memory" in documents["memory_context"].content
    assert "research_finding" in documents["memory_context"].content
    assert "verification_finding" in documents["memory_context"].content
    assert "Written Global Memory" in documents["memory_context"].content


def test_high_signal_step_findings_promote_reusable_global_rules(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()
    _patch_final_reporter(monkeypatch)

    def fake_execute_step(record, step_run, settings, should_cancel, set_active_process):  # noqa: ARG001
        if step_run.step_id == "research":
            snapshot_path = Path(record.run_path) / "project-snapshot.md"
            snapshot_path.write_text("# Project Snapshot\n\n- api/\n- tests/\n", encoding="utf-8")
            return "Always capture a top-level snapshot before editing a repo."
        if step_run.step_id == "implement":
            Path(record.last_message_path).write_text("Implemented the routing fix.", encoding="utf-8")
            return "Implemented the routing fix."
        if step_run.step_id == "verify":
            return "Always re-run routing regressions after API changes."
        if step_run.step_id == "review":
            Path(record.changes_path).write_text("# Changes\n\n- backend/app/api/routes/workflows.py\n", encoding="utf-8")
            return "Captured routing-focused review notes."
        if step_run.step_id == "report":
            return "Wrote the final report."
        return f"Completed step {step_run.step_id}."

    monkeypatch.setattr(execution_service, "execute_step", fake_execute_step)

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Research the routing workflow and verify the API changes carefully.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    _approve_run(record, test_settings)
    executed = execute_workflow_run_now(record.id, str(project_path), test_settings)
    promoted_rules = [entry for entry in executed.memory_context.written_global if entry.entry_kind == "global_rule"]
    assert len(promoted_rules) == 2
    assert all(entry.source_step_id in {"research", "verify"} for entry in promoted_rules)

    global_entries = json.loads(global_memory_path(test_settings).read_text(encoding="utf-8"))
    assert any(entry["entry_kind"] == "global_rule" for entry in global_entries)

    artifacts = read_workflow_run_artifacts(executed.id, str(project_path), test_settings)
    documents = {document.key: document for document in artifacts.documents}
    assert "Promoted Global Rules" in documents["report"].content
    assert "global_rule" in documents["memory_context"].content


def test_planner_backend_can_delegate_to_codex(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Plan a delegated backend workflow for this repository.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    class _Capabilities:
        codex_cli_available = True

    def fake_run(argv, **kwargs):  # noqa: ANN001
        artifact_path = Path(argv[argv.index("-o") + 1])
        artifact_path.write_text("# Planning Brief\n\nDelegated planner output.\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(delegate_service, "get_codex_capabilities", lambda settings: _Capabilities())
    monkeypatch.setattr(delegate_service, "_run_delegated_command", fake_run)

    summary = execute_planner_backend(
        record,
        test_settings,
        should_cancel=lambda: False,
        set_active_process=lambda process: None,  # noqa: ARG005
    )

    assert "delegated to Codex" in summary
    assert planning_brief_path(record).exists()
    assert "Delegated planner output" in planning_brief_path(record).read_text(encoding="utf-8")


def test_research_backend_can_delegate_to_codex(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Research a delegated backend workflow for this repository.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    class _Capabilities:
        codex_cli_available = True

    def fake_run(argv, **kwargs):  # noqa: ANN001
        artifact_path = Path(argv[argv.index("-o") + 1])
        artifact_path.write_text("# Project Snapshot\n\nDelegated research output.\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(delegate_service, "get_codex_capabilities", lambda settings: _Capabilities())
    monkeypatch.setattr(delegate_service, "_run_delegated_command", fake_run)

    summary = execute_research_backend(
        record,
        test_settings,
        should_cancel=lambda: False,
        set_active_process=lambda process: None,  # noqa: ARG005
    )

    assert "delegated to Codex" in summary
    assert project_snapshot_path(record).exists()
    assert "Delegated research output" in project_snapshot_path(record).read_text(encoding="utf-8")


def test_verify_backend_can_delegate_to_codex(monkeypatch, test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Verify a delegated backend workflow for this repository.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    class _Capabilities:
        codex_cli_available = True

    def fake_run(argv, **kwargs):  # noqa: ANN001
        artifact_path = Path(argv[argv.index("-o") + 1])
        artifact_path.write_text("# Verification Brief\n\nDelegated verify output.\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(delegate_service, "get_codex_capabilities", lambda settings: _Capabilities())
    monkeypatch.setattr(delegate_service, "_run_delegated_command", fake_run)

    summary = execute_verify_backend(
        record,
        next(step for step in record.step_runs if step.step_id.startswith("verify")),
        test_settings,
        should_cancel=lambda: False,
        set_active_process=lambda process: None,  # noqa: ARG005
    )

    assert "delegated to Codex" in summary
    assert verification_brief_path(record).exists()
    assert "Delegated verify output" in verification_brief_path(record).read_text(encoding="utf-8")
