from __future__ import annotations

import subprocess
from pathlib import Path

from app.models.dto import (
    ContractMemorySummary,
    FinalStateContract,
    FinalStateStepOutcomeContract,
    ResearchResultContract,
    ReviewResultContract,
    VerifyCommandResultContract,
    VerifySummaryContract,
    WorkflowDeltaScope,
    WorkflowRunRecord,
)
from app.services.workflow_artifact_paths import (
    changed_diff_path,
    final_state_path,
    project_snapshot_path,
    research_result_path,
    review_result_path,
    verify_summary_path,
    verification_brief_path,
)
from app.services.workflow_run_store import trim_summary, write_json

MAX_VERIFICATION_OUTPUT_EXCERPT = 600


def _contract_memory_summary(scope: str, title: str, summary: str, created_at: str | None = None) -> ContractMemorySummary:
    return ContractMemorySummary(scope=scope, title=title, summary=summary, created_at=created_at)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _bullet_lines(items: list[str], empty_line: str) -> list[str]:
    if not items:
        return [empty_line]
    return [f"- {item}" for item in items]


def build_local_research_result_contract(
    record: WorkflowRunRecord,
    *,
    top_level_entries: list[str],
    decision: str = "continue",
    matched_run_id: str | None = None,
    confidence: float = 0.0,
    reason: str = "",
    delta_hint: str = "",
    delta_scope: WorkflowDeltaScope | None = None,
    relevant_hotspots: list[str] | None = None,
) -> ResearchResultContract:
    continuity_notes = [
        entry.summary
        for entry in [*record.memory_context.recalled_project, *record.memory_context.recalled_global][:3]
    ]
    suggested_next = [
        "Inspect task-relevant files before editing.",
        "Carry forward recalled memory summaries while validating the current repo state.",
    ]
    summary = f"Captured a top-level project snapshot with {len(top_level_entries)} visible entries."
    if decision == "stop_as_duplicate":
        summary = f"Research matched this task to `{matched_run_id}` and recommends stopping as a duplicate."
    elif decision == "stop_as_already_satisfied":
        summary = "Research concluded the current project state already satisfies this task."
    elif decision == "continue_with_delta":
        summary = "Research found that most prior work still applies and suggests continuing with a narrowed delta."
    return ResearchResultContract(
        decision=decision,  # type: ignore[arg-type]
        matched_run_id=matched_run_id,
        confidence=confidence,
        reason=reason,
        delta_hint=delta_hint,
        delta_scope=delta_scope,
        run_id=record.id,
        task=record.task,
        project_root=record.project_path,
        top_level_entries=top_level_entries,
        relevant_hotspots=relevant_hotspots or top_level_entries[:10],
        continuity_notes=continuity_notes,
        suggested_next_attention_areas=suggested_next,
        summary=summary,
    )


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


def write_research_result_contract(record: WorkflowRunRecord, contract: ResearchResultContract) -> None:
    write_json(research_result_path(record), contract.model_dump(mode="json"))
    lines = [
        "# Project Snapshot",
        "",
        f"Project root: `{contract.project_root}`",
        "",
        "## Reuse Decision",
        "",
        *_bullet_lines(
            [
                f"Decision: `{contract.decision}`",
                f"Matched run: `{contract.matched_run_id}`" if contract.matched_run_id else "Matched run: none",
                f"Confidence: `{contract.confidence}`",
                f"Reason: {contract.reason}" if contract.reason else "Reason: none recorded",
                f"Delta hint: {contract.delta_hint}" if contract.delta_hint else "Delta hint: none",
                (
                    "Verification focus: "
                    f"`{contract.delta_scope.verification_focus}`"
                    if contract.delta_scope is not None
                    else "Verification focus: none"
                ),
            ],
            "No reuse decision recorded.",
        ),
        "",
        "## Delta Scope",
        "",
        *(
            [
                f"- Focus paths: {', '.join(contract.delta_scope.focus_paths)}" if contract.delta_scope.focus_paths else "- Focus paths: none",
                (
                    f"- Matched-run changed files: {', '.join(contract.delta_scope.matched_run_changed_files)}"
                    if contract.delta_scope.matched_run_changed_files
                    else "- Matched-run changed files: none"
                ),
                (
                    f"- Current diff files: {', '.join(contract.delta_scope.current_diff_files)}"
                    if contract.delta_scope.current_diff_files
                    else "- Current diff files: none"
                ),
                f"- Scope summary: {contract.delta_scope.scope_summary}" if contract.delta_scope.scope_summary else "- Scope summary: none",
            ]
            if contract.delta_scope is not None
            else ["No delta scope was recorded."]
        ),
        "",
        "## Top-level entries",
        "",
        *_bullet_lines(contract.top_level_entries, "No visible entries found."),
        "",
        "## Relevant Hotspots",
        "",
        *_bullet_lines(contract.relevant_hotspots, "No hotspots were highlighted."),
        "",
        "## Continuity Notes",
        "",
        *_bullet_lines(contract.continuity_notes, "No continuity notes were captured."),
        "",
        "## Suggested Next Attention Areas",
        "",
        *_bullet_lines(contract.suggested_next_attention_areas, "No follow-up areas were suggested."),
        "",
    ]
    _write_text(project_snapshot_path(record), "\n".join(lines))


