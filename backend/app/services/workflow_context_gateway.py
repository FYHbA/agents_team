from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.models.dto import WorkflowRunRecord, WorkflowStepRun
from app.services.workflow_artifact_paths import (
    changed_diff_path,
    final_state_path,
    project_summary_state_path,
    recent_runs_state_path,
    repo_snapshot_state_path,
    run_state_path,
    selected_memory_path,
    step_context_state_path,
    upstream_handoff_state_path,
    verify_summary_path,
)
from app.services.workflow_context_audit import create_context_audit
from app.services.workflow_context_policy import (
    PROJECT_PROJECTION_EXCLUDES,
    ContextPolicy,
    context_policy_for_step,
)
from app.services.workflow_contracts import (
    build_final_state_contract,
    load_final_state_contract,
    load_research_result_contract,
    load_review_result_contract,
    load_verify_summary_contract,
    persist_changed_diff,
    write_final_state_contract,
)
from app.services.workflow_run_store import trim_summary, write_json
from app.services.workflow_reuse import recent_reuse_candidates

MAX_SELECTED_MEMORY_ITEMS = 3
MAX_TOP_LEVEL_ENTRIES = 40
MAX_FILE_SAMPLES = 160
MAX_DIFF_CHARS = 12_000
MAX_UPSTREAM_STEPS = 4
STATE_DIRNAME = ".agents-context"


@dataclass(frozen=True)
class PreparedStepContext:
    policy: ContextPolicy
    workspace_path: Path
    state_path: Path
    output_path: Path
    audit_id: str
    source_projection_root: Path | None = None
    projection_manifest_path: Path | None = None


def _context_root(record: WorkflowRunRecord, step_run: WorkflowStepRun, settings: Settings) -> Path:
    return settings.agents_team_home / "context-workspaces" / record.id / step_run.step_id


def _state_file(state_path: Path, filename: str) -> Path:
    state_path.mkdir(parents=True, exist_ok=True)
    return state_path / filename


