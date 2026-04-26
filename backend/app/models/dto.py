from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]


class CodexSessionSummary(BaseModel):
    id: str
    thread_name: str
    updated_at: str


class CodexSummaryResponse(BaseModel):
    codex_home: str
    config_path: str
    session_index_path: str
    config_exists: bool
    session_index_exists: bool
    codex_cli_available: bool
    trusted_project_count: int
    integration_mode: str
    note: str


class CodexCapabilitiesResponse(BaseModel):
    codex_cli_available: bool
    version: str | None
    resume_available: bool
    exec_resume_available: bool
    app_server_available: bool
    exec_server_available: bool
    mcp_server_available: bool
    config_path: str
    session_index_path: str
    note: str


class CodexCommandSpec(BaseModel):
    argv: list[str]
    cwd: str | None
    mode: Literal["interactive", "non_interactive", "service"]
    purpose: str


class CodexSessionBridgeRequest(BaseModel):
    project_path: str | None = None
    prompt: str | None = None
    sandbox_mode: Literal["read-only", "workspace-write", "danger-full-access"] | None = None
    approval_policy: Literal["untrusted", "on-request", "never"] | None = None


class CodexSessionBridgeResponse(BaseModel):
    session: CodexSessionSummary
    project_path: str | None
    session_log_path: str | None
    can_resume: bool
    commands: list[CodexCommandSpec]
    strategies: list[str]
    warnings: list[str]


class DiscoveredProject(BaseModel):
    path: str
    source: Literal["codex-config", "filesystem"]
    trusted: bool = True


class ProjectTreeEntry(BaseModel):
    name: str
    path: str
    entry_type: Literal["file", "directory"]
    children: list["ProjectTreeEntry"] = Field(default_factory=list)


class ProjectTreeResponse(BaseModel):
    root: str
    entries: list[ProjectTreeEntry]


class ProjectRootEntry(BaseModel):
    name: str
    path: str


class ProjectRootsResponse(BaseModel):
    roots: list[ProjectRootEntry]


class ProjectRuntimePolicy(BaseModel):
    allow_network: bool
    allow_installs: bool
    dangerous_commands_require_confirmation: bool
    git_strategy: Literal["manual"]
    global_memory_enabled: bool
    direct_file_editing: bool


class ProjectRuntimeRequest(BaseModel):
    project_path: str


class WorkspaceOpenRequest(BaseModel):
    project_path: str
    name: str | None = None
    alias: str | None = None
    source: Literal["codex-config", "filesystem", "manual", "picker"] = "manual"


class ProjectRuntimeMirrorRequest(BaseModel):
    project_path: str
    path: str | None = None


class ProjectRuntimeResponse(BaseModel):
    workspace_id: str | None = None
    workspace_name: str | None = None
    workspace_alias: str | None = None
    project_path: str
    runtime_path: str
    state: Literal["missing", "initialized", "existing"]
    settings_path: str
    directories: list[str]
    policy: ProjectRuntimePolicy
    global_home: str


class ProjectRuntimeMirrorResponse(BaseModel):
    operation: Literal["mirror", "export", "import"]
    project_path: str
    path: str
    run_count: int
    queue_item_count: int
    agent_session_count: int
    generated_at: str


class ProjectPickResponse(BaseModel):
    path: str | None = None


class ProjectCapabilitiesResponse(BaseModel):
    native_picker_available: bool


class WorkspaceRecord(BaseModel):
    id: str
    name: str
    alias: str
    project_path: str
    runtime_path: str
    source: Literal["codex-config", "filesystem", "manual", "picker"]
    trusted: bool = True
    updated_at: str
    last_opened_at: str | None = None


class RecentProjectRecord(BaseModel):
    workspace_id: str
    name: str
    alias: str
    path: str
    runtime_path: str
    updated_at: str


class AgentCard(BaseModel):
    name: str
    role: str
    reason: str