def load_research_result_contract(record: WorkflowRunRecord) -> ResearchResultContract | None:
    path = research_result_path(record)
    if not path.exists():
        return None
    return ResearchResultContract.model_validate_json(path.read_text(encoding="utf-8"))


def write_verify_summary_contract(record: WorkflowRunRecord, contract: VerifySummaryContract) -> None:
    write_json(verify_summary_path(record), contract.model_dump(mode="json"))
    lines = [
        f"# Verification Brief for {record.id}",
        "",
        "## Executed Commands",
        "",
    ]
    if contract.executed_commands:
        for command in contract.executed_commands:
            line = f"- {command.label}: `{command.status}`"
            if command.exit_code is not None:
                line = f"{line} (exit {command.exit_code})"
            lines.append(line)
            if command.output_excerpt:
                lines.extend(["", "```text", command.output_excerpt, "```", ""])
    else:
        lines.append("- No verification commands were detected.")
    lines.extend(
        [
            "",
            "## Result Summary",
            "",
            contract.result_summary,
            "",
            "## Validation Risks",
            "",
            *_bullet_lines(contract.validation_risks, "No validation risks were recorded."),
            "",
            "## Follow-up Checks",
            "",
            *_bullet_lines(contract.follow_up_checks, "No follow-up checks were recorded."),
            "",
        ]
    )
    _write_text(verification_brief_path(record), "\n".join(lines))


def load_verify_summary_contract(record: WorkflowRunRecord) -> VerifySummaryContract | None:
    path = verify_summary_path(record)
    if not path.exists():
        return None
    return VerifySummaryContract.model_validate_json(path.read_text(encoding="utf-8"))


def build_local_verify_summary_contract(
    record: WorkflowRunRecord,
    *,
    step_id: str,
    commands: list[VerifyCommandResultContract],
    result_summary: str,
    validation_risks: list[str] | None = None,
    follow_up_checks: list[str] | None = None,
) -> VerifySummaryContract:
    return VerifySummaryContract(
        run_id=record.id,
        step_id=step_id,
        task=record.task,
        executed_commands=commands,
        result_summary=result_summary,
        validation_risks=validation_risks or [],
        follow_up_checks=follow_up_checks or list(record.memory_guidance.reviewer),
        summary=result_summary,
    )


def write_review_result_contract(record: WorkflowRunRecord, contract: ReviewResultContract) -> None:
    write_json(review_result_path(record), contract.model_dump(mode="json"))
    lines = [
        f"# Changes for {record.id}",
        "",
        "## Reviewer Memory Cross-Checks",
        "",
        *_bullet_lines(contract.reviewer_memory_cross_checks, "No reviewer memory checklist was available for this run."),
        "",
        "## Changed Files",
        "",
        *_bullet_lines(contract.changed_files, "No changed files were detected."),
        "",
        "## Risk Assessment",
        "",
        *_bullet_lines(contract.risk_assessment, "No risks were recorded."),
        "",
        "## Open Questions",
        "",
        *_bullet_lines(contract.open_questions, "No open questions were captured."),
        "",
    ]
    if contract.git_status_excerpt:
        lines.extend(["## git status --short", "", "```text", contract.git_status_excerpt, "```", ""])
    if contract.diff_stat_excerpt:
        lines.extend(["## git diff --stat", "", "```text", contract.diff_stat_excerpt, "```", ""])
    _write_text(Path(record.changes_path), "\n".join(lines))


