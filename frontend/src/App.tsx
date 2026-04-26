import { useEffect, useMemo, useState } from "react";

import {
  approveDangerousCommands,
  cancelWorkflowRun,
  createWorkflowPlan,
  createWorkflowRun,
  deleteWorkflowRun,
  executeWorkflowRun,
  exportProjectRuntime,
  getCodexSummary,
  getDiscoveredProjects,
  getProjectCapabilities,
  getProjectRoots,
  getProjectRuntime,
  getProjectTree,
  getRecentProjects,
  getWorkflowAgentSessions,
  getWorkflowQueueDashboard,
  getWorkflowRun,
  getWorkflowRunArtifacts,
  getWorkflowRunEventsUrl,
  getWorkflowRunLog,
  getWorkflowRuns,
  importProjectRuntime,
  initProjectRuntime,
  mirrorProjectRuntime,
  openWorkspace,
  parseWorkflowRunEvent,
  pickProjectDirectory,
  resumeWorkflowRun,
  retryWorkflowRun,
} from "./api";
import { AppHeader } from "./components/AppHeader";
import { BuildStage } from "./components/BuildStage";
import { DiagnosticsStage } from "./components/DiagnosticsStage";
import { ProjectStage } from "./components/ProjectStage";
import { RunStage } from "./components/RunStage";
import { WorkspaceStage } from "./components/WorkspaceStage";
import { useI18n } from "./i18n";
import type {
  CodexSummary,
  MemoryEntry,
  ProjectCapabilities,
  ProjectRecord,
  ProjectRootEntry,
  ProjectRuntime,
  ProjectRuntimeMirrorResult,
  ProjectTreeEntry,
  RecentProjectRecord,
  WorkflowAgentSession,
  WorkflowArtifactDocument,
  WorkflowPlan,
  WorkflowQueueDashboard,
  WorkflowQueueItem,
  WorkflowRun,
  WorkflowRunArtifacts,
} from "./types";

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
    memory_guidance: run.memory_guidance,
    outputs: run.outputs,
    warnings: run.warnings,
  };
}

function upsertRunRecord(currentRuns: WorkflowRun[], nextRun: WorkflowRun): WorkflowRun[] {
  const merged = currentRuns.filter((run) => run.id !== nextRun.id);
  merged.push(nextRun);
  merged.sort((left, right) => right.created_at.localeCompare(left.created_at));
  return merged;
}

function runNeedsDangerousApproval(run: WorkflowRun | null): boolean {
  if (!run) {
    return false;
  }
  return run.requires_dangerous_command_confirmation && !run.dangerous_commands_confirmed_at;
}

type AppView = "launcher" | "workspace";
type WorkspaceSection = "build" | "run";

