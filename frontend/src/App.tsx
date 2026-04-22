import { useEffect, useState } from "react";

import {
  createWorkflowPlan,
  createWorkflowRun,
  getCodexCapabilities,
  getCodexSummary,
  getDiscoveredProjects,
  getProjectRuntime,
  getRecentSessions,
  getWorkflowRuns,
  initProjectRuntime,
  prepareCodexSessionBridge,
} from "./api";
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

type ChatBubble = {
  speaker: string;
  role: string;
  text: string;
};

const defaultBubbles: ChatBubble[] = [
  {
    speaker: "Planner",
    role: "planner",
    text: "Drop in a code task and I will draft the first workflow with team roles and execution order.",
  },
  {
    speaker: "Reviewer",
    role: "reviewer",
    text: "V1 keeps Git actions manual. We focus on direct edits, verification, and a clean report.",
  },
  {
    speaker: "Codex Bridge",
    role: "adapter",
    text: "Recent Codex sessions and trusted projects can be surfaced here so the team can pick up existing context.",
  },
];

function planFromRun(run: WorkflowRun): WorkflowPlan {
  return {
    team_name: run.team_name,
    summary: run.summary,
    project_path: run.project_path,
    allow_network: run.allow_network,
    allow_installs: run.allow_installs,
    command_policy: run.command_policy,
    agents: run.agents,
    steps: run.steps,
    outputs: run.outputs,
    warnings: run.warnings,
  };
}

function buildBubbles(
  plan: WorkflowPlan | null,
  bridge: CodexSessionBridge | null,
  runtime: ProjectRuntime | null,
): ChatBubble[] {
  if (!plan) {
    const extra = [...defaultBubbles];
    if (runtime && runtime.state !== "missing") {
      extra.push({
        speaker: "Runtime",
        role: "runtime",
        text: `Project runtime is ready at ${runtime.runtime_path}. New runs can be stored locally without auto-committing Git.`,
      });
    }
    if (bridge?.commands?.length) {
      extra.push({
        speaker: "Codex Bridge",
        role: "adapter",
        text: "A resumable Codex bridge command is ready for the selected session and project.",
      });
    }
    return extra;
  }

  const intro = plan.agents.slice(0, 3).map((agent) => ({
    speaker: agent.name,
    role: agent.role,
    text: agent.reason,
  }));

  return [
    {
      speaker: "System",
      role: "workflow",
      text: plan.summary,
    },
    ...intro,
  ];
}