def load_review_result_contract(record: WorkflowRunRecord) -> ReviewResultContract | None:
    path = review_result_path(record)
    if not path.exists():
        return None
    return ReviewResultContract.model_validate_json(path.read_text(encoding="utf-8"))


def build_local_review_result_contract(record: WorkflowRunRecord) -> ReviewResultContract:
    status = _git_capture(record.project_path, ["status", "--short"])
    diff_stat = _git_capture(record.project_path, ["diff", "--stat"])
    diff_names = _git_capture(record.project_path, ["diff", "--name-only"])
    changed_files = [name for name in diff_names.splitlines() if name.strip()]
    if not any((status, diff_stat, diff_names)):
        return ReviewResultContract(
            run_id=record.id,
            task=record.task,
            reviewer_memory_cross_checks=list(record.memory_guidance.reviewer),
            changed_files=[],
            risk_assessment=[
                "No Git diff metadata was available.",
                "The project may not be a Git repository or there were no tracked changes after execution.",
            ],
            open_questions=[],
            git_status_excerpt=None,
            diff_stat_excerpt=None,
            summary="No Git change summary was available after execution.",
        )
    return ReviewResultContract(
        run_id=record.id,
        task=record.task,
        reviewer_memory_cross_checks=list(record.memory_guidance.reviewer),
        changed_files=changed_files,
        risk_assessment=[] if changed_files else ["Git reported metadata, but no changed file list was returned."],
        open_questions=[],
        git_status_excerpt=status or None,
        diff_stat_excerpt=diff_stat or None,
        summary=(
            f"Recorded Git change details for {len(changed_files)} changed file(s) and applied "
            f"{len(record.memory_guidance.reviewer)} reviewer memory cross-check(s)."
            if changed_files
            else "Recorded Git change details, but no changed file list was returned."
        ),
    )


def build_final_state_contract(record: WorkflowRunRecord) -> FinalStateContract:
    last_message = _read_text(Path(record.last_message_path)) if record.last_message_path else ""
    review_contract = load_review_result_contract(record)
    recall = [
        _contract_memory_summary(entry.scope, entry.title, entry.summary, entry.created_at)
        for entry in [*record.memory_context.recalled_project, *record.memory_context.recalled_global]
    ]
    writes = [
        _contract_memory_summary(entry.scope, entry.title, entry.summary, entry.created_at)
        for entry in [*record.memory_context.written_project, *record.memory_context.written_global]
    ]
    promoted_rules = [
        entry.title for entry in record.memory_context.written_global if entry.entry_kind == "global_rule"
    ]
    return FinalStateContract(
        run_id=record.id,
        task=record.task,
        status=record.status,
        attempt_count=record.attempt_count,
        reuse_decision=record.reuse_decision,
        matched_run_id=record.matched_run_id,
        reuse_reason=record.reuse_reason,
        reuse_confidence=record.reuse_confidence,
        delta_hint=record.delta_hint,
        delta_scope=record.delta_scope,
        step_outcomes=[
            FinalStateStepOutcomeContract(
                step_id=step_run.step_id,
                title=step_run.title,
                status=step_run.status,
                summary=trim_summary(step_run.summary, limit=240),
            )
            for step_run in record.step_runs
        ],
        memory_recall=recall,
        codex_final_message=last_message or None,
        change_summary_excerpt=review_contract.summary if review_contract else trim_summary(_read_text(Path(record.changes_path)), limit=500),
        memory_writes=writes,
        promoted_global_rules=promoted_rules,
        warnings=list(record.warnings),
        summary=trim_summary(
            f"Workflow {record.id} resolved with status {record.status}. "
            f"Recorded {len(record.step_runs)} step outcome(s) and {len(writes)} memory write(s).",
            limit=220,
        )
        or f"Workflow {record.id} final state captured.",
    )