class WorkflowStep(BaseModel):
    id: str
    title: str
    agent_role: str
    backend: Literal[
        "planner_backend",
        "research_backend",
        "codex_backend",
        "verify_backend",
        "reviewer_backend",
        "reporter_backend",
    ]
    execution: Literal["serial", "parallel"]
    goal: str
    depends_on: list[str] = Field(default_factory=list)
    allow_failed_dependencies: bool = False
    requires_confirmation: bool = False
    command_previews: list["WorkflowCommandPreview"] = Field(default_factory=list)


class WorkflowPlanRequest(BaseModel):
    task: str = Field(min_length=8, description="Natural-language task from the user.")
    project_path: str | None = None
    allow_network: bool | None = None
    allow_installs: bool | None = None
    locale: Literal["zh-CN", "en-US"] | None = None


class WorkflowPlanResponse(BaseModel):
    team_name: str
    summary: str
    project_path: str | None
    allow_network: bool
    allow_installs: bool
    command_policy: str
    agents: list[AgentCard]
    steps: list[WorkflowStep]
    memory_guidance: "WorkflowRoleMemoryGuidance" = Field(default_factory=lambda: WorkflowRoleMemoryGuidance())
    outputs: list[str]
    warnings: list[str]


class WorkflowRunCreateRequest(BaseModel):
    task: str = Field(min_length=8, description="Natural-language task from the user.")
    project_path: str = Field(min_length=1, description="Absolute path to the managed project.")
    allow_network: bool | None = None
    allow_installs: bool | None = None
    locale: Literal["zh-CN", "en-US"] | None = None
    codex_session_id: str | None = None
    resume_prompt: str | None = None
    start_immediately: bool = False


class MemoryEntry(BaseModel):
    id: str
    scope: Literal["project", "global"]
    entry_kind: Literal["handoff", "research_finding", "verification_finding", "global_rule"] = "handoff"
    source_step_id: Literal["research", "verify"] | None = None
    step_status: Literal["completed", "failed"] | None = None
    created_at: str
    source_run_id: str | None = None
    attempt_count: int | None = None
    title: str
    summary: str
    details: str
    promote_to_global_rule: bool = False
    tags: list[str] = Field(default_factory=list)


class WorkflowMemoryContext(BaseModel):
    project_memory_path: str
    global_memory_path: str | None = None
    recalled_project: list[MemoryEntry] = Field(default_factory=list)
    recalled_global: list[MemoryEntry] = Field(default_factory=list)
    written_project: list[MemoryEntry] = Field(default_factory=list)
    written_global: list[MemoryEntry] = Field(default_factory=list)


class WorkflowRoleMemoryGuidance(BaseModel):
    planner: list[str] = Field(default_factory=list)
    reviewer: list[str] = Field(default_factory=list)
    reporter: list[str] = Field(default_factory=list)


class WorkflowCommandPreview(BaseModel):
    command_id: str
    label: str
    argv: list[str]
    cwd: str | None = None
    source: Literal["verification", "codex_bridge"] = "verification"
    requires_confirmation: bool = False
    confirmed_at: str | None = None
    delta_scoped: bool = False
    scope_note: str | None = None


class DangerousCommandApprovalRequest(BaseModel):
    command_ids: list[str] = Field(default_factory=list)


class WorkflowDeltaScope(BaseModel):
    focus_paths: list[str] = Field(default_factory=list)
    matched_run_changed_files: list[str] = Field(default_factory=list)
    current_diff_files: list[str] = Field(default_factory=list)
    verification_focus: Literal["all", "tests", "build", "docs"] = "all"
    scope_summary: str = ""


class WorkflowStepRun(BaseModel):
    step_id: str
    title: str
    agent_role: str
    backend: Literal[
        "planner_backend",
        "research_backend",
        "codex_backend",
        "verify_backend",
        "reviewer_backend",
        "reporter_backend",
    ]
    execution: Literal["serial", "parallel"]
    goal: str
    depends_on: list[str] = Field(default_factory=list)
    allow_failed_dependencies: bool = False
    status: Literal["pending", "running", "completed", "failed", "skipped", "cancelled"]
    command_previews: list[WorkflowCommandPreview] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    summary: str | None = None


