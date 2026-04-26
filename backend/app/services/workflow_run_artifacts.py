from __future__ import annotations

import subprocess
from pathlib import Path

from app.models.dto import WorkflowArtifactDocument, WorkflowRunArtifactsResponse, WorkflowRunRecord
from app.services.workflow_artifact_paths import parallel_branches_path, planning_brief_path, project_snapshot_path, verification_brief_path
from app.services.workflow_memory import memory_context_markdown


def report_template(record: WorkflowRunRecord) -> str:
    lines = [
        f"# Workflow Run {record.id}",
        "",
        f"Project: `{record.project_path}`",
        f"Status: `{record.status}`",
        f"Attempt count: `{record.attempt_count}`",
        f"Created at: `{record.created_at}`",
        "",
        "## Task",
        "",
        record.task,
        "",
        "## Expected Outputs",
        "",
        *[f"- {item}" for item in record.outputs],
        "",
        "## Warnings",
        "",
        *[f"- {warning}" for warning in record.warnings],
        "",
    ]
    return "\n".join(lines)


def changes_template(record: WorkflowRunRecord) -> str:
    return "\n".join(
        [
            f"# Planned Changes for {record.id}",
            "",
            "- Direct file edits will be recorded here as the workflow executes.",
            "- Git commit and push remain manual in V1.",
            "- Reviewer memory cross-checks will be recorded here when available.",
            "",
        ]
    )


def _top_level_entries(project_path: Path, limit: int = 60) -> list[str]:
    entries: list[str] = []
    for child in sorted(project_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))[:limit]:
        if child.name in {".git", "node_modules", ".venv", "__pycache__"}:
            continue
        suffix = "/" if child.is_dir() else ""
        entries.append(f"- {child.name}{suffix}")
    return entries