export default function App() {
  const { locale, setLocale, t } = useI18n();

  const [summary, setSummary] = useState<CodexSummary | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [recentProjects, setRecentProjects] = useState<RecentProjectRecord[]>([]);
  const [projectCapabilities, setProjectCapabilities] = useState<ProjectCapabilities | null>(null);
  const [projectRoots, setProjectRoots] = useState<ProjectRootEntry[]>([]);
  const [browserRoot, setBrowserRoot] = useState("");
  const [browserEntries, setBrowserEntries] = useState<ProjectTreeEntry[]>([]);
  const [browserLoading, setBrowserLoading] = useState(false);
  const [browserError, setBrowserError] = useState("");

  const [selectedProject, setSelectedProject] = useState("");
  const [manualProjectPath, setManualProjectPath] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [activeView, setActiveView] = useState<AppView>("launcher");
  const [activeWorkspaceSection, setActiveWorkspaceSection] = useState<WorkspaceSection>("build");

  const [task, setTask] = useState("");
  const [allowNetwork, setAllowNetwork] = useState(true);
  const [allowInstalls, setAllowInstalls] = useState(true);

  const [plan, setPlan] = useState<WorkflowPlan | null>(null);
  const [runtime, setRuntime] = useState<ProjectRuntime | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<WorkflowRun | null>(null);
  const [runLog, setRunLog] = useState("");
  const [runArtifacts, setRunArtifacts] = useState<WorkflowRunArtifacts | null>(null);
  const [selectedArtifactKey, setSelectedArtifactKey] = useState<WorkflowArtifactDocument["key"]>("report");
  const [queueDashboard, setQueueDashboard] = useState<WorkflowQueueDashboard | null>(null);
  const [agentSessions, setAgentSessions] = useState<WorkflowAgentSession[]>([]);
  const [mirrorResult, setMirrorResult] = useState<ProjectRuntimeMirrorResult | null>(null);

  const [bootstrapError, setBootstrapError] = useState("");
  const [runtimeError, setRuntimeError] = useState("");
  const [planError, setPlanError] = useState("");
  const [runError, setRunError] = useState("");
  const [artifactError, setArtifactError] = useState("");
  const [queueError, setQueueError] = useState("");
  const [agentSessionsError, setAgentSessionsError] = useState("");
  const [mirrorError, setMirrorError] = useState("");

  const [loading, setLoading] = useState(false);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runLoading, setRunLoading] = useState(false);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [queueLoading, setQueueLoading] = useState(false);
  const [agentSessionsLoading, setAgentSessionsLoading] = useState(false);
  const [mirrorLoading, setMirrorLoading] = useState(false);

  const artifactRefreshToken = useMemo(() => {
    if (!selectedRun) {
      return "";
    }
    const trackedSteps = ["research", "implement", "verify", "review", "report", "verify_tests", "verify_build"];
    const stepToken = selectedRun.step_runs
      .filter((step) => trackedSteps.includes(step.step_id))
      .map((step) => `${step.step_id}:${step.status}:${step.completed_at ?? ""}`)
      .join("|");
    return `${selectedRun.id}|${selectedRun.status}|${stepToken}`;
  }, [selectedRun]);

  useEffect(() => {
    async function bootstrap() {
      try {
        const search = new URLSearchParams(window.location.search);
        const projectFromUrl = search.get("project");
        const runFromUrl = search.get("run");
        const viewFromUrl = search.get("view");

        const [summaryResult, projectsResult, recentProjectsResult, projectCapabilitiesResult, projectRootsResult] =
          await Promise.allSettled([
          getCodexSummary(),
          getDiscoveredProjects(),
          getRecentProjects(),
          getProjectCapabilities(),
          getProjectRoots(),
        ]);

        if (summaryResult.status === "fulfilled") {
          setSummary(summaryResult.value);
        }
        if (projectsResult.status === "fulfilled") {
          setProjects(projectsResult.value);
        }
        if (recentProjectsResult.status === "fulfilled") {
          setRecentProjects(recentProjectsResult.value);
        }
        if (projectCapabilitiesResult.status === "fulfilled") {
          setProjectCapabilities(projectCapabilitiesResult.value);
        }
        if (projectRootsResult.status === "fulfilled") {
          setProjectRoots(projectRootsResult.value.roots);
          if (projectRootsResult.value.roots[0]) {
            setBrowserRoot(projectRootsResult.value.roots[0].path);
          }
        }

        if (runFromUrl) {
          setSelectedRunId(runFromUrl);
        }

        const initialProject =
          projectFromUrl ??
          (recentProjectsResult.status === "fulfilled" ? recentProjectsResult.value[0]?.path ?? "" : "");
        const shouldOpenWorkspace = viewFromUrl === "workspace" || Boolean(initialProject);

        if (initialProject) {
          setManualProjectPath(initialProject);
        }

        if (shouldOpenWorkspace && initialProject) {
          await loadProjectState(initialProject, runFromUrl);
        } else {
          setActiveView("launcher");
        }
      } catch (error) {
        setBootstrapError(error instanceof Error ? error.message : "Failed to load app bootstrap data.");
      } finally {
        setBootstrapping(false);
      }
    }

    void bootstrap();
  }, []);

  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    if (selectedProject) {
      search.set("project", selectedProject);
    } else {
      search.delete("project");
    }
    if (selectedRunId) {
      search.set("run", selectedRunId);
    } else {
      search.delete("run");
    }
    search.set("view", activeView);
    window.history.replaceState({}, "", `${window.location.pathname}?${search.toString()}`);
  }, [selectedProject, selectedRunId, activeView]);

  useEffect(() => {
    let cancelled = false;

    async function loadBrowserEntries(path: string) {
      if (!path) {
        return;
      }
      setBrowserLoading(true);
      try {
        const result = await getProjectTree(path, 1);
        if (!cancelled) {
          setBrowserEntries(result.entries.filter((entry) => entry.entry_type === "directory"));
          setBrowserError("");
        }
      } catch (error) {
        if (!cancelled) {
          setBrowserError(error instanceof Error ? error.message : "Failed to browse the project host.");
        }
      } finally {
        if (!cancelled) {
          setBrowserLoading(false);
        }
      }
    }

    void loadBrowserEntries(browserRoot);
    return () => {
      cancelled = true;
    };
  }, [browserRoot]);

  useEffect(() => {
    let cancelled = false;

    async function loadSelectedRun(runId: string) {
      try {
        const [runResult, logResult] = await Promise.all([
          getWorkflowRun(runId, selectedProject),
          getWorkflowRunLog(runId, selectedProject),
        ]);
        if (cancelled) {
          return;
        }
        setSelectedRun(runResult);
        setRunLog(logResult.content);
        setRuns((currentRuns) => upsertRunRecord(currentRuns, runResult));
      } catch (error) {
        if (!cancelled) {
          setRunError(error instanceof Error ? error.message : "Failed to load workflow run details.");
        }
      }
    }

    if (!selectedProject || !selectedRunId) {
      setSelectedRun(null);
      setRunLog("");
      return;
    }

    void loadSelectedRun(selectedRunId);
    return () => {
      cancelled = true;
    };
  }, [selectedProject, selectedRunId]);

  useEffect(() => {
    let cancelled = false;

    async function loadArtifacts(runId: string) {
      setArtifactLoading(true);
      try {
        const result = await getWorkflowRunArtifacts(runId, selectedProject);
        if (!cancelled) {
          setRunArtifacts(result);
          setArtifactError("");
        }
      } catch (error) {
        if (!cancelled) {
          setArtifactError(error instanceof Error ? error.message : "Failed to load workflow artifacts.");
        }
      } finally {
        if (!cancelled) {
          setArtifactLoading(false);
        }
      }
    }

    if (!selectedProject || !selectedRunId || !selectedRun) {
      setRunArtifacts(null);
      setArtifactError("");
      return;
    }

    void loadArtifacts(selectedRunId);
    return () => {
      cancelled = true;
    };
  }, [selectedProject, selectedRunId, selectedRun, artifactRefreshToken]);

  useEffect(() => {
    let cancelled = false;

    async function loadQueueDashboard() {
      setQueueLoading(true);
      try {
        const result = await getWorkflowQueueDashboard();
        if (!cancelled) {
          setQueueDashboard(result);
          setQueueError("");
        }
      } catch (error) {
        if (!cancelled) {
          setQueueError(error instanceof Error ? error.message : "Failed to load workflow queue.");
        }
      } finally {
        if (!cancelled) {
          setQueueLoading(false);
        }
      }
    }

    void loadQueueDashboard();
    const timer = window.setInterval(() => {
      void loadQueueDashboard();
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadAgentSessions(runId: string, silent = false) {
      if (!silent) {
        setAgentSessionsLoading(true);
      }
      try {
        const result = await getWorkflowAgentSessions(runId);
        if (!cancelled) {
          setAgentSessions(result);
          setAgentSessionsError("");
        }
      } catch (error) {
        if (!cancelled) {
          setAgentSessionsError(error instanceof Error ? error.message : "Failed to load agent sessions.");
        }
      } finally {
        if (!cancelled && !silent) {
          setAgentSessionsLoading(false);
        }
      }
    }

    if (!selectedRunId) {
      setAgentSessions([]);
      setAgentSessionsError("");
      return;
    }

    void loadAgentSessions(selectedRunId);
    const timer =
      selectedRun?.status === "running"
        ? window.setInterval(() => {
            void loadAgentSessions(selectedRunId, true);
          }, 1500)
        : null;
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearInterval(timer);
      }
    };
  }, [selectedRunId, artifactRefreshToken, selectedRun?.status]);

  useEffect(() => {
    setSelectedArtifactKey((currentKey) => {
      const currentDocument = runArtifacts?.documents.find((document) => document.key === currentKey);
      if (currentDocument?.available) {
        return currentKey;
      }
      return runArtifacts?.documents.find((document) => document.available)?.key ?? "report";
    });
  }, [runArtifacts]);

  useEffect(() => {
    if (!selectedProject || !selectedRunId || selectedRun?.status !== "running") {
      return;
    }

    const stream = new EventSource(getWorkflowRunEventsUrl(selectedRunId, selectedProject));
    let closedByTerminalEvent = false;

    const handleRunUpdate = (event: MessageEvent<string>) => {
      try {
        const payload = parseWorkflowRunEvent(event.data);
        setSelectedRun(payload.run);
        setRunLog(payload.log.content);
        setRuns((currentRuns) => upsertRunRecord(currentRuns, payload.run));
        if (payload.terminal) {
          closedByTerminalEvent = true;
          stream.close();
        }
      } catch (error) {
        setRunError(error instanceof Error ? error.message : "Failed to process workflow run event.");
      }
    };

    const handleError = () => {
      if (!closedByTerminalEvent) {
        setRunError("Realtime workflow stream disconnected. The latest snapshot is still available.");
      }
      stream.close();
    };

    stream.addEventListener("run_update", handleRunUpdate as EventListener);
    stream.addEventListener("error", handleError as EventListener);
    return () => {
      stream.removeEventListener("run_update", handleRunUpdate as EventListener);
      stream.removeEventListener("error", handleError as EventListener);
      stream.close();
    };
  }, [selectedProject, selectedRunId, selectedRun?.status]);

  async function loadProjectState(projectPath: string, preferredRunId?: string | null): Promise<void> {
    setRuntimeLoading(true);
    setRuntimeError("");
    setRunError("");
    try {
      const switchingProjects = projectPath !== selectedProject;
      const [runtimeResultRaw, runsResult, recentResult] = await Promise.all([
        getProjectRuntime(projectPath),
        getWorkflowRuns(projectPath),
        getRecentProjects(),
      ]);
      const runtimeResult =
        runtimeResultRaw.state === "missing" ? await initProjectRuntime(projectPath) : runtimeResultRaw;
      if (switchingProjects) {
        setTask("");
        setPlan(null);
        setPlanError("");
        setArtifactError("");
        setSelectedArtifactKey("report");
      }
      setSelectedProject(projectPath);
      setManualProjectPath(projectPath);
      setRuntime(runtimeResult);
      setRuns(runsResult);
      setRecentProjects(recentResult);
      setSelectedRunId((currentRunId) => {
        const prioritizedRunId = preferredRunId || currentRunId;
        if (prioritizedRunId && runsResult.some((run) => run.id === prioritizedRunId)) {
          return prioritizedRunId;
        }
        return runsResult[0]?.id ?? "";
      });
      setActiveWorkspaceSection(preferredRunId || runsResult[0]?.id ? "run" : "build");
      setActiveView("workspace");
    } catch (error) {
      setRuntimeError(error instanceof Error ? error.message : "Failed to load project runtime state.");
    } finally {
      setRuntimeLoading(false);
    }
  }

  function formatDateTime(value: string): string {
    if (!value) {
      return t("common.unknown");
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? value
      : new Intl.DateTimeFormat(locale, {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }).format(date);
  }

  function backendLabel(backend: WorkflowRun["steps"][number]["backend"]): string {
    return t(`backend.${backend}`);
  }

  function executionLabel(execution: WorkflowPlan["steps"][number]["execution"]): string {
    return t(`execution.${execution}`);
  }

  function sourceLabel(source: ProjectRecord["source"]): string {
    return t(`project.source.${source}`);
  }

  function statusLabel(status: string): string {
    return t(`status.${status}`);
  }

  function queueModeLabel(mode: WorkflowQueueItem["mode"]): string {
    return t(`queueMode.${mode}`);
  }

  function runtimeStateLabel(state: ProjectRuntime["state"] | null | undefined): string {
    if (!state) {
      return t("common.waiting");
    }
    return t(`runtime.${state}`);
  }

  function agentRoleLabel(role: string): string {
    const keyByRole: Record<string, string> = {
      planner: "role.planner",
      researcher: "role.researcher",
      coder: "role.coder",
      "runner/tester": "role.runnerTester",
      reviewer: "role.reviewer",
      summarizer: "role.summarizer",
    };
    const key = keyByRole[role];
    return key ? t(key) : role;
  }

  function runStatusNote(run: WorkflowRun): string | null {
    if (runNeedsDangerousApproval(run)) {
      return t("run.awaitingApproval");
    }
    if (run.status === "running" && run.cancel_requested_at) {
      return `${t("run.cancelRun")} ${t("common.at")} ${formatDateTime(run.cancel_requested_at)}`;
    }
    if (run.status === "cancelled" && run.cancelled_at) {
      return `${t("status.cancelled")} ${t("common.at")} ${formatDateTime(run.cancelled_at)}`;
    }
    if (run.dangerous_commands_confirmed_at) {
      return `${t("run.safetyApproved")} ${t("common.at")} ${formatDateTime(run.dangerous_commands_confirmed_at)}`;
    }
    if (run.attempt_count > 1) {
      return `${t("run.attempt")} ${run.attempt_count}`;
    }
    return null;
  }

  function memorySummary(entries: MemoryEntry[]): string {
    if (entries.length === 0) {
      return t("common.none");
    }
    return entries.map((entry) => entry.title).join(" | ");
  }

  function finalizedStepCount(run: WorkflowRun): number {
    return run.step_runs.filter((step) => !["pending", "running"].includes(step.status)).length;
  }

  function readyArtifactCount(artifacts: WorkflowRunArtifacts | null): number {
    if (!artifacts) {
      return 0;
    }
    return artifacts.documents.filter((document) => document.available).length;
  }

  function writtenMemoryCount(run: WorkflowRun | null): number {
    if (!run) {
      return 0;
    }
    return run.memory_context.written_project.length + run.memory_context.written_global.length;
  }

  function recalledMemoryCount(run: WorkflowRun | null): number {
    if (!run) {
      return 0;
    }
    return run.memory_context.recalled_project.length + run.memory_context.recalled_global.length;
  }

  function promotedGlobalRuleCount(run: WorkflowRun | null): number {
    if (!run) {
      return 0;
    }
    return run.memory_context.written_global.filter((entry) => entry.entry_kind === "global_rule").length;
  }

  function queueItemNote(item: WorkflowQueueItem): string {
    if (item.status === "running" && item.worker_id) {
      return item.target_step_id
        ? t("queue.branchOwnedBy", { step: item.target_step_id, worker: item.worker_id })
        : t("queue.ownedBy", { worker: item.worker_id });
    }
    if (item.status === "queued") {
      return item.target_step_id
        ? t("queue.queuedBranch", { step: item.target_step_id })
        : t("queue.queuedFor", { mode: queueModeLabel(item.mode) });
    }
    if (item.error) {
      return item.error;
    }
    return t(`status.${item.status}`);
  }

  async function handleOpenProject(path: string, source: "manual" | "picker" | "codex-config" | "filesystem" = "manual") {
    const normalized = path.trim();
    if (!normalized) {
      setRuntimeError(t("project.notSelected"));
      return;
    }
    try {
      const workspace = await openWorkspace({
        project_path: normalized,
        source,
      });
      await initProjectRuntime(workspace.project_path);
      await loadProjectState(workspace.project_path);
    } catch (error) {
      setRuntimeError(error instanceof Error ? error.message : "Failed to open the project.");
    }
  }

  function handleTaskChange(value: string) {
    setTask(value);
    setPlanError("");
    if (plan) {
      setPlan(null);
    }
  }

  function handleAllowNetworkChange(value: boolean) {
    setAllowNetwork(value);
    if (plan) {
      setPlan(null);
    }
  }

  function handleAllowInstallsChange(value: boolean) {
    setAllowInstalls(value);
    if (plan) {
      setPlan(null);
    }
  }

  async function handlePickProject() {
    setRuntimeError("");
    try {
      const result = await pickProjectDirectory();
      if (result.path) {
        await handleOpenProject(result.path, "picker");
      }
    } catch (error) {
      setRuntimeError(error instanceof Error ? error.message : "Failed to open the native folder picker.");
    }
  }

  function handleBrowseRoot(path: string) {
    setBrowserRoot(path);
  }

  async function handleOpenFromBrowser(path: string) {
    await handleOpenProject(path, "filesystem");
  }

  function handleOpenLauncher() {
    setActiveView("launcher");
  }

  async function handleDraftWorkflow() {
    setLoading(true);
    setPlanError("");
    try {
      const result = await createWorkflowPlan({
        task,
        project_path: selectedProject || null,
        allow_network: allowNetwork,
        allow_installs: allowInstalls,
        locale,
      });
      setPlan(result);
      setActiveWorkspaceSection("build");
    } catch (error) {
      setPlanError(error instanceof Error ? error.message : "Failed to draft workflow.");
    } finally {
      setLoading(false);
    }
  }

  async function handleInitRuntime() {
    if (!selectedProject) {
      setRuntimeError(t("project.notSelected"));
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

  async function handleMirrorRuntime() {
    if (!selectedProject) {
      setMirrorError(t("project.notSelected"));
      return;
    }
    setMirrorLoading(true);
    setMirrorError("");
    try {
      setMirrorResult(await mirrorProjectRuntime(selectedProject));
    } catch (error) {
      setMirrorError(error instanceof Error ? error.message : "Failed to mirror the project control plane.");
    } finally {
      setMirrorLoading(false);
    }
  }

  async function handleExportRuntime() {
    if (!selectedProject) {
      setMirrorError(t("project.notSelected"));
      return;
    }
    setMirrorLoading(true);
    setMirrorError("");
    try {
      setMirrorResult(await exportProjectRuntime(selectedProject));
    } catch (error) {
      setMirrorError(error instanceof Error ? error.message : "Failed to export the project control plane.");
    } finally {
      setMirrorLoading(false);
    }
  }

  async function handleImportRuntime() {
    if (!selectedProject) {
      setMirrorError(t("project.notSelected"));
      return;
    }
    setMirrorLoading(true);
    setMirrorError("");
    try {
      const result = await importProjectRuntime(selectedProject);
      setMirrorResult(result);
      await loadProjectState(selectedProject);
    } catch (error) {
      setMirrorError(error instanceof Error ? error.message : "Failed to import the project control plane.");
    } finally {
      setMirrorLoading(false);
    }
  }

  async function handleCreateRun() {
    if (!selectedProject) {
      setRunError(t("project.notSelected"));
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
        locale,
        start_immediately: true,
      });
      setPlan(planFromRun(result));
      setSelectedRunId(result.id);
      setSelectedRun(result);
      setRunLog("");
      const [runtimeResult, runsResult] = await Promise.all([
        getProjectRuntime(selectedProject),
        getWorkflowRuns(selectedProject),
      ]);
      setRuntime(runtimeResult);
      setRuns(upsertRunRecord(runsResult, result));
      setActiveWorkspaceSection("run");
      setActiveView("workspace");
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Failed to create the workflow run.");
    } finally {
      setRunLoading(false);
    }
  }

  async function handleExecuteRun(runId: string) {
    if (!selectedProject) {
      setRunError(t("project.notSelected"));
      return;
    }
    setRunLoading(true);
    setRunError("");
    try {
      const result = await executeWorkflowRun(runId, selectedProject);
      setSelectedRunId(result.id);
      setSelectedRun(result);
      setRuns((currentRuns) => upsertRunRecord(currentRuns, result));
      setActiveWorkspaceSection("run");
      setActiveView("workspace");
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Failed to start the workflow run.");
    } finally {
      setRunLoading(false);
    }
  }

  async function handleCancelRun(runId: string) {
    if (!selectedProject) {
      setRunError(t("project.notSelected"));
      return;
    }
    setRunLoading(true);
    setRunError("");
    try {
      const result = await cancelWorkflowRun(runId, selectedProject);
      setSelectedRunId(result.id);
      setSelectedRun(result);
      setRuns((currentRuns) => upsertRunRecord(currentRuns, result));
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Failed to cancel the workflow run.");
    } finally {
      setRunLoading(false);
    }
  }

  async function handleApproveRun(runId: string, commandIds?: string[]) {
    if (!selectedProject) {
      setRunError(t("project.notSelected"));
      return;
    }
    setRunLoading(true);
    setRunError("");
    try {
      const result = await approveDangerousCommands(
        runId,
        selectedProject,
        commandIds && commandIds.length ? { command_ids: commandIds } : undefined,
      );
      setSelectedRunId(result.id);
      setSelectedRun(result);
      setRuns((currentRuns) => upsertRunRecord(currentRuns, result));
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Failed to approve dangerous commands for the workflow run.");
    } finally {
      setRunLoading(false);
    }
  }

  async function handleResumeRun(runId: string) {
    if (!selectedProject) {
      setRunError(t("project.notSelected"));
      return;
    }
    setRunLoading(true);
    setRunError("");
    try {
      const result = await resumeWorkflowRun(runId, selectedProject);
      setSelectedRunId(result.id);
      setSelectedRun(result);
      setRuns((currentRuns) => upsertRunRecord(currentRuns, result));
      setActiveWorkspaceSection("run");
      setActiveView("workspace");
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Failed to resume the workflow run.");
    } finally {
      setRunLoading(false);
    }
  }

  async function handleRetryRun(runId: string) {
    if (!selectedProject) {
      setRunError(t("project.notSelected"));
      return;
    }
    setRunLoading(true);
    setRunError("");
    try {
      const result = await retryWorkflowRun(runId, selectedProject);
      setSelectedRunId(result.id);
      setSelectedRun(result);
      setRuns((currentRuns) => upsertRunRecord(currentRuns, result));
      setActiveWorkspaceSection("run");
      setActiveView("workspace");
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Failed to retry the workflow run.");
    } finally {
      setRunLoading(false);
    }
  }

  async function handleDeleteRun(runId: string) {
    if (!selectedProject) {
      setRunError(t("project.notSelected"));
      return;
    }
    const deletingSelectedRun = selectedRunId === runId;
    setRunLoading(true);
    setRunError("");
    try {
      await deleteWorkflowRun(runId, selectedProject);
      if (deletingSelectedRun) {
        setSelectedRunId("");
        setSelectedRun(null);
        setRunLog("");
        setRunArtifacts(null);
        setAgentSessions([]);
        setArtifactError("");
        setAgentSessionsError("");
        setSelectedArtifactKey("report");
      }
      await loadProjectState(selectedProject, deletingSelectedRun ? undefined : selectedRunId);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Failed to delete the workflow run.");
    } finally {
      setRunLoading(false);
    }
  }

  return (
    <div className="shell tech-shell">
      <div className="shell-backdrop" />
      <AppHeader t={t} locale={locale} onLocaleChange={setLocale} summary={summary} />

      {bootstrapError ? <div className="banner error">{bootstrapError}</div> : null}

      {bootstrapping ? (
        <section className="stage-panel">
          <div className="empty-state">{t("common.loading")}</div>
        </section>
      ) : null}

      {!bootstrapping && (activeView === "launcher" || !selectedProject) ? (
        <ProjectStage
          t={t}
          projects={projects}
          recentProjects={recentProjects}
          projectRoots={projectRoots}
          browserRoot={browserRoot}
          browserEntries={browserEntries}
          browserLoading={browserLoading}
          browserError={browserError}
          selectedProject={selectedProject}
          manualProjectPath={manualProjectPath}
          onManualProjectPathChange={setManualProjectPath}
          onOpenProject={(path, source) => void handleOpenProject(path, source)}
          onPickProject={() => void handlePickProject()}
          onBrowseRoot={handleBrowseRoot}
          onOpenFromBrowser={(path) => void handleOpenFromBrowser(path)}
          pickerAvailable={Boolean(projectCapabilities?.native_picker_available)}
          runtime={runtime}
          runtimeLoading={runtimeLoading}
          runtimeError={runtimeError}
          onInitRuntime={() => void handleInitRuntime()}
          onMirrorRuntime={() => void handleMirrorRuntime()}
          onExportRuntime={() => void handleExportRuntime()}
          onImportRuntime={() => void handleImportRuntime()}
          mirrorLoading={mirrorLoading}
          mirrorResult={mirrorResult}
          mirrorError={mirrorError}
          sourceLabel={sourceLabel}
        />
      ) : null}

      {!bootstrapping && activeView === "workspace" && selectedProject ? (
        <WorkspaceStage
          t={t}
          selectedProject={selectedProject}
          runtime={runtime}
          runtimeLoading={runtimeLoading}
          runtimeError={runtimeError}
          mirrorLoading={mirrorLoading}
          mirrorResult={mirrorResult}
          mirrorError={mirrorError}
          recentProjects={recentProjects}
          projects={projects}
          sourceLabel={sourceLabel}
          runtimeStateLabel={runtimeStateLabel}
          activeSection={activeWorkspaceSection}
          onSectionChange={setActiveWorkspaceSection}
          onOpenProject={(path, source) => void handleOpenProject(path, source)}
          onOpenLauncher={handleOpenLauncher}
          onInitRuntime={() => void handleInitRuntime()}
          onMirrorRuntime={() => void handleMirrorRuntime()}
          onExportRuntime={() => void handleExportRuntime()}
          onImportRuntime={() => void handleImportRuntime()}
          buildContent={
            <BuildStage
              embedded
              t={t}
              selectedProject={selectedProject}
              task={task}
              allowNetwork={allowNetwork}
              allowInstalls={allowInstalls}
              plan={plan}
              loading={loading}
              runLoading={runLoading}
              planError={planError}
              runError={runError}
              backendLabel={backendLabel}
              executionLabel={executionLabel}
              agentRoleLabel={agentRoleLabel}
              onTaskChange={handleTaskChange}
              onAllowNetworkChange={handleAllowNetworkChange}
              onAllowInstallsChange={handleAllowInstallsChange}
              onDraftWorkflow={() => void handleDraftWorkflow()}
              onCreateRun={() => void handleCreateRun()}
            />
          }
          runContent={
            <RunStage
              embedded
              t={t}
              locale={locale}
              runs={runs}
              selectedRunId={selectedRunId}
              selectedRun={selectedRun}
              runArtifacts={runArtifacts}
              artifactLoading={artifactLoading}
              artifactError={artifactError}
              runLog={runLog}
              agentSessions={agentSessions}
              agentSessionsLoading={agentSessionsLoading}
              agentSessionsError={agentSessionsError}
              selectedArtifactKey={selectedArtifactKey}
              onSelectRun={(runId) => {
                setSelectedRunId(runId);
                setActiveWorkspaceSection("run");
              }}
              onSelectArtifact={setSelectedArtifactKey}
              onExecuteRun={(runId) => void handleExecuteRun(runId)}
              onCancelRun={(runId) => void handleCancelRun(runId)}
              onApproveRun={(runId, commandIds) => void handleApproveRun(runId, commandIds)}
              onResumeRun={(runId) => void handleResumeRun(runId)}
              onRetryRun={(runId) => void handleRetryRun(runId)}
              onDeleteRun={(runId) => void handleDeleteRun(runId)}
              runLoading={runLoading}
              runNeedsDangerousApproval={runNeedsDangerousApproval}
              runStatusNote={runStatusNote}
              backendLabel={backendLabel}
              agentRoleLabel={agentRoleLabel}
              statusLabel={statusLabel}
              formatDateTime={formatDateTime}
              memorySummary={memorySummary}
              finalizedStepCount={finalizedStepCount}
              readyArtifactCount={readyArtifactCount}
              writtenMemoryCount={writtenMemoryCount}
              recalledMemoryCount={recalledMemoryCount}
              promotedGlobalRuleCount={promotedGlobalRuleCount}
            />
          }
          diagnosticsContent={
            <DiagnosticsStage
              embedded
              t={t}
              queueDashboard={queueDashboard}
              queueLoading={queueLoading}
              queueError={queueError}
              queueItemNote={queueItemNote}
              queueModeLabel={queueModeLabel}
            />
          }
        />
      ) : null}
    </div>
  );
}