class WorkflowRunRecord(BaseModel):
    id: str
    status: Literal["planned", "running", "completed", "failed", "cancelled", "short_circuited"]
    attempt_count: int = 0
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    cancel_requested_at: str | None = None
    cancelled_at: str | None = None
    task: str
    project_path: str
    runtime_path: str
    run_path: str
    report_path: str
    changes_path: str
    log_path: str
    last_message_path: str | None = None
    memory_scope: Literal["project", "project+global"]
    git_strategy: Literal["manual"]
    direct_file_editing: bool
    requires_dangerous_command_confirmation: bool = False
    dangerous_commands_confirmed_at: str | None = None
    team_name: str
    summary: str
    allow_network: bool
    allow_installs: bool
    command_policy: str
    agents: list[AgentCard]
    steps: list[WorkflowStep]
    outputs: list[str]
    warnings: list[str]
    error: str | None = None
    reuse_decision: Literal["continue", "stop_as_duplicate", "stop_as_already_satisfied", "continue_with_delta"] | None = None
    matched_run_id: str | None = None
    reuse_reason: str | None = None
    reuse_confidence: float | None = None
    delta_hint: str | None = None
    delta_scope: WorkflowDeltaScope | None = None
    step_runs: list[WorkflowStepRun] = Field(default_factory=list)
    memory_context: WorkflowMemoryContext
    memory_guidance: WorkflowRoleMemoryGuidance
    codex_session_id: str | None = None
    codex_commands: list[CodexCommandSpec] = Field(default_factory=list)


class WorkflowRunLogResponse(BaseModel):
    run_id: str
    log_path: str
    content: str


class WorkflowRunDeleteResponse(BaseModel):
    run_id: str
    project_path: str
    deleted_at: str


class ContractMemorySummary(BaseModel):
    scope: Literal["project", "global"]
    title: str
    summary: str
    created_at: str | None = None


class ResearchResultContract(BaseModel):
    decision: Literal["continue", "stop_as_duplicate", "stop_as_already_satisfied", "continue_with_delta"] = "continue"
    matched_run_id: str | None = None
    confidence: float = 0.0
    reason: str = ""
    delta_hint: str = ""
    delta_scope: WorkflowDeltaScope | None = None
    run_id: str
    task: str
    project_root: str
    top_level_entries: list[str] = Field(default_factory=list)
    relevant_hotspots: list[str] = Field(default_factory=list)
    continuity_notes: list[str] = Field(default_factory=list)
    suggested_next_attention_areas: list[str] = Field(default_factory=list)
    summary: str


class VerifyCommandResultContract(BaseModel):
    label: str
    status: Literal["completed", "failed", "skipped"]
    exit_code: int | None = None
    output_excerpt: str | None = None


class VerifySummaryContract(BaseModel):
    run_id: str
    step_id: str
    task: str
    executed_commands: list[VerifyCommandResultContract] = Field(default_factory=list)
    result_summary: str
    validation_risks: list[str] = Field(default_factory=list)
    follow_up_checks: list[str] = Field(default_factory=list)
    summary: str


class ReviewResultContract(BaseModel):
    run_id: str
    task: str
    reviewer_memory_cross_checks: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    risk_assessment: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    git_status_excerpt: str | None = None
    diff_stat_excerpt: str | None = None
    summary: str


class FinalStateStepOutcomeContract(BaseModel):
    step_id: str
    title: str
    status: str
    summary: str | None = None


class FinalStateContract(BaseModel):
    run_id: str
    task: str
    status: str
    attempt_count: int
    reuse_decision: str | None = None
    matched_run_id: str | None = None
    reuse_reason: str | None = None
    reuse_confidence: float | None = None
    delta_hint: str | None = None
    delta_scope: WorkflowDeltaScope | None = None
    step_outcomes: list[FinalStateStepOutcomeContract] = Field(default_factory=list)
    memory_recall: list[ContractMemorySummary] = Field(default_factory=list)
    codex_final_message: str | None = None
    change_summary_excerpt: str | None = None
    memory_writes: list[ContractMemorySummary] = Field(default_factory=list)
    promoted_global_rules: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str


class WorkflowContextAuditSourceRecord(BaseModel):
    key: str
    path: str
    bytes: int


