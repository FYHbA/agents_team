import type {
  CodexSummary,
  ProjectRecord,
  ProjectRootEntry,
  ProjectTreeResponse,
  ProjectCapabilities,
  ProjectPickResult,
  ProjectRuntime,
  ProjectRuntimeMirrorResult,
  RecentProjectRecord,
  WorkspaceRecord,
  WorkflowPlan,
  WorkflowQueueDashboard,
  WorkflowRunArtifacts,
  WorkflowAgentSession,
  WorkflowRunEvent,
  WorkflowRunDeleteResult,
  WorkflowRunLog,
  WorkflowRun,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

function buildApiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getCodexSummary(): Promise<CodexSummary> {
  return fetchJson<CodexSummary>("/api/codex/summary");
}

export function getDiscoveredProjects(): Promise<ProjectRecord[]> {
  return fetchJson<ProjectRecord[]>("/api/projects/discovered");
}

export function getProjectRoots(): Promise<{ roots: ProjectRootEntry[] }> {
  return fetchJson<{ roots: ProjectRootEntry[] }>("/api/projects/roots");
}

export function getRecentProjects(): Promise<RecentProjectRecord[]> {
  return fetchJson<RecentProjectRecord[]>("/api/projects/recent");
}

export function openWorkspace(payload: {
  project_path: string;
  name?: string;
  alias?: string;
  source?: "codex-config" | "filesystem" | "manual" | "picker";
}): Promise<WorkspaceRecord> {
  return fetchJson<WorkspaceRecord>("/api/projects/workspaces/open", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getProjectCapabilities(): Promise<ProjectCapabilities> {
  return fetchJson<ProjectCapabilities>("/api/projects/capabilities");
}

export function pickProjectDirectory(): Promise<ProjectPickResult> {
  return fetchJson<ProjectPickResult>("/api/projects/pick", {
    method: "POST",
  });
}

export function getProjectRuntime(path: string): Promise<ProjectRuntime> {
  return fetchJson<ProjectRuntime>(`/api/projects/runtime?path=${encodeURIComponent(path)}`);
}

export function getProjectTree(path: string, depth = 1): Promise<ProjectTreeResponse> {
  return fetchJson<ProjectTreeResponse>(`/api/projects/tree?path=${encodeURIComponent(path)}&depth=${depth}`);
}

export function initProjectRuntime(projectPath: string): Promise<ProjectRuntime> {
  return fetchJson<ProjectRuntime>("/api/projects/runtime/init", {
    method: "POST",
    body: JSON.stringify({ project_path: projectPath }),
  });
}

export function mirrorProjectRuntime(projectPath: string): Promise<ProjectRuntimeMirrorResult> {
  return fetchJson<ProjectRuntimeMirrorResult>("/api/projects/runtime/mirror", {
    method: "POST",
    body: JSON.stringify({ project_path: projectPath }),
  });
}

export function exportProjectRuntime(projectPath: string): Promise<ProjectRuntimeMirrorResult> {
  return fetchJson<ProjectRuntimeMirrorResult>("/api/projects/runtime/export", {
    method: "POST",
    body: JSON.stringify({ project_path: projectPath }),
  });
}

export function importProjectRuntime(projectPath: string): Promise<ProjectRuntimeMirrorResult> {
  return fetchJson<ProjectRuntimeMirrorResult>("/api/projects/runtime/import", {
    method: "POST",
    body: JSON.stringify({ project_path: projectPath }),
  });
}

export function createWorkflowPlan(payload: {
  task: string;
  project_path: string | null;
  allow_network: boolean;
  allow_installs: boolean;
  locale?: "zh-CN" | "en-US";
}): Promise<WorkflowPlan> {
  return fetchJson<WorkflowPlan>("/api/workflows/plan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createWorkflowRun(payload: {
  task: string;
  project_path: string;
  allow_network: boolean;
  allow_installs: boolean;
  locale?: "zh-CN" | "en-US";
  start_immediately?: boolean;
}): Promise<WorkflowRun> {
  return fetchJson<WorkflowRun>("/api/workflows/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getWorkflowRuns(projectPath?: string): Promise<WorkflowRun[]> {
  if (!projectPath) {
    return fetchJson<WorkflowRun[]>("/api/workflows/runs");
  }
  return fetchJson<WorkflowRun[]>(`/api/workflows/runs?project_path=${encodeURIComponent(projectPath)}`);
}

export function getWorkflowRun(runId: string, projectPath?: string): Promise<WorkflowRun> {
  if (!projectPath) {
    return fetchJson<WorkflowRun>(`/api/workflows/runs/${encodeURIComponent(runId)}`);
  }
  return fetchJson<WorkflowRun>(
    `/api/workflows/runs/${encodeURIComponent(runId)}?project_path=${encodeURIComponent(projectPath)}`,
  );
}

export function deleteWorkflowRun(runId: string, projectPath?: string): Promise<WorkflowRunDeleteResult> {
  if (!projectPath) {
    return fetchJson<WorkflowRunDeleteResult>(`/api/workflows/runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    });
  }
  return fetchJson<WorkflowRunDeleteResult>(
    `/api/workflows/runs/${encodeURIComponent(runId)}?project_path=${encodeURIComponent(projectPath)}`,
    {
      method: "DELETE",
    },
  );
}

export function executeWorkflowRun(runId: string, projectPath?: string): Promise<WorkflowRun> {
  if (!projectPath) {
    return fetchJson<WorkflowRun>(`/api/workflows/runs/${encodeURIComponent(runId)}/execute`, {
      method: "POST",
    });
  }
  return fetchJson<WorkflowRun>(
    `/api/workflows/runs/${encodeURIComponent(runId)}/execute?project_path=${encodeURIComponent(projectPath)}`,
    {
      method: "POST",
    },
  );
}

export function cancelWorkflowRun(runId: string, projectPath?: string): Promise<WorkflowRun> {
  if (!projectPath) {
    return fetchJson<WorkflowRun>(`/api/workflows/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    });
  }
  return fetchJson<WorkflowRun>(
    `/api/workflows/runs/${encodeURIComponent(runId)}/cancel?project_path=${encodeURIComponent(projectPath)}`,
    {
      method: "POST",
    },
  );
}

export function approveDangerousCommands(
  runId: string,
  projectPath?: string,
  payload?: { command_ids?: string[] },
): Promise<WorkflowRun> {
  if (!projectPath) {
    return fetchJson<WorkflowRun>(`/api/workflows/runs/${encodeURIComponent(runId)}/approve-dangerous`, {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    });
  }
  return fetchJson<WorkflowRun>(
    `/api/workflows/runs/${encodeURIComponent(runId)}/approve-dangerous?project_path=${encodeURIComponent(projectPath)}`,
    {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    },
  );
}

export function resumeWorkflowRun(runId: string, projectPath?: string): Promise<WorkflowRun> {
  if (!projectPath) {
    return fetchJson<WorkflowRun>(`/api/workflows/runs/${encodeURIComponent(runId)}/resume`, {
      method: "POST",
    });
  }
  return fetchJson<WorkflowRun>(
    `/api/workflows/runs/${encodeURIComponent(runId)}/resume?project_path=${encodeURIComponent(projectPath)}`,
    {
      method: "POST",
    },
  );
}

export function retryWorkflowRun(runId: string, projectPath?: string): Promise<WorkflowRun> {
  if (!projectPath) {
    return fetchJson<WorkflowRun>(`/api/workflows/runs/${encodeURIComponent(runId)}/retry`, {
      method: "POST",
    });
  }
  return fetchJson<WorkflowRun>(
    `/api/workflows/runs/${encodeURIComponent(runId)}/retry?project_path=${encodeURIComponent(projectPath)}`,
    {
      method: "POST",
    },
  );
}

export function getWorkflowRunLog(runId: string, projectPath?: string, tail = 200): Promise<WorkflowRunLog> {
  const query = [`tail=${tail}`];
  if (projectPath) {
    query.push(`project_path=${encodeURIComponent(projectPath)}`);
  }
  return fetchJson<WorkflowRunLog>(`/api/workflows/runs/${encodeURIComponent(runId)}/log?${query.join("&")}`);
}

export function getWorkflowRunArtifacts(runId: string, projectPath?: string): Promise<WorkflowRunArtifacts> {
  if (!projectPath) {
    return fetchJson<WorkflowRunArtifacts>(`/api/workflows/runs/${encodeURIComponent(runId)}/artifacts`);
  }
  return fetchJson<WorkflowRunArtifacts>(
    `/api/workflows/runs/${encodeURIComponent(runId)}/artifacts?project_path=${encodeURIComponent(projectPath)}`,
  );
}

export function getWorkflowRunEventsUrl(runId: string, projectPath?: string, tail = 200): string {
  const query = new URLSearchParams({ tail: String(tail) });
  if (projectPath) {
    query.set("project_path", projectPath);
  }
  return buildApiUrl(`/api/workflows/runs/${encodeURIComponent(runId)}/events?${query.toString()}`);
}

export function parseWorkflowRunEvent(data: string): WorkflowRunEvent {
  return JSON.parse(data) as WorkflowRunEvent;
}

export function getWorkflowQueueDashboard(): Promise<WorkflowQueueDashboard> {
  return fetchJson<WorkflowQueueDashboard>("/api/workflows/queue");
}

export function getWorkflowAgentSessions(runId: string): Promise<WorkflowAgentSession[]> {
  return fetchJson<WorkflowAgentSession[]>(`/api/workflows/runs/${encodeURIComponent(runId)}/agent-sessions`);
}
