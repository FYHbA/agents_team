import type { Locale, Translator } from "../i18n";
import type {
  WorkflowAgentSession,
  WorkflowAgentSessionEvent,
  WorkflowArtifactDocument,
  WorkflowCommandPreview,
  WorkflowRun,
} from "../types";

export type RunLedgerFilter = "all" | "attention" | "running" | "finished";

export type RunGroup = {
  key: string;
  label: string;
  runs: WorkflowRun[];
};

export type RunLedgerFilterItem = {
  key: RunLedgerFilter;
  label: string;
  count: number;
};

export type ChatCommandEvent = {
  id: string;
  label: string;
  command: string;
  status: string;
  output: string;
  exitCode: number | null;
  sequence: number;
};

export type ChatMessage = {
  id: string;
  stepId: string;
  agentRole: string;
  title: string;
  body: string;
  status: string;
  timestamp: string | null;
  backend: WorkflowRun["steps"][number]["backend"];
  provider: string | null;
  goal: string | null;
  dependsOn: string[];
  commandPreviews: WorkflowCommandPreview[];
  hasStructuredTimeline: boolean;
  thinkingMessages: string[];
  finalMessage: string | null;
  collapsedPreview: string | null;
  commandEvents: ChatCommandEvent[];
  events: WorkflowAgentSessionEvent[];
};

export type ChatActionItem = {
  label: string;
  value: string;
  meta?: string;
};

export type ChatTimeline = {
  hasStructuredEvents: boolean;
  thinkingMessages: string[];
  finalMessage: string | null;
  commands: ChatCommandEvent[];
};

export type RunSafetyState = {
  confirmableStepRuns: WorkflowRun["step_runs"];
  pendingDangerousCommands: WorkflowCommandPreview[];
  approvedDangerousCommands: WorkflowCommandPreview[];
};

export function compactText(value: string, maxLength = 96): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxLength - 3)).trimEnd()}...`;
}

export function formatCollapsedPreview(value: string, fallback: string): string {
  const normalized = value
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^#+\s*/gm, "")
    .replace(/`/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return compactText(normalized || fallback, 156);
}

export function avatarLabel(role: string): string {
  const labels: Record<string, string> = {
    planner: "PL",
    researcher: "RS",
    coder: "CD",
    "runner/tester": "VR",
    reviewer: "RV",
    summarizer: "RP",
  };
  return labels[role] ?? "AG";
}

export function avatarTone(role: string): string {
  const tones: Record<string, string> = {
    planner: "planner",
    researcher: "researcher",
    coder: "coder",
    "runner/tester": "runner",
    reviewer: "reviewer",
    summarizer: "summarizer",
  };
  return tones[role] ?? "default";
}

export function buildLedgerFilterItems(
  runs: WorkflowRun[],
  t: Translator,
  runNeedsDangerousApproval: (run: WorkflowRun | null) => boolean,
): RunLedgerFilterItem[] {
  return [
    { key: "all", label: t("run.filterAll"), count: runs.length },
    {
      key: "attention",
      label: t("run.filterAttention"),
      count: runs.filter((run) => runNeedsDangerousApproval(run) || run.status === "failed" || run.status === "cancelled").length,
    },
    {
      key: "running",
      label: t("run.filterRunning"),
      count: runs.filter((run) => run.status === "running" || run.status === "planned").length,
    },
    {
      key: "finished",
      label: t("run.filterFinished"),
      count: runs.filter((run) => isFinishedRun(run.status)).length,
    },
  ];
}

export function filterVisibleRuns(
  runs: WorkflowRun[],
  runFilter: RunLedgerFilter,
  normalizedRunQuery: string,
  runNeedsDangerousApproval: (run: WorkflowRun | null) => boolean,
): WorkflowRun[] {
  return runs.filter((run) => {
    const matchesFilter =
      runFilter === "all"
        ? true
        : runFilter === "attention"
        ? runNeedsDangerousApproval(run) || run.status === "failed" || run.status === "cancelled"
        : runFilter === "running"
        ? run.status === "running" || run.status === "planned"
        : isFinishedRun(run.status);

    if (!matchesFilter) {
      return false;
    }

    if (!normalizedRunQuery) {
      return true;
    }

    return [run.team_name, run.task, run.id].some((value) => value.toLowerCase().includes(normalizedRunQuery));
  });
}

