from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.models.dto import AgentCard, WorkflowPlanRequest, WorkflowPlanResponse, WorkflowStep


def _task_lower(task: str) -> str:
    return task.strip().lower()


def _needs_research(task: str) -> bool:
    keywords = {"investigate", "debug", "analyze", "compare", "research", "design", "plan"}
    return any(keyword in task for keyword in keywords)


def _needs_parallel_checks(task: str) -> bool:
    keywords = {"test", "benchmark", "compare", "regression", "multi", "matrix"}
    return any(keyword in task for keyword in keywords)


def _build_agents(task: str) -> list[AgentCard]:
    agents = [
        AgentCard(
            name="Planner",
            role="planner",
            reason="Translates the task into a strict workflow and chooses serial or parallel paths.",
        ),
    ]
    if _needs_research(task):
        agents.append(
            AgentCard(
                name="Researcher",
                role="researcher",
                reason="Inspects code, docs, and local context before implementation begins.",
            )
        )
    agents.extend(
        [
            AgentCard(
                name="Coder",
                role="coder",
                reason="Edits files directly and produces the primary implementation.",
            ),
            AgentCard(
                name="Runner",
                role="runner/tester",
                reason="Runs tests, experiments, installs, and command-line checks under policy control.",
            ),
            AgentCard(
                name="Reviewer",
                role="reviewer",
                reason="Checks for regressions, missing edge cases, and workflow completeness.",
            ),
            AgentCard(
                name="Summarizer",
                role="summarizer",
                reason="Produces the final report, artifact summary, and reproducibility notes.",
            ),
        ]
    )
    return agents


def _build_steps(task: str, confirm_dangerous: bool) -> list[WorkflowStep]:
    parallel_checks = _needs_parallel_checks(task)
    steps = [
        WorkflowStep(
            id="plan",
            title="Plan the run",
            agent_role="planner",
            execution="serial",
            goal="Break the request into explicit stages, approvals, and artifact expectations.",
        )
    ]
    if _needs_research(task):
        steps.append(
            WorkflowStep(
                id="research",
                title="Inspect code and context",
                agent_role="researcher",
                execution="serial",
                goal="Collect enough context to avoid blind edits and identify the likely execution path.",
            )
        )
    steps.append(
        WorkflowStep(
            id="implement",
            title="Edit files directly",
            agent_role="coder",
            execution="serial",
            goal="Make the requested code changes in the target project.",
        )
    )
    steps.append(
        WorkflowStep(
            id="verify",
            title="Run checks and experiments",
            agent_role="runner/tester",
            execution="parallel" if parallel_checks else "serial",
            goal="Run the appropriate tests, scripts, or experiment commands for the task.",
            requires_confirmation=confirm_dangerous,
        )
    )
    steps.append(
        WorkflowStep(
            id="review",
            title="Review the result",
            agent_role="reviewer",
            execution="serial",
            goal="Inspect output quality, regressions, and missing edge cases before final handoff.",
        )
    )
    steps.append(
        WorkflowStep(
            id="report",
            title="Produce handoff report",
            agent_role="summarizer",
            execution="serial",
            goal="Summarize changes, results, follow-ups, and reproducible commands without auto-committing Git.",
        )
    )
    return steps


def build_workflow_plan(request: WorkflowPlanRequest, settings: Settings) -> WorkflowPlanResponse:
    task = _task_lower(request.task)
    project_name = Path(request.project_path).name if request.project_path else "workspace"
    allow_network = settings.default_allow_network if request.allow_network is None else request.allow_network
    allow_installs = settings.default_allow_installs if request.allow_installs is None else request.allow_installs
    team_name = f"{project_name}-task-force"
    warnings = [
        "Codex session continuation is still treated as an adapter-level capability and may depend on CLI behavior.",
        "Dangerous commands should require explicit confirmation before execution.",
        "Workflow output should stop at file changes and reports. Git commit and push stay manual in V1.",
    ]

    if not allow_network:
        warnings.append("Network access is disabled for this draft, so remote search and package fetches should be skipped.")
    if not allow_installs:
        warnings.append("Package installation is disabled for this draft, so dependency fixes must avoid install steps.")

    return WorkflowPlanResponse(
        team_name=team_name,
        summary=(
            "A strict multi-agent workflow optimized for code tasks. "
            "The planner owns sequencing, the coder edits files, the runner verifies, "
            "the reviewer checks risk, and the summarizer closes the loop."
        ),
        project_path=request.project_path,
        allow_network=allow_network,
        allow_installs=allow_installs,
        command_policy="dangerous-commands-confirmed",
        agents=_build_agents(task),
        steps=_build_steps(task, confirm_dangerous=settings.default_confirm_dangerous_commands),
        outputs=[
            "direct file changes",
            "verification logs",
            "task report",
            "conversation notes",
            "reproducible command list",
        ],
        warnings=warnings,
    )
