from __future__ import annotations

from dataclasses import dataclass

from app.services.workflow_backend_registry import step_family

FORBIDDEN_CONTEXT_GLOBS: tuple[str, ...] = (
    ".agents-team/**/execution.log",
    ".agents-team/**/memory/*.json",
    ".agents-team/**/reports/*.md",
    ".agents-team/**/runs/*/report.md",
    ".agents-team/**/runs/*/last-message.md",
)

FORBIDDEN_SOURCE_MARKERS: tuple[str, ...] = (
    ".agents-team",
    "execution.log",
    "project-memory.json",
    "global-memory.json",
    "last-message.md",
    "memory-context.md",
    "/reports/",
    "\\reports\\",
)

PROJECT_PROJECTION_EXCLUDES: tuple[str, ...] = (
    ".agents-team",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
)


@dataclass(frozen=True)
class ContextPolicy:
    family: str
    allow_source_projection: bool
    source_keys: tuple[str, ...]
    forbidden_globs: tuple[str, ...] = FORBIDDEN_CONTEXT_GLOBS


POLICIES: dict[str, ContextPolicy] = {
    "plan": ContextPolicy(
        family="plan",
        allow_source_projection=False,
        source_keys=("project_summary", "run_state", "step_context", "selected_memory"),
    ),
    "research": ContextPolicy(
        family="research",
        allow_source_projection=False,
        source_keys=("repo_snapshot", "run_state", "step_context", "selected_memory", "recent_runs"),
    ),
    "implement": ContextPolicy(
        family="implement",
        allow_source_projection=True,
        source_keys=("run_state", "step_context", "selected_memory", "upstream_handoff"),
    ),
    "verify": ContextPolicy(
        family="verify",
        allow_source_projection=True,
        source_keys=("run_state", "step_context", "selected_memory", "upstream_handoff", "changed_diff"),
    ),
    "review": ContextPolicy(
        family="review",
        allow_source_projection=False,
        source_keys=("run_state", "step_context", "changed_diff", "verify_summary"),
    ),
    "report": ContextPolicy(
        family="report",
        allow_source_projection=False,
        source_keys=("run_state", "step_context", "final_state"),
    ),
}


def context_policy_for_step(step_id: str) -> ContextPolicy:
    return POLICIES.get(step_family(step_id), POLICIES["plan"])