export function groupRunsByDay(runs: WorkflowRun[]): RunGroup[] {
  const groups = new Map<string, WorkflowRun[]>();
  for (const run of runs) {
    const timestamp = run.started_at ?? run.created_at;
    const date = new Date(timestamp);
    const key = Number.isNaN(date.getTime())
      ? timestamp.slice(0, 10) || "unknown"
      : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    const existing = groups.get(key);
    if (existing) {
      existing.push(run);
    } else {
      groups.set(key, [run]);
    }
  }

  return Array.from(groups.entries()).map(([key, groupedRuns]) => ({
    key,
    label: formatRunGroupLabel(key),
    runs: groupedRuns,
  }));
}

export function buildRunSafetyState(selectedRun: WorkflowRun | null): RunSafetyState {
  const confirmableStepRuns =
    selectedRun?.step_runs.filter((stepRun) => stepRun.command_previews.some((preview) => preview.requires_confirmation)) ?? [];
  return {
    confirmableStepRuns,
    pendingDangerousCommands: confirmableStepRuns.flatMap((stepRun) =>
      stepRun.command_previews.filter((preview) => preview.requires_confirmation && !preview.confirmed_at),
    ),
    approvedDangerousCommands: confirmableStepRuns.flatMap((stepRun) =>
      stepRun.command_previews.filter((preview) => preview.requires_confirmation && preview.confirmed_at),
    ),
  };
}

export function buildChatMessages(
  agentSessions: WorkflowAgentSession[],
  selectedRun: WorkflowRun | null,
  chatPendingLabel: string,
): ChatMessage[] {
  const stepRunById = new Map(selectedRun?.step_runs.map((stepRun) => [stepRun.step_id, stepRun]) ?? []);

  if (agentSessions.length > 0) {
    return agentSessions.map((session) => ({
      stepId: session.step_id,
      goal: stepRunById.get(session.step_id)?.goal ?? null,
      dependsOn: stepRunById.get(session.step_id)?.depends_on ?? [],
      commandPreviews: stepRunById.get(session.step_id)?.command_previews ?? [],
      id: session.id,
      agentRole: session.agent_role,
      title: session.title,
      body: session.summary ?? session.error ?? chatPendingLabel,
      status: session.status,
      timestamp: session.completed_at ?? session.started_at,
      backend: session.backend,
      provider: session.provider,
      hasStructuredTimeline: session.has_structured_timeline,
      thinkingMessages: session.thinking_messages,
      finalMessage: session.final_message,
      collapsedPreview: session.collapsed_preview,
      commandEvents: session.commands.map((command) => ({
        id: command.id,
        label: command.label,
        command: command.command,
        status: command.status,
        output: command.output,
        exitCode: command.exit_code,
        sequence: command.sequence,
      })),
      events: session.events ?? [],
    }));
  }

  return (
    selectedRun?.step_runs.map((stepRun) => ({
      id: stepRun.step_id,
      stepId: stepRun.step_id,
      agentRole: stepRun.agent_role,
      title: stepRun.title,
      body: stepRun.summary ?? stepRun.goal ?? chatPendingLabel,
      status: stepRun.status,
      timestamp: stepRun.completed_at ?? stepRun.started_at,
      backend: stepRun.backend,
      provider: null,
      goal: stepRun.goal,
      dependsOn: stepRun.depends_on,
      commandPreviews: stepRun.command_previews,
      hasStructuredTimeline: false,
      thinkingMessages: [],
      finalMessage: null,
      collapsedPreview: null,
      commandEvents: [],
      events: [],
    })) ?? []
  );
}