def _file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _top_level_entries(project_path: Path, *, limit: int = MAX_TOP_LEVEL_ENTRIES) -> list[str]:
    entries: list[str] = []
    try:
        children = sorted(project_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    except OSError:
        return entries
    for child in children:
        if child.name in PROJECT_PROJECTION_EXCLUDES:
            continue
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{suffix}")
        if len(entries) >= limit:
            break
    return entries


def _file_samples(project_path: Path, *, limit: int = MAX_FILE_SAMPLES) -> list[str]:
    samples: list[str] = []
    for root, dir_names, file_names in os.walk(project_path):
        dir_names[:] = [name for name in sorted(dir_names) if name not in PROJECT_PROJECTION_EXCLUDES]
        for file_name in sorted(file_names):
            if len(samples) >= limit:
                return samples
            path = Path(root) / file_name
            try:
                rel_path = path.relative_to(project_path)
            except ValueError:
                continue
            if _should_exclude_project_path(rel_path):
                continue
            samples.append(rel_path.as_posix())
    return samples


def _project_summary_payload(record: WorkflowRunRecord) -> dict[str, object]:
    project_path = Path(record.project_path)
    return {
        "project_name": project_path.name,
        "task": record.task,
        "top_level_entries": _top_level_entries(project_path),
        "file_samples": _file_samples(project_path, limit=80),
        "step_count": len(record.steps),
        "agent_count": len(record.agents),
        "allow_network": record.allow_network,
        "allow_installs": record.allow_installs,
    }


def _repo_snapshot_payload(record: WorkflowRunRecord) -> dict[str, object]:
    project_path = Path(record.project_path)
    return {
        "project_name": project_path.name,
        "top_level_entries": _top_level_entries(project_path),
        "file_samples": _file_samples(project_path),
    }


def _selected_memory_items(record: WorkflowRunRecord) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for entry in record.memory_context.recalled_project[:MAX_SELECTED_MEMORY_ITEMS]:
        selected.append(
            {
                "scope": entry.scope,
                "title": entry.title,
                "summary": entry.summary,
                "created_at": entry.created_at,
            }
        )
    remaining = MAX_SELECTED_MEMORY_ITEMS - len(selected)
    if remaining > 0:
        for entry in record.memory_context.recalled_global[:remaining]:
            selected.append(
                {
                    "scope": entry.scope,
                    "title": entry.title,
                    "summary": entry.summary,
                    "created_at": entry.created_at,
                }
            )
    return selected


def _run_state_payload(record: WorkflowRunRecord) -> dict[str, object]:
    return {
        "run_id": record.id,
        "task": record.task,
        "status": record.status,
        "warnings": list(record.warnings),
        "reuse": {
            "decision": record.reuse_decision,
            "matched_run_id": record.matched_run_id,
            "reason": record.reuse_reason,
            "confidence": record.reuse_confidence,
            "delta_hint": record.delta_hint,
            "delta_scope": (record.delta_scope.model_dump(mode="json") if record.delta_scope is not None else None),
        },
        "steps": [
            {
                "step_id": step_run.step_id,
                "title": step_run.title,
                "status": step_run.status,
                "summary": trim_summary(step_run.summary, limit=220),
            }
            for step_run in record.step_runs
        ],
    }


def _artifact_excerpt_for_step(record: WorkflowRunRecord, step_id: str) -> str | None:
    if step_id == "research":
        contract = load_research_result_contract(record)
        if contract is not None:
            return trim_summary(contract.summary, limit=500)
    if step_id.startswith("verify"):
        contract = load_verify_summary_contract(record)
        if contract is not None:
            return trim_summary(contract.summary, limit=500)
    if step_id == "review":
        contract = load_review_result_contract(record)
        if contract is not None:
            return trim_summary(contract.summary, limit=500)
    if step_id == "report":
        contract = load_final_state_contract(record)
        if contract is not None:
            return trim_summary(contract.summary, limit=500)
    if step_id == "implement" and record.last_message_path:
        candidate = Path(record.last_message_path)
        if candidate.exists():
            return trim_summary(candidate.read_text(encoding="utf-8").strip(), limit=500)
    candidate = Path(record.run_path) / "planning-brief.md"
    if step_id == "plan" and candidate.exists():
        return trim_summary(candidate.read_text(encoding="utf-8").strip(), limit=500)
    return None


def _upstream_handoff_payload(record: WorkflowRunRecord, current_step_id: str) -> dict[str, object]:
    prior_steps: list[dict[str, str | None]] = []
    for step_run in record.step_runs:
        if step_run.step_id == current_step_id or step_run.status not in {"completed", "failed", "cancelled", "skipped"}:
            continue
        prior_steps.append(
            {
                "step_id": step_run.step_id,
                "title": step_run.title,
                "status": step_run.status,
                "summary": trim_summary(step_run.summary, limit=220),
                "artifact_excerpt": _artifact_excerpt_for_step(record, step_run.step_id),
            }
        )
    return {
        "current_step_id": current_step_id,
        "prior_steps": prior_steps[-MAX_UPSTREAM_STEPS:],
    }


def _verify_summary_payload(record: WorkflowRunRecord) -> dict[str, object]:
    contract = load_verify_summary_contract(record)
    if contract is not None:
        return contract.model_dump(mode="json")
    verify_steps = [step for step in record.step_runs if step.step_id.startswith("verify")]
    return {
        "verify_steps": [
            {
                "step_id": step.step_id,
                "status": step.status,
                "summary": trim_summary(step.summary, limit=240),
                "commands": [preview.label for preview in step.command_previews],
            }
            for step in verify_steps
        ]
    }


def _final_state_payload(record: WorkflowRunRecord) -> dict[str, object]:
    contract = load_final_state_contract(record)
    if contract is None:
        contract = build_final_state_contract(record)
        write_final_state_contract(record, contract)
    return contract.model_dump(mode="json")


def _step_context_payload(record: WorkflowRunRecord, step_run: WorkflowStepRun, policy: ContextPolicy) -> dict[str, object]:
    source_names = {
        "project_summary": "project-summary.json",
        "repo_snapshot": "repo-snapshot.json",
        "run_state": "run-state.json",
        "step_context": "step-context.json",
        "selected_memory": "selected-memory.json",
        "recent_runs": "recent-runs.json",
        "upstream_handoff": "upstream-handoff.json",
        "verify_summary": "verify-summary.json",
        "final_state": "final-state.json",
        "changed_diff": "changed.diff",
    }
    return {
        "run_id": record.id,
        "project_name": Path(record.project_path).name,
        "step_id": step_run.step_id,
        "title": step_run.title,
        "agent_role": step_run.agent_role,
        "backend": step_run.backend,
        "execution": step_run.execution,
        "goal": step_run.goal,
        "depends_on": list(step_run.depends_on),
        "reuse": {
            "decision": record.reuse_decision,
            "matched_run_id": record.matched_run_id,
            "delta_hint": record.delta_hint,
            "delta_scope": (record.delta_scope.model_dump(mode="json") if record.delta_scope is not None else None),
        },
        "available_context_files": [f"{STATE_DIRNAME}/{source_names[key]}" for key in policy.source_keys],
    }


def _changed_diff_text(record: WorkflowRunRecord) -> str:
    cached_diff_path = changed_diff_path(record)
    if cached_diff_path.exists():
        return cached_diff_path.read_text(encoding="utf-8")
    project_path = Path(record.project_path)
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_path), "diff", "--no-ext-diff", "--binary", "--", ".", ":(exclude).agents-team"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        completed = None
    if completed and completed.returncode == 0 and completed.stdout.strip():
        diff_text = completed.stdout.strip()
        if len(diff_text) > MAX_DIFF_CHARS:
            diff_text = f"{diff_text[: MAX_DIFF_CHARS - 15].rstrip()}\n...diff truncated..."
        persist_changed_diff(record, diff_text)
        return diff_text

    excerpt = _artifact_excerpt_for_step(record, "review")
    if excerpt:
        diff_text = f"# Derived review excerpt\n\n{excerpt}\n"
        persist_changed_diff(record, diff_text)
        return diff_text
    diff_text = "# No tracked diff was available for this run.\n"
    persist_changed_diff(record, diff_text)
    return diff_text


