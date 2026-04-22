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

export type CodexCapabilities = {
  codex_cli_available: boolean;
  version: string | null;
  resume_available: boolean;
  exec_resume_available: boolean;
  app_server_available: boolean;
  exec_server_available: boolean;
  mcp_server_available: boolean;
  config_path: string;
  session_index_path: string;
  note: string;
};

export type CodexSession = {
  id: string;
  thread_name: string;
  updated_at: string;
};

export type CodexCommandSpec = {
  argv: string[];
  cwd: string | null;
  mode: "interactive" | "non_interactive" | "service";
  purpose: string;
};

export type CodexSessionBridge = {
  session: CodexSession;
  project_path: string | null;
  session_log_path: string | null;
  can_resume: boolean;
  commands: CodexCommandSpec[];
  strategies: string[];
  warnings: string[];
};

export type ProjectRecord = {
  path: string;
  source: "codex-config" | "filesystem";
  trusted: boolean;
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
  project_path: string;
  runtime_path: string;
  state: "missing" | "initialized" | "existing";
  settings_path: string;
  directories: string[];
  policy: ProjectRuntimePolicy;
  global_home: string;
};

export type AgentCard = {
  name: string;
  role: string;
  reason: string;
};

export type WorkflowStep = {
  id: string;
  title: string;
  agent_role: string;
  execution: "serial" | "parallel";
  goal: string;
  requires_confirmation: boolean;
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
  outputs: string[];
  warnings: string[];
};

export type WorkflowRun = {
  id: string;
  status: "planned" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  updated_at: string;
  task: string;
  project_path: string;
  runtime_path: string;
  run_path: string;
  report_path: string;
  changes_path: string;
  memory_scope: "project+global";
  git_strategy: "manual";
  direct_file_editing: boolean;
  team_name: string;
  summary: string;
  allow_network: boolean;
  allow_installs: boolean;
  command_policy: string;
  agents: AgentCard[];
  steps: WorkflowStep[];
  outputs: string[];
  warnings: string[];
  codex_session_id: string | null;
  codex_commands: CodexCommandSpec[];
};