export function buildChatProcessItems(
  message: ChatMessage,
  t: Translator,
  backendLabel: (backend: WorkflowRun["steps"][number]["backend"]) => string,
): ChatActionItem[] {
  const items: ChatActionItem[] = [];

  if (message.goal) {
    items.push({
      label: t("run.chatGoal"),
      value: message.goal,
    });
  }

  if (message.commandPreviews.length > 0) {
    for (const preview of message.commandPreviews) {
      const metaParts = [
        preview.argv.join(" "),
        preview.cwd ? `${t("run.commandCwd")}: ${preview.cwd}` : "",
        preview.scope_note ?? "",
      ].filter(Boolean);
      items.push({
        label: t("run.chatAction"),
        value: preview.label,
        meta: metaParts.join(" | "),
      });
    }
  } else {
    items.push({
      label: t("run.chatAction"),
      value: t("run.chatActionFallback", { stage: backendLabel(message.backend) }),
    });
  }

  if (message.dependsOn.length > 0) {
    items.push({
      label: t("run.chatDependsOn"),
      value: message.dependsOn.join(", "),
    });
  }

  if (message.provider) {
    items.push({
      label: t("run.chatProvider"),
      value: message.provider,
    });
  }

  return items;
}

export function buildChatTimeline(message: ChatMessage): ChatTimeline {
  if (message.hasStructuredTimeline) {
    return {
      hasStructuredEvents: true,
      thinkingMessages: message.thinkingMessages,
      finalMessage: message.finalMessage,
      commands: message.commandEvents,
    };
  }

  if (message.events.length === 0) {
    return {
      hasStructuredEvents: false,
      thinkingMessages: [],
      finalMessage: message.body || null,
      commands: [],
    };
  }

  const agentMessages: string[] = [];
  const commandMap = new Map<string, ChatCommandEvent>();

  for (const event of message.events) {
    if (event.event_type === "agent_message") {
      const text = typeof event.payload.text === "string" ? event.payload.text.trim() : "";
      if (text) {
        agentMessages.push(text);
      }
      continue;
    }

    if (event.event_type === "command_execution") {
      const commandId = typeof event.payload.command_id === "string" && event.payload.command_id ? event.payload.command_id : event.id;
      const existing = commandMap.get(commandId);
      commandMap.set(commandId, {
        id: commandId,
        label:
          typeof event.payload.label === "string" && event.payload.label
            ? event.payload.label
            : typeof event.payload.command === "string" && event.payload.command
            ? event.payload.command
            : "Shell command",
        command: typeof event.payload.command === "string" ? event.payload.command : existing?.command ?? "",
        status: normalizeCommandStatus(event.payload.status),
        output:
          typeof event.payload.output === "string" && event.payload.output
            ? event.payload.output
            : existing?.output ?? "",
        exitCode: typeof event.payload.exit_code === "number" ? event.payload.exit_code : existing?.exitCode ?? null,
        sequence: event.sequence,
      });
    }
  }

  const commands = Array.from(commandMap.values()).sort((left, right) => left.sequence - right.sequence);
  if (agentMessages.length === 0) {
    return {
      hasStructuredEvents: true,
      thinkingMessages: [],
      finalMessage: message.body || null,
      commands,
    };
  }

  if (message.status === "running") {
    return {
      hasStructuredEvents: true,
      thinkingMessages: agentMessages,
      finalMessage: null,
      commands,
    };
  }

  return {
    hasStructuredEvents: true,
    thinkingMessages: agentMessages.slice(0, -1),
    finalMessage: agentMessages[agentMessages.length - 1] ?? message.body ?? null,
    commands,
  };
}

