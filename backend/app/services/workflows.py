from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.models.dto import (
    AgentCard,
    WorkflowCommandPreview,
    WorkflowMemoryContext,
    WorkflowPlanRequest,
    WorkflowPlanResponse,
    WorkflowStep,
)
from app.services.runtime import get_project_runtime
from app.services.workflow_backend_registry import backend_for_step
from app.services.workflow_backend_runtime import verification_command_previews
from app.services.workflow_memory import build_memory_context, build_role_memory_guidance
from app.services.workflow_reuse import has_recent_reuse_candidate


def _task_lower(task: str) -> str:
    return task.strip().lower()


def _use_zh(locale: str | None) -> bool:
    return locale == "zh-CN"


def _needs_research(task: str, *, has_memory_context: bool, has_recent_reuse_candidates: bool) -> bool:
    keywords = {
        "investigate",
        "debug",
        "analyze",
        "compare",
        "research",
        "design",
        "plan",
        "排查",
        "调试",
        "分析",
        "比较",
        "调研",
        "设计",
        "规划",
        "梳理",
    }
    return has_memory_context or has_recent_reuse_candidates or any(keyword in task for keyword in keywords)


def _needs_parallel_checks(task: str) -> bool:
    keywords = {
        "test",
        "benchmark",
        "compare",
        "regression",
        "multi",
        "matrix",
        "测试",
        "基准",
        "回归",
        "矩阵",
        "多组",
        "多轮",
        "构建",
    }
    return any(keyword in task for keyword in keywords)


def _build_agents(
    task: str,
    *,
    has_memory_context: bool,
    has_recent_reuse_candidates: bool,
    locale: str | None,
) -> list[AgentCard]:
    use_zh = _use_zh(locale)
    agents = [
        AgentCard(
            name="规划者" if use_zh else "Planner",
            role="planner",
            reason=(
                "把任务拆成明确步骤，并决定哪些环节适合串行、哪些环节适合并行。"
                if use_zh
                else "Translates the task into a strict workflow and chooses serial or parallel paths."
            ),
        )
    ]
    if _needs_research(task, has_memory_context=has_memory_context, has_recent_reuse_candidates=has_recent_reuse_candidates):
        agents.append(
            AgentCard(
                name="调研者" if use_zh else "Researcher",
                role="researcher",
                reason=(
                    "先看清代码、文档和本地上下文，再进入具体实现，避免盲改。"
                    if use_zh
                    else "Inspects code, docs, and local context before implementation begins."
                ),
            )
        )
    agents.extend(
        [
            AgentCard(
                name="实现者" if use_zh else "Coder",
                role="coder",
                reason=(
                    "直接修改文件，完成主要实现。"
                    if use_zh
                    else "Edits files directly and produces the primary implementation."
                ),
            ),
            AgentCard(
                name="验证者" if use_zh else "Runner",
                role="runner/tester",
                reason=(
                    "负责测试、构建、实验和命令校验，确认结果真的可用。"
                    if use_zh
                    else "Runs tests, experiments, installs, and command-line checks under policy control."
                ),
            ),
            AgentCard(
                name="审查者" if use_zh else "Reviewer",
                role="reviewer",
                reason=(
                    "补齐风险检查、边界情况和遗漏点，避免只跑通演示路径。"
                    if use_zh
                    else "Checks for regressions, missing edge cases, and workflow completeness."
                ),
            ),
            AgentCard(
                name="汇总者" if use_zh else "Summarizer",
                role="summarizer",
                reason=(
                    "整理最终交接、结果摘要和复现说明。"
                    if use_zh
                    else "Produces the final report, artifact summary, and reproducibility notes."
                ),
            ),
        ]
    )
    return agents


