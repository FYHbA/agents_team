export type CodexSummary = {
  codex_home: string;
  config_path: string;
  session_index_path: string;
  config_exists: boolean;
  session_index_exists: boolean;
  codex_cli_available: boolean;
  trusted_project_count: number;
  integration_mode: string;
  note: string;
};

export type CodexCommandSpec = {
  argv: string[];
  cwd: string | null;
  mode: "interactive" | "non_interactive" | "service";
  purpose: string;
};

export type ProjectRecord = {
  path: string;
  source: "codex-config" | "filesystem";
  trusted: boolean;
};

export type ProjectRootEntry = {
  name: string;
  path: string;
};

export type ProjectTreeEntry = {
  name: string;
  path: string;
  entry_type: "file" | "directory";
  children: ProjectTreeEntry[];
};

export type ProjectTreeResponse = {
  root: string;
  entries: ProjectTreeEntry[];
};

export type WorkspaceRecord = {
  id: string;
  name: string;
  alias: string;
  project_path: string;
  runtime_path: string;
  source: "codex-config" | "filesystem" | "manual" | "picker";
  trusted: boolean;
  updated_at: string;
  last_opened_at: string | null;
};

export type ProjectPickResult = {
  path: string | null;
};

export type ProjectCapabilities = {
  native_picker_available: boolean;
};

export type RecentProjectRecord = {
  workspace_id: string;
  name: string;
  alias: string;
  path: string;
  runtime_path: string;
  updated_at: string;
};

export type ProjectRuntimePolicy = {
  allow_network: boolean;
  allow_installs: boolean;
  dangerous_commands_require_confirmation: boolean;
  git_strategy: "manual";
  global_memory_enabled: boolean;
  direct_file_editing: boolean;
};

export type ProjectRuntime = {
  workspace_id: string | null;
  workspace_name: string | null;
  workspace_alias: string | null;
  project_path: string;
  runtime_path: string;
  state: "missing" | "initialized" | "existing";
  settings_path: string;
  directories: string[];
  policy: ProjectRuntimePolicy;
  global_home: string;
};

export type ProjectRuntimeMirrorResult = {
  operation: "mirror" | "export" | "import";
  project_path: string;
  path: string;
  run_count: number;
  queue_item_count: number;
  agent_session_count: number;
  generated_at: string;
};

export type AgentCard = {
  name: string;
  role: string;
  reason: string;
};

export type WorkflowCommandPreview = {
  command_id: string;
  label: string;
  argv: string[];
  cwd: string | null;
  source: "verification" | "codex_bridge";
  requires_confirmation: boolean;
  confirmed_at: string | null;
  delta_scoped: boolean;
  scope_note: string | null;
};

export type WorkflowDeltaScope = {
  focus_paths: string[];
  matched_run_changed_files: string[];
  current_diff_files: string[];
  verification_focus: "all" | "tests" | "build" | "docs";
  scope_summary: string;
};

export type WorkflowStep = {
  id: string;
  title: string;
  agent_role: string;
  backend:
    | "planner_backend"
    | "research_backend"
    | "codex_backend"
    | "verify_backend"
    | "reviewer_backend"
    | "reporter_backend";
  execution: "serial" | "parallel";
  goal: string;
  depends_on: string[];
  allow_failed_dependencies: boolean;
  requires_confirmation: boolean;
  command_previews: WorkflowCommandPreview[];
};

export type MemoryEntry = {
  id: string;
  scope: "project" | "global";
  entry_kind: "handoff" | "research_finding" | "verification_finding" | "global_rule";
  source_step_id: "research" | "verify" | null;
  step_status: "completed" | "failed" | null;
  created_at: string;
  source_run_id: string | null;
  attempt_count: number | null;
  title: string;
  summary: string;
  details: string;
  promote_to_global_rule: boolean;
  tags: string[];
};

export type WorkflowMemoryContext = {
  project_memory_path: string;
  global_memory_path: string | null;
  recalled_project: MemoryEntry[];
  recalled_global: MemoryEntry[];
  written_project: MemoryEntry[];
  written_global: MemoryEntry[];
};

export type WorkflowRoleMemoryGuidance = {
  planner: string[];
  reviewer: string[];
  reporter: string[];
};

export type WorkflowStepRun = {
  step_id: string;
  title: string;
  agent_role: string;
  backend:
    | "planner_backend"
    | "research_backend"
    | "codex_backend"
    | "verify_backend"
    | "reviewer_backend"
    | "reporter_backend";
  execution: "serial" | "parallel";
  goal: string;
  depends_on: string[];
  allow_failed_dependencies: boolean;
  status: "pending" | "running" | "completed" | "failed" | "skipped" | "cancelled";
  command_previews: WorkflowCommandPreview[];
  started_at: string | null;
  completed_at: string | null;
  summary: string | null;
};

export type WorkflowPlan = {
  team_name: string;
  summary: string;
  project_path: string | null;
  allow_network: boolean;
  allow_installs: boolean;
  command_policy: string;
  agents: AgentCard[];
  steps: WorkflowStep[];
  memory_guidance: WorkflowRoleMemoryGuidance;
  outputs: string[];
  warnings: string[];
};

