from __future__ import annotations

from pathlib import Path

from app.models.dto import WorkflowRunRecord


def state_dir(record: WorkflowRunRecord) -> Path:
    return Path(record.run_path) / "state"


def planning_brief_path(record: WorkflowRunRecord) -> Path:
    return Path(record.run_path) / "planning-brief.md"


def project_snapshot_path(record: WorkflowRunRecord) -> Path:
    return Path(record.run_path) / "project-snapshot.md"


def research_result_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "research-result.json"


def verification_brief_path(record: WorkflowRunRecord) -> Path:
    return Path(record.run_path) / "verification-brief.md"


def verify_summary_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "verify-summary.json"


def review_result_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "review-result.json"


def final_state_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "final-state.json"


def run_state_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "run-state.json"


def selected_memory_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "selected-memory.json"


def recent_runs_state_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "recent-runs.json"


def changed_diff_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "changed.diff"


def repo_snapshot_state_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "repo-snapshot.json"


def project_summary_state_path(record: WorkflowRunRecord) -> Path:
    return state_dir(record) / "project-summary.json"


def step_context_state_path(record: WorkflowRunRecord, step_id: str) -> Path:
    return state_dir(record) / f"{step_id}-step-context.json"


def upstream_handoff_state_path(record: WorkflowRunRecord, step_id: str) -> Path:
    return state_dir(record) / f"{step_id}-upstream-handoff.json"


def parallel_branches_path(record: WorkflowRunRecord) -> Path:
    return Path(record.run_path) / "parallel-branches.md"