def _verification_previews(
    project_path_str: str | None,
    *,
    focus: str,
    step_id: str,
    requires_confirmation: bool,
) -> list[WorkflowCommandPreview]:
    if not project_path_str:
        return []
    project_path = Path(project_path_str)
    if not project_path.exists():
        return []
    return verification_command_previews(
        project_path,
        focus=focus,
        step_id=step_id,
        requires_confirmation=requires_confirmation,
    )


def _build_steps(
    task: str,
    confirm_dangerous: bool,
    *,
    has_memory_context: bool,
    has_recent_reuse_candidates: bool,
    project_path_str: str | None,
    locale: str | None,
) -> list[WorkflowStep]:
    use_zh = _use_zh(locale)
    parallel_checks = _needs_parallel_checks(task)
    steps = [
        WorkflowStep(
            id="plan",
            title="规划这次执行" if use_zh else "Plan the run",
            agent_role="planner",
            backend=backend_for_step("plan"),
            execution="serial",
            goal=(
                "把需求拆成明确步骤、审批点、产物预期和上下文延续要点。"
                if has_memory_context and use_zh
                else "把需求拆成明确步骤、审批点和产物预期。"
                if use_zh
                else "Break the request into explicit stages, approvals, artifact expectations, and continuity notes from memory."
                if has_memory_context
                else "Break the request into explicit stages, approvals, and artifact expectations."
            ),
            depends_on=[],
        )
    ]

    implementation_dependency = "plan"
    if _needs_research(task, has_memory_context=has_memory_context, has_recent_reuse_candidates=has_recent_reuse_candidates):
        steps.append(
            WorkflowStep(
                id="research",
                title="检查代码和上下文" if use_zh else "Inspect code and context",
                agent_role="researcher",
                backend=backend_for_step("research"),
                execution="serial",
                goal=(
                    "先补齐必要上下文，验证召回记忆是否仍然成立，再进入实现。"
                    if has_memory_context and use_zh
                    else "先补齐必要上下文，避免盲改，并找出最合适的执行路径。"
                    if use_zh
                    else "Collect enough context to avoid blind edits, validate recalled memory, and identify the likely execution path."
                    if has_memory_context
                    else "Collect enough context to avoid blind edits and identify the likely execution path."
                ),
                depends_on=["plan"],
            )
        )
        implementation_dependency = "research"

    steps.append(
        WorkflowStep(
            id="implement",
            title="直接修改文件" if use_zh else "Edit files directly",
            agent_role="coder",
            backend=backend_for_step("implement"),
            execution="serial",
            goal="直接在目标项目里完成需要的改动。" if use_zh else "Make the requested code changes in the target project.",
            depends_on=[implementation_dependency],
        )
    )

    review_dependencies: list[str]
    if parallel_checks:
        verify_steps = [
            WorkflowStep(
                id="verify_tests",
                title="运行回归测试" if use_zh else "Run regression tests",
                agent_role="runner/tester",
                backend=backend_for_step("verify_tests"),
                execution="parallel",
                goal=(
                    "运行测试和回归检查，确认这次改动没有破坏已有行为。"
                    if use_zh
                    else "Run automated tests and regression-focused checks for the task."
                ),
                depends_on=["implement"],
                allow_failed_dependencies=False,
                requires_confirmation=confirm_dangerous,
                command_previews=_verification_previews(
                    project_path_str,
                    focus="tests",
                    step_id="verify_tests",
                    requires_confirmation=confirm_dangerous,
                ),
            ),
            WorkflowStep(
                id="verify_build",
                title="运行构建与补充检查" if use_zh else "Run build and matrix checks",
                agent_role="runner/tester",
                backend=backend_for_step("verify_build"),
                execution="parallel",
                goal=(
                    "运行构建、对比或补充校验，确认结果在更完整的场景下仍然成立。"
                    if use_zh
                    else "Run build, benchmark, compare, or matrix-style checks when available."
                ),
                depends_on=["implement"],
                allow_failed_dependencies=False,
                requires_confirmation=confirm_dangerous,
                command_previews=_verification_previews(
                    project_path_str,
                    focus="build",
                    step_id="verify_build",
                    requires_confirmation=confirm_dangerous,
                ),
            ),
        ]
        steps.extend(verify_steps)
        review_dependencies = [step.id for step in verify_steps]
    else:
        steps.append(
            WorkflowStep(
                id="verify",
                title="运行检查与实验" if use_zh else "Run checks and experiments",
                agent_role="runner/tester",
                backend=backend_for_step("verify"),
                execution="serial",
                goal=(
                    "运行和这次任务最相关的测试、脚本或命令检查。"
                    if use_zh
                    else "Run the appropriate tests, scripts, or experiment commands for the task."
                ),
                depends_on=["implement"],
                allow_failed_dependencies=False,
                requires_confirmation=confirm_dangerous,
                command_previews=_verification_previews(
                    project_path_str,
                    focus="all",
                    step_id="verify",
                    requires_confirmation=confirm_dangerous,
                ),
            )
        )
        review_dependencies = ["verify"]

    steps.append(
        WorkflowStep(
            id="review",
            title="审查结果" if use_zh else "Review the result",
            agent_role="reviewer",
            backend=backend_for_step("review"),
            execution="serial",
            goal=(
                "检查结果质量、回归风险、记忆延续是否兑现，以及有没有遗漏的边界情况。"
                if has_memory_context and use_zh
                else "检查结果质量、回归风险和遗漏的边界情况。"
                if use_zh
                else "Inspect output quality, regressions, recalled-memory commitments, and missing edge cases before final handoff."
                if has_memory_context
                else "Inspect output quality, regressions, and missing edge cases before final handoff."
            ),
            depends_on=review_dependencies,
            allow_failed_dependencies=True,
        )
    )
    steps.append(
        WorkflowStep(
            id="report",
            title="生成交接报告" if use_zh else "Produce handoff report",
            agent_role="summarizer",
            backend=backend_for_step("report"),
            execution="serial",
            goal=(
                "整理改动、结果、后续事项、记忆更新和复现命令，但不要自动提交 Git。"
                if has_memory_context and use_zh
                else "整理改动、结果、后续事项和复现命令，但不要自动提交 Git。"
                if use_zh
                else "Summarize changes, results, follow-ups, recalled memory updates, and reproducible commands without auto-committing Git."
                if has_memory_context
                else "Summarize changes, results, follow-ups, and reproducible commands without auto-committing Git."
            ),
            depends_on=["review"],
            allow_failed_dependencies=False,
        )
    )
    return steps


