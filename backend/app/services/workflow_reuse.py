from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.config import Settings
from app.models.dto import WorkflowDeltaScope, WorkflowRunRecord
from app.services.workflow_contracts import load_review_result_contract
from app.services.workflow_run_store import get_workflow_run, list_workflow_runs, trim_summary

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "then",
    "than",
    "your",
    "will",
    "have",
    "after",
    "before",
    "about",
    "workflow",
    "project",
    "task",
    "code",
}

_DOC_FILENAMES = {
    "readme",
    "readme.md",
    "changelog",
    "changelog.md",
    "license",
    "license.md",
}
_DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".adoc"}
_BUILD_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".sass", ".less", ".html", ".vue", ".svelte"}
_BUILD_FILENAMES = {
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "vite.config.js",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
}


def _normalize_task(text: str) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9_+-/*().]+", text.lower()))


def _tokenize_task(text: str) -> set[str]:
    tokens = re.findall(r"[A-Za-z0-9_]{3,}", text.lower())
    return {token for token in tokens if token not in _STOPWORDS}


def _task_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_task(left)
    normalized_right = _normalize_task(right)
    if normalized_left and normalized_left == normalized_right:
        return 1.0
    left_tokens = _tokenize_task(left)
    right_tokens = _tokenize_task(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    if union == 0:
        return 0.0
    return intersection / union


def _project_has_source_drift(project_path: str) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "-C", project_path, "diff", "--quiet", "--", ".", ":(exclude).agents-team"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode == 0:
        return False
    if completed.returncode == 1:
        return True
    return None


def _project_diff_names(project_path: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", project_path, "diff", "--name-only", "--", ".", ":(exclude).agents-team"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _looks_like_doc_path(path_str: str) -> bool:
    path = Path(path_str)
    normalized_parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return (
        name in _DOC_FILENAMES
        or path.suffix.lower() in _DOC_SUFFIXES
        or "docs" in normalized_parts
        or "doc" in normalized_parts
    )


def _looks_like_build_path(path_str: str) -> bool:
    path = Path(path_str)
    normalized_parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return (
        "frontend" in normalized_parts
        or name in _BUILD_FILENAMES
        or path.suffix.lower() in _BUILD_SUFFIXES
    )


def _verification_focus_for_paths(paths: list[str]) -> str:
    if not paths:
        return "all"
    categories: set[str] = set()
    for path in paths:
        if _looks_like_doc_path(path):
            categories.add("docs")
            continue
        if _looks_like_build_path(path):
            categories.add("build")
            continue
        categories.add("tests")

    non_doc_categories = categories - {"docs"}
    if not non_doc_categories:
        return "docs"
    if non_doc_categories == {"build"}:
        return "build"
    if non_doc_categories == {"tests"}:
        return "tests"
    return "all"


def _build_delta_scope(run_id: str, project_path: str, settings: Settings) -> WorkflowDeltaScope:
    matched_run_changed_files = _candidate_changed_files(run_id, project_path, settings)
    current_diff_files = _project_diff_names(project_path)[:6]
    focus_paths = current_diff_files or matched_run_changed_files[:6]
    verification_focus = _verification_focus_for_paths(focus_paths)
    scope_summary_parts: list[str] = []
    if focus_paths:
        scope_summary_parts.append("Focus paths: " + ", ".join(focus_paths[:4]) + ".")
    if verification_focus == "docs":
        scope_summary_parts.append("Verification can stay lightweight because the remaining delta is documentation-heavy.")
    elif verification_focus == "tests":
        scope_summary_parts.append("Verification should emphasize regression tests over unrelated build checks.")
    elif verification_focus == "build":
        scope_summary_parts.append("Verification should emphasize build or frontend checks over unrelated regression suites.")
    else:
        scope_summary_parts.append("Verification should stay scoped to the smallest mixed set of checks that still covers the remaining delta.")
    return WorkflowDeltaScope(
        focus_paths=focus_paths,
        matched_run_changed_files=matched_run_changed_files[:6],
        current_diff_files=current_diff_files,
        verification_focus=verification_focus,  # type: ignore[arg-type]
        scope_summary=" ".join(scope_summary_parts).strip(),
    )


def recent_reuse_candidates(record: WorkflowRunRecord, settings: Settings, *, limit: int = 5) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for run in list_workflow_runs(record.project_path, settings):
        if run.id == record.id:
            continue
        if run.status not in {"completed", "short_circuited"}:
            continue
        similarity = _task_similarity(record.task, run.task)
        if similarity <= 0:
            continue
        candidates.append(
            {
                "run_id": run.id,
                "status": run.status,
                "task": run.task,
                "similarity": round(similarity, 3),
                "completed_at": run.completed_at,
                "summary": trim_summary(run.summary, limit=220),
                "reuse_decision": run.reuse_decision,
                "matched_run_id": run.matched_run_id,
            }
        )
    candidates.sort(key=lambda item: (float(item["similarity"]), str(item.get("completed_at") or "")), reverse=True)
    return candidates[:limit]


def has_recent_reuse_candidate(project_path: str | None, task: str, settings: Settings) -> bool:
    if not project_path:
        return False
    probe = WorkflowRunRecord.model_construct(
        id="probe",
        status="planned",
        attempt_count=0,
        created_at="",
        updated_at="",
        started_at=None,
        completed_at=None,
        cancel_requested_at=None,
        cancelled_at=None,
        task=task,
        project_path=project_path,
        runtime_path="",
        run_path="",
        report_path="",
        changes_path="",
        log_path="",
        last_message_path=None,
        memory_scope="project",
        git_strategy="manual",
        direct_file_editing=True,
        requires_dangerous_command_confirmation=False,
        dangerous_commands_confirmed_at=None,
        team_name="",
        summary="",
        allow_network=True,
        allow_installs=True,
        command_policy="",
        agents=[],
        steps=[],
        outputs=[],
        warnings=[],
        error=None,
        reuse_decision=None,
        matched_run_id=None,
        reuse_reason=None,
        reuse_confidence=None,
        delta_hint=None,
        step_runs=[],
        memory_context=None,  # type: ignore[arg-type]
        memory_guidance=None,  # type: ignore[arg-type]
        codex_session_id=None,
        codex_commands=[],
    )
    return bool(recent_reuse_candidates(probe, settings, limit=1))


def _candidate_changed_files(run_id: str, project_path: str, settings: Settings) -> list[str]:
    try:
        matched_run = get_workflow_run(run_id, project_path, settings)
    except Exception:  # noqa: BLE001
        return []
    review_contract = load_review_result_contract(matched_run)
    if review_contract is not None and review_contract.changed_files:
        return review_contract.changed_files[:6]
    return []


def _delta_hint_for_candidate(run_id: str, project_path: str, settings: Settings) -> str:
    candidate_files = _candidate_changed_files(run_id, project_path, settings)
    current_diff_files = _project_diff_names(project_path)
    hints: list[str] = []
    if candidate_files:
        hints.append("Focus first on the files that changed in the matched run: " + ", ".join(candidate_files[:4]) + ".")
    if current_diff_files:
        hints.append("Current source drift is visible in: " + ", ".join(current_diff_files[:4]) + ".")
    if not hints:
        hints.append("Limit execution to the smallest remaining delta that separates the current repo state from the matched successful run.")
    return " ".join(hints)


def infer_reuse_decision(record: WorkflowRunRecord, settings: Settings) -> tuple[str, str | None, float, str, str, WorkflowDeltaScope | None]:
    candidates = recent_reuse_candidates(record, settings, limit=1)
    if not candidates:
        return "continue", None, 0.0, "", "", None

    best = candidates[0]
    similarity = float(best["similarity"])
    drift = _project_has_source_drift(record.project_path)
    if similarity >= 0.92 and drift is False:
        matched_run_id = str(best["run_id"])
        reason = (
            "A highly similar successful run already exists for this project, and Git reports no source drift outside `.agents-team`."
        )
        return "stop_as_duplicate", matched_run_id, similarity, reason, "", None
    if similarity >= 0.75:
        matched_run_id = str(best["run_id"])
        if drift is True:
            reason = "A similar successful run exists, but current source drift means the workflow should continue only on the remaining delta."
        else:
            reason = "A similar successful run exists, but the match is not strong enough to stop immediately without a narrowed delta-focused pass."
        delta_scope = _build_delta_scope(matched_run_id, record.project_path, settings)
        return (
            "continue_with_delta",
            matched_run_id,
            similarity,
            reason,
            _delta_hint_for_candidate(matched_run_id, record.project_path, settings),
            delta_scope,
        )
    return "continue", None, similarity, "", "", None
