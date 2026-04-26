from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.models.dto import MemoryEntry, WorkflowMemoryContext, WorkflowRoleMemoryGuidance, WorkflowRunRecord, WorkflowStepRun
from app.services.runtime import project_runtime_path, resolve_project_path
from app.services.workflow_backend_registry import step_family
from app.services.workflow_run_store import load_json, now_iso, trim_summary, write_json

MAX_RECALLED_ENTRIES = 3
MAX_GLOBAL_RULES = 5
STOPWORDS = {
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
    "global",
    "memory",
    "review",
    "generate",
    "implement",
}
def _memory_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_memory_path(project_path: Path) -> Path:
    return _memory_dir(project_runtime_path(project_path) / "memory") / "project-memory.json"


def global_memory_path(settings: Settings) -> Path:
    return _memory_dir(settings.agents_team_home / "memory") / "global-memory.json"


def _load_entries(path: Path) -> list[MemoryEntry]:
    if not path.exists():
        return []
    try:
        payload = load_json(path)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(payload, list):
        return []
    entries: list[MemoryEntry] = []
    for item in payload:
        if isinstance(item, dict):
            try:
                entries.append(MemoryEntry.model_validate(item))
            except Exception:  # noqa: BLE001
                continue
    return entries


def _save_entries(path: Path, entries: list[MemoryEntry]) -> None:
    write_json(path, [entry.model_dump(mode="json") for entry in entries])


def _append_entry(path: Path, entry: MemoryEntry, *, limit: int) -> None:
    entries = _load_entries(path)
    entries.append(entry)
    _save_entries(path, entries[-limit:])


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_]{3,}", text.lower())
    return [token for token in tokens if token not in STOPWORDS]


def _recall_entries(entries: list[MemoryEntry], task: str) -> list[MemoryEntry]:
    task_tokens = set(_tokenize(task))
    if not entries:
        return []

    def score(entry: MemoryEntry) -> tuple[int, str]:
        haystack = " ".join([entry.title, entry.summary, entry.details, *entry.tags]).lower()
        overlap = len(task_tokens.intersection(_tokenize(haystack)))
        return overlap, entry.created_at

    ranked = sorted(entries, key=score, reverse=True)
    recalled = [entry for entry in ranked if score(entry)[0] > 0][:MAX_RECALLED_ENTRIES]
    if recalled:
        return recalled
    return ranked[:MAX_RECALLED_ENTRIES]


def build_memory_context(project_path_str: str, task: str, settings: Settings, *, global_enabled: bool) -> WorkflowMemoryContext:
    project_path = resolve_project_path(project_path_str)
    project_path_memory = project_memory_path(project_path)
    global_path_memory = global_memory_path(settings) if global_enabled else None

    project_entries = _load_entries(project_path_memory)
    global_entries = _load_entries(global_path_memory) if global_path_memory else []

    recalled_project = _recall_entries(project_entries, task)[:MAX_RECALLED_ENTRIES]
    remaining_global_slots = max(0, MAX_RECALLED_ENTRIES - len(recalled_project))
    recalled_global = (
        _recall_entries(global_entries, task)[:remaining_global_slots]
        if global_enabled and remaining_global_slots
        else []
    )

    return WorkflowMemoryContext(
        project_memory_path=str(project_path_memory),
        global_memory_path=str(global_path_memory) if global_path_memory else None,
        recalled_project=recalled_project,
        recalled_global=recalled_global,
        written_project=[],
        written_global=[],
    )