def _resolve_memory_context(
    request: WorkflowPlanRequest,
    settings: Settings,
    memory_context: WorkflowMemoryContext | None,
) -> WorkflowMemoryContext | None:
    if memory_context is not None:
        return memory_context
    if not request.project_path:
        return None

    runtime = get_project_runtime(request.project_path, settings)
    return build_memory_context(
        request.project_path,
        request.task,
        settings,
        global_enabled=runtime.policy.global_memory_enabled,
    )


def build_workflow_plan(
    request: WorkflowPlanRequest,
    settings: Settings,
    *,
    memory_context: WorkflowMemoryContext | None = None,
) -> WorkflowPlanResponse:
    task = _task_lower(request.task)
    locale = request.locale
    use_zh = _use_zh(locale)
    project_name = Path(request.project_path).name if request.project_path else "workspace"
    allow_network = settings.default_allow_network if request.allow_network is None else request.allow_network
    allow_installs = settings.default_allow_installs if request.allow_installs is None else request.allow_installs

    resolved_memory_context = _resolve_memory_context(request, settings, memory_context)
    has_memory_context = bool(
        resolved_memory_context
        and (resolved_memory_context.recalled_project or resolved_memory_context.recalled_global)
    )
    has_recent_reuse_candidates = has_recent_reuse_candidate(request.project_path, request.task, settings)

    memory_guidance = (
        build_role_memory_guidance(resolved_memory_context, locale=locale)
        if resolved_memory_context
        else build_role_memory_guidance(WorkflowMemoryContext(project_memory_path="", global_memory_path=None), locale=locale)
    )

    team_name = f"{project_name}-任务编组" if use_zh else f"{project_name}-task-force"
    warnings = [
        (
            "Codex 会话续接仍属于适配能力，实际可用性会受 CLI 行为影响。"
            if use_zh
            else "Codex session continuation is still treated as an adapter-level capability and may depend on CLI behavior."
        ),
        (
            "危险命令在执行前必须经过明确确认。"
            if use_zh
            else "Dangerous commands should require explicit confirmation before execution."
        ),
        (
            "工作流输出只应停留在文件改动和报告，Git 提交与推送在 V1 中保持手动。"
            if use_zh
            else "Workflow output should stop at file changes and reports. Git commit and push stay manual in V1."
        ),
    ]

    if not allow_network:
        warnings.append(
            "当前草稿已关闭联网能力，所以远程搜索和依赖拉取都应跳过。"
            if use_zh
            else "Network access is disabled for this draft, so remote search and package fetches should be skipped."
        )
    if not allow_installs:
        warnings.append(
            "当前草稿已关闭安装依赖，所以需要避免把修复建立在 install 步骤之上。"
            if use_zh
            else "Package installation is disabled for this draft, so dependency fixes must avoid install steps."
        )
    if has_memory_context:
        warnings.append(
            "这次运行召回了历史记忆，所以审查和交接时要明确说明哪些旧结论被延续、修正或替换。"
            if use_zh
            else "Planner memory recall is active for this run, so reviewer/reporter continuity checks should stay in scope."
        )
    if has_recent_reuse_candidates:
        warnings.append(
            "这个项目里已经有近期相似的成功运行，所以 research 会先判断是否可以直接复用，或只保留差量执行。"
            if use_zh
            else "A recent similar successful run already exists for this project, so research will first decide whether the workflow can be reused or narrowed to a delta-only pass."
        )

    summary = (
        "这是一个面向代码任务的严格协作流程。规划者负责排步骤，实现者直接改文件，验证者负责检查，审查者补齐风险，最后由汇总者整理交接。"
        if use_zh
        else "A strict multi-agent workflow optimized for code tasks. The planner owns sequencing, the coder edits files, the runner verifies, the reviewer checks risk, and the summarizer closes the loop."
    )
    if has_memory_context:
        summary = (
            f"{summary} 这次计划还带入了 {len(memory_guidance.planner)} 条历史上下文提醒。"
            if use_zh
            else f"{summary} The plan is carrying forward {len(memory_guidance.planner)} structured memory cue(s)."
        )

    return WorkflowPlanResponse(
        team_name=team_name,
        summary=summary,
        project_path=request.project_path,
        allow_network=allow_network,
        allow_installs=allow_installs,
        command_policy="dangerous-commands-confirmed",
        agents=_build_agents(
            task,
            has_memory_context=has_memory_context,
            has_recent_reuse_candidates=has_recent_reuse_candidates,
            locale=locale,
        ),
        steps=_build_steps(
            task,
            confirm_dangerous=settings.default_confirm_dangerous_commands,
            has_memory_context=has_memory_context,
            has_recent_reuse_candidates=has_recent_reuse_candidates,
            project_path_str=request.project_path,
            locale=locale,
        ),
        memory_guidance=memory_guidance,
        outputs=(
            [
                "直接文件改动",
                "验证日志",
                "任务报告",
                "过程记录",
                "可复现命令清单",
                "记忆交接条目",
            ]
            if use_zh
            else [
                "direct file changes",
                "verification logs",
                "task report",
                "conversation notes",
                "reproducible command list",
                "memory handoff entry",
            ]
        ),
        warnings=warnings,
    )
