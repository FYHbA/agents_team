import type {
  CodexCapabilities,
  CodexSession,
  CodexSessionBridge,
  CodexSummary,
  ProjectRecord,
  ProjectRuntime,
  WorkflowPlan,
  WorkflowRun,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
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

export function getCodexCapabilities(): Promise<CodexCapabilities> {
  return fetchJson<CodexCapabilities>("/api/codex/capabilities");
}

export function getRecentSessions(): Promise<CodexSession[]> {
  return fetchJson<CodexSession[]>("/api/codex/sessions");
}

export function prepareCodexSessionBridge(
  sessionId: string,
  payload: {
    project_path: string | null;
    prompt?: string;
    sandbox_mode?: "read-only" | "workspace-write" | "danger-full-access";
    approval_policy?: "untrusted" | "on-request" | "never";
  },
): Promise<CodexSessionBridge> {
  return fetchJson<CodexSessionBridge>(`/api/codex/sessions/${encodeURIComponent(sessionId)}/bridge`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDiscoveredProjects(): Promise<ProjectRecord[]> {
  return fetchJson<ProjectRecord[]>("/api/projects/discovered");
}

export function getProjectRuntime(path: string): Promise<ProjectRuntime> {
  return fetchJson<ProjectRuntime>(`/api/projects/runtime?path=${encodeURIComponent(path)}`);
}

export function initProjectRuntime(projectPath: string): Promise<ProjectRuntime> {
  return fetchJson<ProjectRuntime>("/api/projects/runtime/init", {
    method: "POST",
    body: JSON.stringify({ project_path: projectPath }),
  });
}

export function createWorkflowPlan(payload: {
  task: string;
  project_path: string | null;
  allow_network: boolean;
  allow_installs: boolean;
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
  codex_session_id?: string | null;
  resume_prompt?: string;
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