function formatDateTime(value: string): string {
  if (!value) {
    return "Unknown";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function App() {
  const [summary, setSummary] = useState<CodexSummary | null>(null);
  const [capabilities, setCapabilities] = useState<CodexCapabilities | null>(null);
  const [sessions, setSessions] = useState<CodexSession[]>([]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>("");
  const [selectedSessionId, setSelectedSessionId] = useState<string>("");
  const [task, setTask] = useState(
    "Audit the current repository, design a strict multi-agent workflow, and scaffold the first backend/frontend implementation plan.",
  );
  const [allowNetwork, setAllowNetwork] = useState(true);
  const [allowInstalls, setAllowInstalls] = useState(true);
  const [plan, setPlan] = useState<WorkflowPlan | null>(null);
  const [runtime, setRuntime] = useState<ProjectRuntime | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [bridge, setBridge] = useState<CodexSessionBridge | null>(null);
  const [loading, setLoading] = useState(false);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runLoading, setRunLoading] = useState(false);
  const [bridgeLoading, setBridgeLoading] = useState(false);
  const [bootstrapError, setBootstrapError] = useState<string>("");
  const [planError, setPlanError] = useState<string>("");
  const [runtimeError, setRuntimeError] = useState<string>("");
  const [runError, setRunError] = useState<string>("");
  const [bridgeError, setBridgeError] = useState<string>("");

  useEffect(() => {
    async function bootstrap() {
      try {
        const [summaryResult, capabilitiesResult, sessionsResult, projectsResult] = await Promise.all([
          getCodexSummary(),
          getCodexCapabilities(),
          getRecentSessions(),
          getDiscoveredProjects(),
        ]);
        setSummary(summaryResult);
        setCapabilities(capabilitiesResult);
        setSessions(sessionsResult);
        setProjects(projectsResult);
        if (projectsResult.length > 0) {
          setSelectedProject(projectsResult[0].path);
        }
      } catch (error) {
        setBootstrapError(error instanceof Error ? error.message : "Failed to load app bootstrap data.");
      }
    }

    bootstrap();
  }, []);

  useEffect(() => {
    async function loadProjectState(projectPath: string) {
      setRuntimeLoading(true);
      setRuntimeError("");
      setRunError("");
      try {
        const [runtimeResult, runsResult] = await Promise.all([
          getProjectRuntime(projectPath),
          getWorkflowRuns(projectPath),
        ]);
        setRuntime(runtimeResult);
        setRuns(runsResult);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to load project runtime state.";
        setRuntimeError(message);
      } finally {
        setRuntimeLoading(false);
      }
    }

    if (!selectedProject) {
      setRuntime(null);
      setRuns([]);
      return;
    }
    loadProjectState(selectedProject);
  }, [selectedProject]);

  async function handleDraftWorkflow() {
    setLoading(true);
    setPlanError("");
    try {
      const result = await createWorkflowPlan({
        task,
        project_path: selectedProject || null,
        allow_network: allowNetwork,
        allow_installs: allowInstalls,
      });
      setPlan(result);
    } catch (error) {
      setPlanError(error instanceof Error ? error.message : "Failed to draft workflow.");
    } finally {
      setLoading(false);
    }
  }

  async function handleInitRuntime() {
    if (!selectedProject) {
      setRuntimeError("Select a project first.");
      return;
    }

    setRuntimeLoading(true);
    setRuntimeError("");
    try {
      const result = await initProjectRuntime(selectedProject);
      setRuntime(result);
    } catch (error) {
      setRuntimeError(error instanceof Error ? error.message : "Failed to initialize the project runtime.");
    } finally {
      setRuntimeLoading(false);
    }
  }

  async function handlePrepareBridge(sessionId: string) {
    setSelectedSessionId(sessionId);
    setBridgeLoading(true);
    setBridgeError("");
    try {
      const result = await prepareCodexSessionBridge(sessionId, {
        project_path: selectedProject || null,
        prompt: task,
        sandbox_mode: "workspace-write",
        approval_policy: "on-request",
      });
      setBridge(result);
    } catch (error) {
      setBridgeError(error instanceof Error ? error.message : "Failed to prepare the Codex session bridge.");
    } finally {
      setBridgeLoading(false);
    }
  }

  async function handleCreateRun() {
    if (!selectedProject) {
      setRunError("Select a project before creating a workflow run.");
      return;
    }

    setRunLoading(true);
    setRunError("");
    try {
      const result = await createWorkflowRun({
        task,
        project_path: selectedProject,
        allow_network: allowNetwork,
        allow_installs: allowInstalls,
        codex_session_id: selectedSessionId || null,
        resume_prompt: selectedSessionId ? task : undefined,
      });
      setPlan(planFromRun(result));
      const [runtimeResult, runsResult] = await Promise.all([
        getProjectRuntime(selectedProject),
        getWorkflowRuns(selectedProject),
      ]);
      setRuntime(runtimeResult);
      setRuns(runsResult);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Failed to create the workflow run.");
    } finally {
      setRunLoading(false);
    }
  }

  const bubbles = buildBubbles(plan, bridge, runtime);

  return (
    <div className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Local-First Multi-Agent Workbench</p>
          <h1>Agents Team</h1>
          <p className="hero-copy">
            A team-room UI for orchestrating planner, coder, runner, reviewer, and summarizer agents
            across multiple local projects while staying close to Codex.
          </p>
        </div>
        <div className="hero-status">
          <div className="status-card">
            <span className="status-label">Codex bridge</span>
            <strong>{summary?.codex_cli_available ? "Detected" : "Unavailable"}</strong>
            <span>{capabilities?.version ?? summary?.integration_mode ?? "waiting for backend"}</span>
          </div>
          <div className="status-card accent">
            <span className="status-label">Workflow mode</span>
            <strong>Strict</strong>
            <span>Serial + parallel by step</span>
          </div>
        </div>
      </header>

      {bootstrapError ? <div className="banner error">{bootstrapError}</div> : null}

      <main className="workspace">
        <section className="panel sidebar">
          <div className="panel-header">
            <h2>Projects</h2>
            <span>{projects.length} discovered</span>
          </div>

          <div className="project-list">
            {projects.length === 0 ? (
              <div className="empty-state">No projects discovered yet from the local Codex config.</div>
            ) : (
              projects.map((project) => (
                <button
                  key={project.path}
                  type="button"
                  className={`project-item ${selectedProject === project.path ? "selected" : ""}`}
                  onClick={() => setSelectedProject(project.path)}
                >
                  <span className="project-path">{project.path}</span>
                  <span className="project-meta">{project.source}</span>
                </button>
              ))
            )}
          </div>

          <div className="panel-header subheader">
            <h2>Codex bridge</h2>
            <span>{sessions.length} recent sessions</span>
          </div>
          <div className="meta-grid">
            <div>
              <span className="meta-label">Config path</span>
              <strong>{summary?.config_path ?? "Unavailable"}</strong>
            </div>
            <div>
              <span className="meta-label">Session index</span>
              <strong>{summary?.session_index_path ?? "Unavailable"}</strong>
            </div>
            <div>
              <span className="meta-label">Capabilities</span>
              <strong>
                {capabilities?.resume_available ? "resume" : "no resume"} /{" "}
                {capabilities?.exec_resume_available ? "exec resume" : "no exec resume"}
              </strong>
            </div>
          </div>
          <div className="session-list">
            {sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                className={`session-item ${selectedSessionId === session.id ? "selected" : ""}`}
                onClick={() => handlePrepareBridge(session.id)}
              >
                <strong>{session.thread_name}</strong>
                <span>{formatDateTime(session.updated_at)}</span>
                <code>{session.id}</code>
              </button>
            ))}
          </div>

          <div className="panel-header subheader">
            <h2>Project runtime</h2>
            <span>{runtime?.state ?? "waiting"}</span>
          </div>
          <div className="runtime-card">
            <div className="meta-grid compact">
              <div>
                <span className="meta-label">Runtime path</span>
                <strong>{runtime?.runtime_path ?? "Not initialized"}</strong>
              </div>
              <div>
                <span className="meta-label">Policy</span>
                <strong>{runtime?.policy.git_strategy ?? "manual"} / project + global memory</strong>
              </div>
            </div>
            <div className="button-row">
              <button type="button" className="secondary-button" onClick={handleInitRuntime} disabled={runtimeLoading}>
                {runtimeLoading ? "Initializing..." : "Initialize .agents-team"}
              </button>
            </div>
            {runtimeError ? <div className="inline-error">{runtimeError}</div> : null}
          </div>

          <div className="panel-header subheader">
            <h2>Bridge commands</h2>
            <span>{bridgeLoading ? "preparing" : bridge?.can_resume ? "ready" : "idle"}</span>
          </div>
          <div className="command-list">
            {bridge?.commands?.length ? (
              bridge.commands.map((command) => (
                <article key={`${command.mode}-${command.argv.join(" ")}`} className="command-item">
                  <strong>{command.purpose}</strong>
                  <span className="meta-label">{command.mode}</span>
                  <code>{command.argv.join(" ")}</code>
                </article>
              ))
            ) : (
              <div className="empty-state">Pick a recent session to preview resumable Codex bridge commands.</div>
            )}
          </div>
          {bridgeError ? <div className="inline-error">{bridgeError}</div> : null}
        </section>

        <section className="panel team-room">
          <div className="panel-header">
            <h2>Team room</h2>
            <span>Natural language first</span>
          </div>

          <div className="chat-log">
            {bubbles.map((bubble, index) => (
              <article key={`${bubble.speaker}-${index}`} className="bubble">
                <div className="bubble-meta">
                  <strong>{bubble.speaker}</strong>
                  <span>{bubble.role}</span>
                </div>
                <p>{bubble.text}</p>
              </article>
            ))}
          </div>

          <div className="composer">
            <label htmlFor="task" className="field-label">
              Task draft
            </label>
            <textarea id="task" value={task} onChange={(event) => setTask(event.target.value)} rows={7} />
            <div className="toggle-row">
              <label>
                <input
                  type="checkbox"
                  checked={allowNetwork}
                  onChange={(event) => setAllowNetwork(event.target.checked)}
                />
                Allow network search
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={allowInstalls}
                  onChange={(event) => setAllowInstalls(event.target.checked)}
                />
                Allow package installs
              </label>
            </div>
            <div className="composer-footer">
              <span className="project-pill">{selectedProject || "No project selected"}</span>
              <div className="button-row">
                <button type="button" className="secondary-button" onClick={handleDraftWorkflow} disabled={loading || task.trim().length < 8}>
                  {loading ? "Drafting..." : "Draft workflow"}
                </button>
                <button
                  type="button"
                  onClick={handleCreateRun}
                  disabled={runLoading || task.trim().length < 8 || !selectedProject}
                >
                  {runLoading ? "Creating..." : "Create run record"}
                </button>
              </div>
            </div>
            {planError ? <div className="inline-error">{planError}</div> : null}
            {runError ? <div className="inline-error">{runError}</div> : null}
          </div>
        </section>

        <section className="panel workflow">
          <div className="panel-header">
            <h2>Workflow draft</h2>
            <span>{plan?.team_name ?? "waiting for task"}</span>
          </div>

          <div className="workflow-summary">
            <p>{plan?.summary ?? "Draft a task to generate the first multi-agent workflow plan."}</p>
          </div>

          <div className="agent-grid">
            {(plan?.agents ?? []).map((agent) => (
              <article key={agent.role} className="agent-card">
                <span className="agent-role">{agent.role}</span>
                <strong>{agent.name}</strong>
                <p>{agent.reason}</p>
              </article>
            ))}
          </div>

          <div className="step-list">
            {(plan?.steps ?? []).map((step) => (
              <article key={step.id} className="step-item">
                <div className="step-header">
                  <strong>{step.title}</strong>
                  <span className={`step-mode ${step.execution}`}>{step.execution}</span>
                </div>
                <p>{step.goal}</p>
                <div className="step-meta">
                  <span>{step.agent_role}</span>
                  {step.requires_confirmation ? <span>dangerous commands require confirmation</span> : null}
                </div>
              </article>
            ))}
          </div>

          <div className="outputs">
            <h3>Expected outputs</h3>
            <ul>
              {(plan?.outputs ?? ["code changes", "reports", "logs"]).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>

          {plan?.warnings?.length ? (
            <div className="warnings">
              <h3>Warnings</h3>
              <ul>
                {plan.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="panel-header subheader">
            <h2>Run ledger</h2>
            <span>{runs.length} runs</span>
          </div>
          <div className="run-list">
            {runs.length === 0 ? (
              <div className="empty-state">No workflow runs have been created for the selected project yet.</div>
            ) : (
              runs.map((run) => (
                <article key={run.id} className="run-item">
                  <div className="step-header">
                    <strong>{run.team_name}</strong>
                    <span className={`step-mode ${run.status === "planned" ? "parallel" : "serial"}`}>{run.status}</span>
                  </div>
                  <p>{run.task}</p>
                  <div className="step-meta">
                    <span>{formatDateTime(run.created_at)}</span>
                    <span>{run.codex_session_id ? `linked to ${run.codex_session_id}` : "new Codex run path"}</span>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