class WorkflowContextAuditRecord(BaseModel):
    id: str
    run_id: str
    step_id: str
    agent_role: str
    backend: Literal[
        "planner_backend",
        "research_backend",
        "codex_backend",
        "verify_backend",
        "reviewer_backend",
        "reporter_backend",
    ]
    workspace_path: str
    input_sources: list[WorkflowContextAuditSourceRecord] = Field(default_factory=list)
    input_bytes: int
    memory_item_count: int
    raw_log_bytes_included: int
    markdown_artifact_bytes_included: int
    forbidden_source_attempts: int = 0
    input_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None
    created_at: str
    updated_at: str


class WorkflowRunContextAuditsResponse(BaseModel):
    run_id: str
    audits: list[WorkflowContextAuditRecord] = Field(default_factory=list)
    total_input_bytes: int = 0
    total_forbidden_source_attempts: int = 0
    total_memory_items: int = 0
    total_input_tokens: int | None = None
    total_cached_tokens: int | None = None
    total_output_tokens: int | None = None


class WorkflowArtifactDocument(BaseModel):
    key: Literal[
        "planning_brief",
        "report",
        "changes",
        "last_message",
        "project_snapshot",
        "verification_brief",
        "parallel_branches",
        "memory_context",
        "research_result",
        "verify_summary",
        "review_result",
        "final_state",
    ]
    title: str
    path: str | None
    content_type: Literal["markdown", "text", "json"]
    available: bool
    content: str


class WorkflowRunArtifactsResponse(BaseModel):
    run_id: str
    documents: list[WorkflowArtifactDocument]


class WorkflowQueueItemRecord(BaseModel):
    id: str
    run_id: str
    project_path: str | None = None
    mode: Literal["start", "resume", "retry"]
    item_kind: Literal["run", "step"] = "run"
    target_step_id: str | None = None
    branch_group_id: str | None = None
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    prepared: bool
    enqueued_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    worker_id: str | None = None
    heartbeat_at: str | None = None
    lease_expires_at: str | None = None


class WorkflowWorkerRecord(BaseModel):
    worker_id: str
    thread_name: str
    process_id: int
    host: str
    status: Literal["idle", "running", "stale"]
    started_at: str
    last_heartbeat_at: str
    current_item_id: str | None = None
    current_run_id: str | None = None
    stale_reason: str | None = None


class WorkflowQueueDashboardResponse(BaseModel):
    items: list[WorkflowQueueItemRecord]
    workers: list[WorkflowWorkerRecord]
    queued_count: int
    running_count: int
    terminal_count: int
    stale_count: int
    stale_worker_count: int = 0
    hidden_terminal_count: int = 0
    hidden_worker_count: int = 0


class WorkflowAgentCommandRecord(BaseModel):
    id: str
    label: str
    command: str
    status: str
    output: str
    exit_code: int | None = None
    sequence: int


class WorkflowAgentSessionRecord(BaseModel):
    id: str
    run_id: str
    step_id: str
    title: str
    agent_role: str
    backend: Literal[
        "planner_backend",
        "research_backend",
        "codex_backend",
        "verify_backend",
        "reviewer_backend",
        "reporter_backend",
    ]
    execution: Literal["serial", "parallel"]
    status: Literal["running", "completed", "failed", "cancelled"]
    owner_worker_id: str | None = None
    provider: str | None = None
    session_ref: str | None = None
    started_at: str
    completed_at: str | None = None
    summary: str | None = None
    error: str | None = None
    has_structured_timeline: bool = False
    thinking_messages: list[str] = Field(default_factory=list)
    final_message: str | None = None
    collapsed_preview: str | None = None
    commands: list[WorkflowAgentCommandRecord] = Field(default_factory=list)
    events: list["WorkflowAgentSessionEventRecord"] = Field(default_factory=list)


class WorkflowAgentSessionEventRecord(BaseModel):
    id: str
    session_id: str
    run_id: str
    step_id: str
    sequence: int
    created_at: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


ProjectTreeEntry.model_rebuild()
WorkflowAgentSessionRecord.model_rebuild()