def write_project_snapshot(record: WorkflowRunRecord) -> str:
    project_path = Path(record.project_path)
    artifact_path = Path(record.run_path) / "project-snapshot.md"
    entries = _top_level_entries(project_path)
    artifact_path.write_text(
        "\n".join(
            [
                "# Project Snapshot",
                "",
                f"Project root: `{record.project_path}`",
                "",
                "## Top-level entries",
                "",
                *(entries or ["- No visible entries found."]),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return f"Captured a top-level project snapshot with {len(entries)} visible entries."


def _git_capture(project_path: str, argv: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", project_path, *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def write_changes_summary(record: WorkflowRunRecord) -> str:
    status = _git_capture(record.project_path, ["status", "--short"])
    diff_stat = _git_capture(record.project_path, ["diff", "--stat"])
    diff_names = _git_capture(record.project_path, ["diff", "--name-only"])

    lines = [
        f"# Changes for {record.id}",
        "",
    ]
    if not any((status, diff_stat, diff_names)):
        lines.extend(
            [
                "## Reviewer Memory Cross-Checks",
                "",
                *(
                    [f"- {item}" for item in record.memory_guidance.reviewer]
                    or ["- No reviewer memory checklist was available for this run."]
                ),
                "",
                "No Git diff metadata was available.",
                "",
                "Possible reasons:",
                "- the project is not a Git repository",
                "- there were no tracked changes after execution",
                "",
            ]
        )
        Path(record.changes_path).write_text("\n".join(lines), encoding="utf-8")
        return "No Git change summary was available after execution."

    lines.extend(
        [
            "## Reviewer Memory Cross-Checks",
            "",
            *(
                [f"- {item}" for item in record.memory_guidance.reviewer]
                or ["- No reviewer memory checklist was available for this run."]
            ),
            "",
            "## git status --short",
            "",
            "```text",
            status or "(empty)",
            "```",
            "",
            "## git diff --stat",
            "",
            "```text",
            diff_stat or "(empty)",
            "```",
            "",
            "## Changed Files",
            "",
            *(f"- {name}" for name in diff_names.splitlines() if name.strip()),
            "",
        ]
    )
    Path(record.changes_path).write_text("\n".join(lines), encoding="utf-8")

    changed_files = [name for name in diff_names.splitlines() if name.strip()]
    if changed_files:
        return (
            f"Recorded Git change details for {len(changed_files)} changed file(s) "
            f"and applied {len(record.memory_guidance.reviewer)} reviewer memory cross-check(s)."
        )
    return "Recorded Git change details, but no changed file list was returned."


def _step_summary_lines(record: WorkflowRunRecord) -> list[str]:
    lines: list[str] = []
    for step_run in record.step_runs:
        line = f"- `{step_run.step_id}` `{step_run.status}`"
        if step_run.summary:
            line = f"{line}: {step_run.summary}"
        lines.append(line)
    return lines


def write_report(record: WorkflowRunRecord) -> str:
    last_message = ""
    if record.last_message_path:
        last_message_path = Path(record.last_message_path)
        if last_message_path.exists():
            last_message = last_message_path.read_text(encoding="utf-8").strip()

    changes_text = Path(record.changes_path).read_text(encoding="utf-8") if Path(record.changes_path).exists() else ""
    report_lines = [
        f"# Workflow Run {record.id}",
        "",
        f"Project: `{record.project_path}`",
        f"Status: `{record.status}`",
        f"Attempt count: `{record.attempt_count}`",
        f"Created at: `{record.created_at}`",
    ]
    if record.started_at:
        report_lines.append(f"Started at: `{record.started_at}`")
    if record.completed_at:
        report_lines.append(f"Completed at: `{record.completed_at}`")
    if record.cancel_requested_at:
        report_lines.append(f"Cancel requested at: `{record.cancel_requested_at}`")
    if record.cancelled_at:
        report_lines.append(f"Cancelled at: `{record.cancelled_at}`")
    report_lines.extend(
        [
            "",
            "## Task",
            "",
            record.task,
            "",
            "## Step Outcomes",
            "",
            *_step_summary_lines(record),
            "",
            "## Memory Recall",
            "",
            *(
                [f"- project: {entry.title} -> {entry.summary}" for entry in record.memory_context.recalled_project]
                or ["- No project memory recalled."]
            ),
            *(
                [f"- global: {entry.title} -> {entry.summary}" for entry in record.memory_context.recalled_global]
                or ["- No global memory recalled."]
            ),
            "",
            "## Planner Memory Guidance",
            "",
            *([f"- {item}" for item in record.memory_guidance.planner] or ["- No planner memory guidance was generated."]),
            "",
            "## Codex Final Message",
            "",
            last_message or "_No final Codex message was captured._",
            "",
            "## Change Summary",
            "",
            changes_text or "_No change summary available._",
            "",
            "## Reviewer Memory Checklist",
            "",
            *([f"- {item}" for item in record.memory_guidance.reviewer] or ["- No reviewer checklist was generated."]),
            "",
            "## Reporter Handoff Priorities",
            "",
            *([f"- {item}" for item in record.memory_guidance.reporter] or ["- No reporter priorities were generated."]),
            "",
            "## Memory Writes",
            "",
            *(
                [f"- project: {entry.title} -> {entry.summary}" for entry in record.memory_context.written_project]
                or ["- No project memory written yet."]
            ),
            *(
                [f"- global: {entry.title} -> {entry.summary}" for entry in record.memory_context.written_global]
                or ["- No global memory written yet."]
            ),
            "",
            "## Promoted Global Rules",
            "",
            *(
                [f"- {entry.title} -> {entry.summary}" for entry in record.memory_context.written_global if entry.entry_kind == "global_rule"]
                or ["- No reusable global rule was promoted from this run."]
            ),
            "",
            "## Warnings",
            "",
            *[f"- {warning}" for warning in record.warnings],
            "",
        ]
    )
    if record.error:
        report_lines.extend(["## Error", "", record.error, ""])

    Path(record.report_path).write_text("\n".join(report_lines), encoding="utf-8")
    return "Updated the final report with step outcomes, changes, and captured Codex output."


def write_parallel_branches_summary(record: WorkflowRunRecord) -> str:
    artifact_path = parallel_branches_path(record)
    parallel_steps = [step_run for step_run in record.step_runs if step_run.execution == "parallel"]
    if not parallel_steps:
        artifact_path.write_text(
            "\n".join(
                [
                    "# Parallel Branches",
                    "",
                    "No parallel branch steps were planned for this run.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return "No parallel branches were present for this run."

    lines = [
        "# Parallel Branches",
        "",
        f"Run: `{record.id}`",
        "",
        "| Step | Status | Summary | Commands |",
        "|------|--------|---------|----------|",
    ]
    for step_run in parallel_steps:
        command_list = "<br>".join(" ".join(preview.argv) for preview in step_run.command_previews) or "-"
        summary = (step_run.summary or "-").replace("|", "/")
        lines.append(f"| `{step_run.step_id}` | `{step_run.status}` | {summary} | {command_list} |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Parallel branch steps can be claimed by different workers.",
            "- Failed branches still flow into review/report, so the final run may fail after artifacts are written.",
            "",
        ]
    )
    artifact_path.write_text("\n".join(lines), encoding="utf-8")
    return f"Wrote a parallel branch summary covering {len(parallel_steps)} branch step(s)."


def _artifact_text(path: Path | None) -> tuple[bool, str]:
    if path is None or not path.exists():
        return False, ""
    return True, path.read_text(encoding="utf-8")


def _artifact_documents(record: WorkflowRunRecord) -> list[WorkflowArtifactDocument]:
    Path(record.run_path).mkdir(parents=True, exist_ok=True)
    snapshot_path = project_snapshot_path(record)
    branch_summary_path = parallel_branches_path(record)
    memory_context_path = Path(record.run_path) / "memory-context.md"
    memory_context_path.write_text(memory_context_markdown(record), encoding="utf-8")
    write_parallel_branches_summary(record)
    document_specs = [
        ("planning_brief", "Planning brief", planning_brief_path(record), "markdown"),
        ("report", "Final report", Path(record.report_path), "markdown"),
        ("changes", "Change summary", Path(record.changes_path), "markdown"),
        ("last_message", "Codex final message", Path(record.last_message_path) if record.last_message_path else None, "text"),
        ("project_snapshot", "Research snapshot", snapshot_path, "markdown"),
        ("verification_brief", "Verification brief", verification_brief_path(record), "markdown"),
        ("parallel_branches", "Parallel branches", branch_summary_path, "markdown"),
        ("memory_context", "Workflow memory", memory_context_path, "markdown"),
    ]

    documents: list[WorkflowArtifactDocument] = []
    for key, title, path, content_type in document_specs:
        available, content = _artifact_text(path)
        documents.append(
            WorkflowArtifactDocument(
                key=key,
                title=title,
                path=str(path) if path else None,
                content_type=content_type,  # type: ignore[arg-type]
                available=available,
                content=content,
            )
        )
    return documents


def read_run_artifacts(record: WorkflowRunRecord) -> WorkflowRunArtifactsResponse:
    return WorkflowRunArtifactsResponse(run_id=record.id, documents=_artifact_documents(record))