def build_role_memory_guidance(
    memory_context: WorkflowMemoryContext,
    locale: str | None = None,
) -> WorkflowRoleMemoryGuidance:
    use_zh = locale == "zh-CN"
    recalled_entries = [*memory_context.recalled_project, *memory_context.recalled_global]
    if not recalled_entries:
        return WorkflowRoleMemoryGuidance(
            planner=[
                "这次没有召回历史记忆，所以请把关键假设、未知项和取舍条件直接写清楚。"
                if use_zh
                else "No prior memory was recalled, so surface assumptions and unknowns explicitly in the plan."
            ],
            reviewer=[
                "这次没有召回历史记忆，所以重点检查回归风险、验证覆盖和遗漏的边界情况。"
                if use_zh
                else "No prior memory was recalled, so focus on regressions, verification coverage, and missing edge cases."
            ],
            reporter=[
                "这次没有召回历史记忆，所以请写出一份新的交接说明，方便后续运行直接复用。"
                if use_zh
                else "No prior memory was recalled, so write a fresh handoff that future runs can reuse directly."
            ],
        )

    planner: list[str] = []
    reviewer: list[str] = []
    reporter: list[str] = []
    for entry in recalled_entries[:MAX_RECALLED_ENTRIES]:
        scope = entry.scope
        if entry.entry_kind == "global_rule":
            if use_zh:
                planner.append(f"沿用可复用的全局规则“{entry.title}”：{entry.summary}")
                reviewer.append(f"检查回归和边界情况时，确认可复用全局规则“{entry.title}”是否被遵守。")
                reporter.append(f"在交接里说明这次运行是延续、修正，还是替换了全局规则“{entry.title}”。")
            else:
                planner.append(f"Apply reusable global rule `{entry.title}`: {entry.summary}")
                reviewer.append(f"Enforce reusable global rule `{entry.title}` while checking regressions and edge cases.")
                reporter.append(f"State whether this run upheld, refined, or superseded reusable global rule `{entry.title}`.")
            continue
        if use_zh:
            scope_label = "项目" if scope == "project" else "全局"
            planner.append(f"延续{scope_label}记忆“{entry.title}”：{entry.summary}")
            reviewer.append(f"收尾前请对照{scope_label}记忆“{entry.title}”，确认结果没有偏离。")
            reporter.append(f"在交接里说明这次运行是确认、更新，还是替换了{scope_label}记忆“{entry.title}”。")
        else:
            planner.append(f"Carry forward {scope} memory `{entry.title}`: {entry.summary}")
            reviewer.append(f"Cross-check the outcome against {scope} memory `{entry.title}` before closing the run.")
            reporter.append(f"State whether this run confirms, updates, or supersedes {scope} memory `{entry.title}`.")

    return WorkflowRoleMemoryGuidance(planner=planner, reviewer=reviewer, reporter=reporter)


def _format_step_summaries(record: WorkflowRunRecord) -> str:
    lines = []
    for step in record.step_runs:
        summary = step.summary or "No summary captured."
        lines.append(f"- {step.step_id} [{step.status}]: {summary}")
    return "\n".join(lines)


def _changes_excerpt(record: WorkflowRunRecord) -> str:
    changes_path = Path(record.changes_path)
    if not changes_path.exists():
        return "No change summary was captured."
    text = changes_path.read_text(encoding="utf-8").strip()
    return trim_summary(text, limit=700) or "No change summary was captured."


def _last_message_excerpt(record: WorkflowRunRecord) -> str:
    if not record.last_message_path:
        return "No final Codex message was captured."
    last_message_path = Path(record.last_message_path)
    if not last_message_path.exists():
        return "No final Codex message was captured."
    return trim_summary(last_message_path.read_text(encoding="utf-8").strip(), limit=700) or "No final Codex message was captured."


def _memory_entry(scope: str, record: WorkflowRunRecord) -> MemoryEntry:
    title = f"{record.status.title()} workflow for {Path(record.project_path).name}"
    summary = trim_summary(
        f"Task: {record.task}. Status: {record.status}. Key result: {_last_message_excerpt(record)}",
        limit=220,
    ) or f"{record.status.title()} workflow memory"
    details = "\n".join(
        [
            f"Task: {record.task}",
            f"Status: {record.status}",
            f"Attempt: {record.attempt_count}",
            "",
            "Step outcomes:",
            _format_step_summaries(record),
            "",
            "Codex final message:",
            _last_message_excerpt(record),
            "",
            "Change summary excerpt:",
            _changes_excerpt(record),
        ]
    )
    tags = list(dict.fromkeys(_tokenize(" ".join([record.task, record.summary]))))[:8]
    return MemoryEntry(
        id=f"mem-{uuid4().hex[:10]}",
        scope=scope,  # type: ignore[arg-type]
        entry_kind="handoff",
        created_at=now_iso(),
        source_run_id=record.id,
        attempt_count=record.attempt_count,
        title=title,
        summary=summary,
        details=details,
        tags=tags,
    )