def write_final_state_contract(record: WorkflowRunRecord, contract: FinalStateContract) -> None:
    write_json(final_state_path(record), contract.model_dump(mode="json"))
    lines = [
        f"# Workflow Run {contract.run_id}",
        "",
        f"Project: `{record.project_path}`",
        f"Status: `{contract.status}`",
        f"Attempt count: `{contract.attempt_count}`",
        f"Created at: `{record.created_at}`",
    ]
    if record.started_at:
        lines.append(f"Started at: `{record.started_at}`")
    if record.completed_at:
        lines.append(f"Completed at: `{record.completed_at}`")
    if record.cancel_requested_at:
        lines.append(f"Cancel requested at: `{record.cancel_requested_at}`")
    if record.cancelled_at:
        lines.append(f"Cancelled at: `{record.cancelled_at}`")
    lines.extend(
        [
            "",
            "## Task",
            "",
            contract.task,
            "",
            "## Reuse Decision",
            "",
            *(
                [
                    f"- Decision: `{contract.reuse_decision}`",
                    f"- Matched run: `{contract.matched_run_id}`" if contract.matched_run_id else "- Matched run: none",
                    f"- Confidence: `{contract.reuse_confidence}`" if contract.reuse_confidence is not None else "- Confidence: unknown",
                    f"- Reason: {contract.reuse_reason}" if contract.reuse_reason else "- Reason: none recorded",
                    f"- Delta hint: {contract.delta_hint}" if contract.delta_hint else "- Delta hint: none",
                    (
                        f"- Verification focus: `{contract.delta_scope.verification_focus}`"
                        if contract.delta_scope is not None
                        else "- Verification focus: none"
                    ),
                ]
                if contract.reuse_decision
                else ["- No reuse decision recorded."]
            ),
            "",
            "## Delta Scope",
            "",
            *(
                [
                    f"- Focus paths: {', '.join(contract.delta_scope.focus_paths)}" if contract.delta_scope.focus_paths else "- Focus paths: none",
                    (
                        f"- Matched-run changed files: {', '.join(contract.delta_scope.matched_run_changed_files)}"
                        if contract.delta_scope.matched_run_changed_files
                        else "- Matched-run changed files: none"
                    ),
                    (
                        f"- Current diff files: {', '.join(contract.delta_scope.current_diff_files)}"
                        if contract.delta_scope.current_diff_files
                        else "- Current diff files: none"
                    ),
                    f"- Scope summary: {contract.delta_scope.scope_summary}" if contract.delta_scope.scope_summary else "- Scope summary: none",
                ]
                if contract.delta_scope is not None
                else ["No delta scope was recorded."]
            ),
            "",
            "## Step Outcomes",
            "",
            *(
                f"- `{item.step_id}` `{item.status}`: {item.summary}"
                if item.summary
                else f"- `{item.step_id}` `{item.status}`"
                for item in contract.step_outcomes
            ),
            "",
            "## Memory Recall",
            "",
            *_bullet_lines(
                [f"{item.scope}: {item.title} -> {item.summary}" for item in contract.memory_recall],
                "No project memory recalled.",
            ),
            "",
            "## Codex Final Message",
            "",
            contract.codex_final_message or "_No final Codex message was captured._",
            "",
            "## Change Summary",
            "",
            contract.change_summary_excerpt or "_No change summary available._",
            "",
            "## Memory Writes",
            "",
            *_bullet_lines(
                [f"{item.scope}: {item.title} -> {item.summary}" for item in contract.memory_writes],
                "No project memory written yet.",
            ),
            "",
            "## Promoted Global Rules",
            "",
            *_bullet_lines(contract.promoted_global_rules, "No reusable global rule was promoted from this run."),
            "",
            "## Warnings",
            "",
            *_bullet_lines(contract.warnings, "No warnings were recorded."),
            "",
        ]
    )
    if record.error:
        lines.extend(["## Error", "", record.error, ""])
    _write_text(Path(record.report_path), "\n".join(lines))


def load_final_state_contract(record: WorkflowRunRecord) -> FinalStateContract | None:
    path = final_state_path(record)
    if not path.exists():
        return None
    return FinalStateContract.model_validate_json(path.read_text(encoding="utf-8"))


def persist_changed_diff(record: WorkflowRunRecord, diff_text: str) -> None:
    _write_text(changed_diff_path(record), diff_text)