def _materialize_payload(path: Path, payload: dict[str, object] | list[object] | str) -> int:
    if isinstance(payload, str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    else:
        write_json(path, payload)
    return _file_bytes(path)


def _should_exclude_project_path(relative_path: Path) -> bool:
    parts = set(relative_path.parts)
    return any(name in parts for name in PROJECT_PROJECTION_EXCLUDES) or relative_path.name.endswith(".pyc")


def _copy_project_projection(project_path: Path, workspace_path: Path) -> None:
    for root, dir_names, file_names in os.walk(project_path):
        dir_names[:] = [name for name in sorted(dir_names) if name not in PROJECT_PROJECTION_EXCLUDES]
        for file_name in sorted(file_names):
            path = Path(root) / file_name
            try:
                rel_path = path.relative_to(project_path)
            except ValueError:
                continue
            if _should_exclude_project_path(rel_path):
                continue
            destination = workspace_path / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_projection_manifest(workspace_path: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(workspace_path.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel_path = path.relative_to(workspace_path)
        except ValueError:
            continue
        if rel_path.parts and rel_path.parts[0] == STATE_DIRNAME:
            continue
        manifest[rel_path.as_posix()] = _hash_file(path)
    return manifest


def _write_projection_manifest(path: Path, workspace_path: Path) -> None:
    write_json(path, _build_projection_manifest(workspace_path))


def _remove_empty_parent_dirs(path: Path, *, stop_at: Path) -> None:
    current = path.parent
    while current != stop_at and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _sync_projection_back(project_path: Path, workspace_path: Path, manifest_path: Path) -> None:
    if not manifest_path.exists():
        return
    before = {}
    try:
        payload = manifest_path.read_text(encoding="utf-8")
        before = {str(key): str(value) for key, value in json.loads(payload).items()}
    except Exception:  # noqa: BLE001
        before = {}
    after = _build_projection_manifest(workspace_path)

    for rel_path, current_hash in after.items():
        if before.get(rel_path) == current_hash:
            continue
        source = workspace_path / Path(rel_path)
        destination = project_path / Path(rel_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    for rel_path in sorted(set(before) - set(after)):
        destination = project_path / Path(rel_path)
        if destination.exists():
            destination.unlink()
            _remove_empty_parent_dirs(destination, stop_at=project_path)


def prepare_step_context(
    *,
    record: WorkflowRunRecord,
    step_run: WorkflowStepRun,
    settings: Settings,
    output_filename: str,
) -> PreparedStepContext:
    policy = context_policy_for_step(step_run.step_id)
    context_root = _context_root(record, step_run, settings)
    if context_root.exists():
        shutil.rmtree(context_root)
    workspace_path = context_root / "workspace"
    output_path = context_root / "outputs" / output_filename
    workspace_path.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if policy.allow_source_projection:
        _copy_project_projection(Path(record.project_path), workspace_path)

    state_path = workspace_path / STATE_DIRNAME
    state_path.mkdir(parents=True, exist_ok=True)

    memory_items = _selected_memory_items(record)
    source_payloads: dict[str, dict[str, object] | list[object] | str] = {
        "project_summary": _project_summary_payload(record),
        "repo_snapshot": _repo_snapshot_payload(record),
        "run_state": _run_state_payload(record),
        "step_context": _step_context_payload(record, step_run, policy),
        "selected_memory": {"items": memory_items},
        "recent_runs": {"items": recent_reuse_candidates(record, settings)},
        "upstream_handoff": _upstream_handoff_payload(record, step_run.step_id),
        "verify_summary": _verify_summary_payload(record),
        "final_state": _final_state_payload(record),
        "changed_diff": _changed_diff_text(record),
    }
    source_names = {
        "project_summary": "project-summary.json",
        "repo_snapshot": "repo-snapshot.json",
        "run_state": "run-state.json",
        "step_context": "step-context.json",
        "selected_memory": "selected-memory.json",
        "recent_runs": "recent-runs.json",
        "upstream_handoff": "upstream-handoff.json",
        "verify_summary": "verify-summary.json",
        "final_state": "final-state.json",
        "changed_diff": "changed.diff",
    }

    input_sources: list[dict[str, object]] = []
    input_bytes = 0
    persisted_state_paths = {
        "project_summary": project_summary_state_path(record),
        "repo_snapshot": repo_snapshot_state_path(record),
        "run_state": run_state_path(record),
        "selected_memory": selected_memory_path(record),
        "recent_runs": recent_runs_state_path(record),
        "changed_diff": changed_diff_path(record),
        "step_context": step_context_state_path(record, step_run.step_id),
        "upstream_handoff": upstream_handoff_state_path(record, step_run.step_id),
        "verify_summary": verify_summary_path(record),
        "final_state": final_state_path(record),
    }
    for key in policy.source_keys:
        path = _state_file(state_path, source_names[key])
        size = _materialize_payload(path, source_payloads[key])
        _materialize_payload(persisted_state_paths[key], source_payloads[key])
        input_bytes += size
        input_sources.append(
            {
                "key": key,
                "path": f"{STATE_DIRNAME}/{path.name}",
                "bytes": size,
            }
        )

    projection_manifest_path: Path | None = None
    if policy.allow_source_projection:
        projection_manifest_path = context_root / "projection-manifest.json"
        _write_projection_manifest(projection_manifest_path, workspace_path)

    audit_id = create_context_audit(
        record=record,
        step_run=step_run,
        settings=settings,
        workspace_path=str(workspace_path),
        input_sources=input_sources,
        input_bytes=input_bytes,
        memory_item_count=len(memory_items),
        raw_log_bytes_included=0,
        markdown_artifact_bytes_included=0,
    )
    return PreparedStepContext(
        policy=policy,
        workspace_path=workspace_path,
        state_path=state_path,
        output_path=output_path,
        audit_id=audit_id,
        source_projection_root=workspace_path if policy.allow_source_projection else None,
        projection_manifest_path=projection_manifest_path,
    )


def finalize_step_context(
    *,
    prepared: PreparedStepContext,
    final_output_path: Path,
    record: WorkflowRunRecord,
) -> None:
    if prepared.output_path.exists():
        final_output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prepared.output_path, final_output_path)
    if prepared.source_projection_root and prepared.projection_manifest_path:
        _sync_projection_back(
            Path(record.project_path),
            prepared.source_projection_root,
            prepared.projection_manifest_path,
        )