export type WorkflowRun = {
  id: string;
  status: "planned" | "running" | "completed" | "failed" | "cancelled" | "short_circuited";
  attempt_count: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  cancel_requested_at: string | null;
  cancelled_at: string | null;
  task: string;
  project_path: string;
  runtime_path: string;
  run_path: string;
  report_path: string;
  changes_path: string;
  log_path: string;
  last_message_path: string | null;
  memory_scope: "project" | "project+global";
  git_strategy: "manual";
  direct_file_editing: boolean;
  requires_dangerous_command_confirmation: boolean;
  dangerous_commands_confirmed_at: string | null;
  team_name: string;
  summary: string;
  allow_network: boolean;
  allow_installs: boolean;
  command_policy: string;
  agents: AgentCard[];
  steps: WorkflowStep[];
  outputs: string[];
  warnings: string[];
  error: string | null;
  reuse_decision: "continue" | "stop_as_duplicate" | "stop_as_already_satisfied" | "continue_with_delta" | null;
  matched_run_id: string | null;
  reuse_reason: string | null;
  reuse_confidence: number | null;
  delta_hint: string | null;
  delta_scope: WorkflowDeltaScope | null;
  step_runs: WorkflowStepRun[];
  memory_context: WorkflowMemoryContext;
  memory_guidance: WorkflowRoleMemoryGuidance;
  codex_session_id: string | null;
  codex_commands: CodexCommandSpec[];
};

export type WorkflowRunLog = {
  run_id: string;
  log_path: string;
  content: string;
};

export type WorkflowRunDeleteResult = {
  run_id: string;
  project_path: string;
  deleted_at: string;
};

export type WorkflowRunEvent = {
  run: WorkflowRun;
  log: WorkflowRunLog;
  terminal: boolean;
};

export type WorkflowArtifactDocument = {
  key:
    | "planning_brief"
    | "report"
    | "changes"
    | "last_message"
    | "project_snapshot"
    | "verification_brief"
    | "parallel_branches"
    | "memory_context"
    | "research_result"
    | "verify_summary"
    | "review_result"
    | "final_state";
  title: string;
  path: string | null;
  content_type: "markdown" | "text" | "json";
  available: boolean;
  content: string;
};

export type WorkflowRunArtifacts = {
  run_id: string;
  documents: WorkflowArtifactDocument[];
};

export type WorkflowContextAuditSource = {
  key: string;
  path: string;
  bytes: number;
};

export type WorkflowContextAudit = {
  id: string;
  run_id: string;
  step_id: string;
  agent_role: string;
  backend:
    | "planner_backend"
    | "research_backend"
    | "codex_backend"
    | "verify_backend"
    | "reviewer_backend"
    | "reporter_backend";
  workspace_path: string;
  input_sources: WorkflowContextAuditSource[];
  input_bytes: number;
  memory_item_count: number;
  raw_log_bytes_included: number;
  markdown_artifact_bytes_included: number;
  forbidden_source_attempts: number;
  input_tokens: number | null;
  cached_tokens: number | null;
  output_tokens: number | null;
  created_at: string;
  updated_at: string;
};

export type WorkflowRunContextAudits = {
  run_id: string;
  audits: WorkflowContextAudit[];
  total_input_bytes: number;
  total_forbidden_source_attempts: number;
  total_memory_items: number;
  total_input_tokens: number | null;
  total_cached_tokens: number | null;
  total_output_tokens: number | null;
};

export type WorkflowQueueItem = {
  id: string;
  run_id: string;
  project_path: string | null;
  mode: "start" | "resume" | "retry";
  item_kind: "run" | "step";
  target_step_id: string | null;
  branch_group_id: string | null;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  prepared: boolean;
  enqueued_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  worker_id: string | null;
  heartbeat_at: string | null;
  lease_expires_at: string | null;
};

export type WorkflowWorker = {
  worker_id: string;
  thread_name: string;
  process_id: number;
  host: string;
  status: "idle" | "running" | "stale";
  started_at: string;
  last_heartbeat_at: string;
  current_item_id: string | null;
  current_run_id: string | null;
  stale_reason: string | null;
};

export type WorkflowQueueDashboard = {
  items: WorkflowQueueItem[];
  workers: WorkflowWorker[];
  queued_count: number;
  running_count: number;
  terminal_count: number;
  stale_count: number;
  stale_worker_count: number;
  hidden_terminal_count: number;
  hidden_worker_count: number;
};

export type WorkflowAgentSession = {
  id: string;
  run_id: string;
  step_id: string;
  title: string;
  agent_role: string;
  backend:
    | "planner_backend"
    | "research_backend"
    | "codex_backend"
    | "verify_backend"
    | "reviewer_backend"
    | "reporter_backend";
  execution: "serial" | "parallel";
  status: "running" | "completed" | "failed" | "cancelled";
  owner_worker_id: string | null;
  provider: string | null;
  session_ref: string | null;
  started_at: string;
  completed_at: string | null;
  summary: string | null;
  error: string | null;
  has_structured_timeline: boolean;
  thinking_messages: string[];
  final_message: string | null;
  collapsed_preview: string | null;
  commands: WorkflowAgentCommand[];
  events: WorkflowAgentSessionEvent[];
};

export type WorkflowAgentSessionEvent = {
  id: string;
  session_id: string;
  run_id: string;
  step_id: string;
  sequence: number;
  created_at: string;
  event_type: string;
  payload: Record<string, unknown>;
};

export type WorkflowAgentCommand = {
  id: string;
  label: string;
  command: string;
  status: string;
  output: string;
  exit_code: number | null;
  sequence: number;
};

export type WorkflowAgentSessionPresentation = {
  has_structured_timeline: boolean;
  thinking_messages: string[];
  final_message: string | null;
  collapsed_preview: string | null;
  commands: WorkflowAgentCommand[];
};