def _project_snapshot_excerpt(record: WorkflowRunRecord) -> str:
    snapshot_path = Path(record.run_path) / "project-snapshot.md"
    if not snapshot_path.exists():
        return "No project snapshot artifact was available."
    text = snapshot_path.read_text(encoding="utf-8").strip()
    return trim_summary(text, limit=700) or "No project snapshot artifact was available."


def _log_excerpt(record: WorkflowRunRecord, *, max_lines: int = 60) -> str:
    log_path = Path(record.log_path)
    if not log_path.exists():
        return "No execution log was captured."
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-max_lines:])


def _step_finding_entry(record: WorkflowRunRecord, step_run: WorkflowStepRun) -> MemoryEntry | None:
    family = step_family(step_run.step_id)
    if family not in {"research", "verify"}:
        return None

    if family == "research":
        title = f"Research finding for {Path(record.project_path).name}"
        details = "\n".join(
            [
                f"Task: {record.task}",
                f"Step status: {step_run.status}",
                f"Summary: {step_run.summary or 'No summary captured.'}",
                "",
                "Snapshot excerpt:",
                _project_snapshot_excerpt(record),
            ]
        )
        tags = list(dict.fromkeys(["research", *_tokenize(record.task)]))[:8]
        return MemoryEntry(
            id=f"mem-{uuid4().hex[:10]}",
            scope="project",
            entry_kind="research_finding",
            source_step_id="research",
            step_status=step_run.status if step_run.status in {"completed", "failed"} else None,
            created_at=now_iso(),
            source_run_id=record.id,
            attempt_count=record.attempt_count,
            title=title,
            summary=trim_summary(step_run.summary or "Research completed without a detailed summary.", limit=220)
            or "Research finding captured.",
            details=details,
            tags=tags,
        )

    title = f"Verification finding for {Path(record.project_path).name}"
    details = "\n".join(
        [
            f"Task: {record.task}",
            f"Step status: {step_run.status}",
            f"Summary: {step_run.summary or 'No summary captured.'}",
            "",
            "Verification log excerpt:",
            _log_excerpt(record),
        ]
    )
    tags = list(dict.fromkeys(["verify", *_tokenize(record.task)]))[:8]
    return MemoryEntry(
        id=f"mem-{uuid4().hex[:10]}",
        scope="project",
        entry_kind="verification_finding",
        source_step_id="verify",
        step_status=step_run.status if step_run.status in {"completed", "failed"} else None,
        created_at=now_iso(),
        source_run_id=record.id,
        attempt_count=record.attempt_count,
        title=title,
        summary=trim_summary(step_run.summary or "Verification completed without a detailed summary.", limit=220)
        or "Verification finding captured.",
        details=details,
        tags=tags,
    )


def _should_promote_to_global_rule(finding: MemoryEntry) -> bool:
    return bool(finding.promote_to_global_rule)


def _global_rule_entry(finding: MemoryEntry) -> MemoryEntry:
    title = trim_summary(finding.summary, limit=110) or finding.title
    details = "\n".join(
        [
            f"Promoted from {finding.entry_kind} on step `{finding.source_step_id}`.",
            f"Original project finding: {finding.title}",
            "",
            finding.details,
        ]
    )
    tags = list(dict.fromkeys([*finding.tags, "global_rule", *( [finding.source_step_id] if finding.source_step_id else [] )]))[:10]
    return MemoryEntry(
        id=f"mem-{uuid4().hex[:10]}",
        scope="global",
        entry_kind="global_rule",
        source_step_id=finding.source_step_id,
        step_status=finding.step_status,
        created_at=now_iso(),
        source_run_id=finding.source_run_id,
        attempt_count=finding.attempt_count,
        title=title,
        summary=f"Reusable rule promoted from {finding.entry_kind}: {finding.summary}",
        details=details,
        tags=tags,
    )


