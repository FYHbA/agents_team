from __future__ import annotations

from typing import Literal

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


class ProjectRuntimePolicy(BaseModel):
    allow_network: bool
    allow_installs: bool
    dangerous_commands_require_confirmation: bool
    git_strategy: Literal["manual"]
    global_memory_enabled: bool
    direct_file_editing: bool


class ProjectRuntimeRequest(BaseModel):
    project_path: str


class ProjectRuntimeResponse(BaseModel):
    project_path: str
    runtime_path: str
    state: Literal["missing", "initialized", "existing"]
    settings_path: str
    directories: list[str]
    policy: ProjectRuntimePolicy
    global_home: str


class AgentCard(BaseModel):
    name: str
    role: str
    reason: str


class WorkflowStep(BaseModel):
    id: str
    title: str
    agent_role: str
    execution: Literal["serial", "parallel"]
    goal: str
    requires_confirmation: bool = False


class WorkflowPlanRequest(BaseModel):
    task: str = Field(min_length=8, description="Natural-language task from the user.")
    project_path: str | None = None
    allow_network: bool | None = None
    allow_installs: bool | None = None


class WorkflowPlanResponse(BaseModel):
    team_name: str
    summary: str
    project_path: str | None
    allow_network: bool
    allow_installs: bool
    command_policy: str
    agents: list[AgentCard]
    steps: list[WorkflowStep]
    outputs: list[str]
    warnings: list[str]


class WorkflowRunCreateRequest(BaseModel):
    task: str = Field(min_length=8, description="Natural-language task from the user.")
    project_path: str = Field(min_length=1, description="Absolute path to the managed project.")
    allow_network: bool | None = None
    allow_installs: bool | None = None
    codex_session_id: str | None = None
    resume_prompt: str | None = None


class WorkflowRunRecord(BaseModel):
    id: str
    status: Literal["planned", "running", "completed", "failed", "cancelled"]
    created_at: str
    updated_at: str
    task: str
    project_path: str
    runtime_path: str
    run_path: str
    report_path: str
    changes_path: str
    memory_scope: Literal["project+global"]
    git_strategy: Literal["manual"]
    direct_file_editing: bool
    team_name: str
    summary: str
    allow_network: bool
    allow_installs: bool
    command_policy: str
    agents: list[AgentCard]
    steps: list[WorkflowStep]
    outputs: list[str]
    warnings: list[str]
    codex_session_id: str | None = None
    codex_commands: list[CodexCommandSpec] = Field(default_factory=list)


ProjectTreeEntry.model_rebuild()