export function buildChatFinalOutputDocument(
  message: ChatMessage,
  documents: Map<WorkflowArtifactDocument["key"], WorkflowArtifactDocument>,
  t: Translator,
  structuredFinalMessage: string | null,
): WorkflowArtifactDocument {
  const preferredKeysByRole: Record<string, WorkflowArtifactDocument["key"][]> = {
    planner: ["planning_brief"],
    researcher: ["project_snapshot", "memory_context"],
    coder: ["last_message", "changes"],
    "runner/tester": ["verification_brief", "parallel_branches"],
    reviewer: ["changes"],
    summarizer: ["report", "memory_context"],
  };

  const preferredKeys = preferredKeysByRole[message.agentRole] ?? [];
  for (const key of preferredKeys) {
    const document = documents.get(key);
    if (document?.available && document.content) {
      return document;
    }
  }

  if (structuredFinalMessage) {
    return {
      key: "last_message",
      title: t("run.chatInlineReply"),
      path: null,
      content_type: "text",
      available: true,
      content: structuredFinalMessage,
    };
  }

  return {
    key: "last_message",
    title: t("run.chatInlineReply"),
    path: null,
    content_type: "text",
    available: true,
    content: message.body,
  };
}

export function buildMachineOutputSummary(document: WorkflowArtifactDocument, locale: Locale): string | null {
  if (!document.available || !document.content) {
    return null;
  }

  if (document.content_type === "json") {
    return locale === "zh-CN"
      ? "这是工作流步骤之间传递的结构化合同，界面只补充导航和状态，下面保留原始字段。"
      : "This is a structured handoff contract between workflow steps. The UI adds navigation and status, while the exact fields stay raw below.";
  }

  const summaryByKey: Partial<Record<WorkflowArtifactDocument["key"], { zh: string; en: string }>> = {
    planning_brief: {
      zh: "这是本次运行的规划简报，正文保留原始输出，界面只补充本地化结构。",
      en: "This is the planning brief for the run. The original wording is preserved, and the UI only adds localized structure.",
    },
    report: {
      zh: "这是最终交接文档。正文可能保持原始语言，界面会用当前语言补足结构和定位。",
      en: "This is the final handoff document. The body may stay in its original language, while the UI frames it in the current locale.",
    },
    changes: {
      zh: "这里保留本轮改动总结的原文，适合结合步骤和状态卡一起交叉查看。",
      en: "This keeps the raw change summary from the run. It reads best alongside the step ledger and status cards.",
    },
    last_message: {
      zh: "这是该步骤记录下来的直接回复，可能混合中英文，界面不会改写原句。",
      en: "This is the step's direct reply. It may mix languages, and the UI keeps the original wording intact.",
    },
    project_snapshot: {
      zh: "这是调研阶段生成的项目快照，原文保留在下方，方便和后续实现结果对照。",
      en: "This is the research snapshot captured for the run. The original wording stays below for comparison with later implementation output.",
    },
    verification_brief: {
      zh: "这里保留验证阶段的原始结论和证据摘要，方便和 trace 互相校对。",
      en: "This preserves the verification stage's raw findings and evidence summary so you can cross-check it against the trace.",
    },
    parallel_branches: {
      zh: "这是并行验证分支的汇总结果，界面只补充结构，不改写各分支原始输出。",
      en: "This summarizes parallel verification branches. The UI adds structure without rewriting each branch's original output.",
    },
    memory_context: {
      zh: "这里展示本次运行召回或写回的记忆内容，正文保持原始记录。",
      en: "This shows the memory recalled or written during the run, with the original record preserved below.",
    },
  };

  const summary = summaryByKey[document.key];
  if (!summary) {
    return locale === "zh-CN"
      ? "下面保留这份运行产物的原始内容，界面只补充导航、状态和阅读结构。"
      : "The original artifact content is preserved below. The UI only adds navigation, status, and reading structure around it.";
  }

  return locale === "zh-CN" ? summary.zh : summary.en;
}

function isFinishedRun(status: WorkflowRun["status"]): boolean {
  return ["completed", "failed", "cancelled", "short_circuited"].includes(status);
}

function formatRunGroupLabel(key: string): string {
  const date = new Date(`${key}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return key;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

function normalizeCommandStatus(value: unknown): string {
  if (typeof value !== "string" || !value) {
    return "completed";
  }
  if (value === "in_progress") {
    return "running";
  }
  return value;
}