def persist_run_memory(record: WorkflowRunRecord, settings: Settings) -> WorkflowMemoryContext:
    project_path = resolve_project_path(record.project_path)
    project_path_memory = project_memory_path(project_path)
    global_path_memory = global_memory_path(settings) if record.memory_context.global_memory_path else None

    updated_context = record.memory_context.model_copy(deep=True)
    project_entry = _memory_entry("project", record)
    _append_entry(project_path_memory, project_entry, limit=50)
    updated_context.written_project = [*updated_context.written_project, project_entry]
    updated_context.project_memory_path = str(project_path_memory)

    if global_path_memory:
        global_entry = _memory_entry("global", record)
        _append_entry(global_path_memory, global_entry, limit=80)
        updated_context.written_global = [*updated_context.written_global, global_entry]
        updated_context.global_memory_path = str(global_path_memory)
    else:
        updated_context.written_global = []
        updated_context.global_memory_path = None

    return updated_context


def persist_step_finding(record: WorkflowRunRecord, step_run: WorkflowStepRun, settings: Settings) -> WorkflowMemoryContext:
    finding = _step_finding_entry(record, step_run)
    if finding is None:
        return record.memory_context

    project_path = resolve_project_path(record.project_path)
    project_path_memory = project_memory_path(project_path)
    _append_entry(project_path_memory, finding, limit=50)

    updated_context = record.memory_context.model_copy(deep=True)
    updated_context.project_memory_path = str(project_path_memory)
    updated_context.written_project = [*updated_context.written_project, finding]

    if updated_context.global_memory_path and _should_promote_to_global_rule(finding):
        global_rule = _global_rule_entry(finding)
        global_path_memory = Path(updated_context.global_memory_path)
        _append_entry(global_path_memory, global_rule, limit=MAX_GLOBAL_RULES + 80)
        updated_context.written_global = [*updated_context.written_global, global_rule]
    return updated_context


def memory_context_markdown(record: WorkflowRunRecord) -> str:
    context = record.memory_context

    def render_entries(entries: list[MemoryEntry]) -> list[str]:
        if not entries:
            return ["- None recalled."]
        rendered: list[str] = []
        for entry in entries:
            suffix = f" [{entry.entry_kind}]"
            if entry.source_step_id:
                suffix = f"{suffix} via `{entry.source_step_id}`"
            rendered.append(f"- `{entry.scope}` {entry.title}{suffix}: {entry.summary}")
        return rendered

    def render_written(entries: list[MemoryEntry]) -> list[str]:
        if not entries:
            return ["- No memory write recorded."]
        rendered: list[str] = []
        for entry in entries:
            suffix = f" [{entry.entry_kind}]"
            if entry.source_step_id:
                suffix = f"{suffix} via `{entry.source_step_id}`"
            rendered.append(f"- `{entry.scope}` {entry.title}{suffix}: {entry.summary}")
        return rendered

    return "\n".join(
        [
            "# Workflow Memory Context",
            "",
            "## Planner Guidance",
            "",
            *([f"- {item}" for item in record.memory_guidance.planner] or ["- No planner guidance generated."]),
            "",
            "## Reviewer Checklist",
            "",
            *([f"- {item}" for item in record.memory_guidance.reviewer] or ["- No reviewer checklist generated."]),
            "",
            "## Reporter Priorities",
            "",
            *([f"- {item}" for item in record.memory_guidance.reporter] or ["- No reporter priorities generated."]),
            "",
            "## Recalled Project Memory",
            "",
            *render_entries(context.recalled_project),
            "",
            "## Recalled Global Memory",
            "",
            *render_entries(context.recalled_global),
            "",
            "## Promoted Global Rules",
            "",
            *render_written([entry for entry in context.written_global if entry.entry_kind == "global_rule"]),
            "",
            "## Written Project Memory",
            "",
            *render_written(context.written_project),
            "",
            "## Written Global Memory",
            "",
            *render_written(context.written_global),
            "",
        ]
    )
