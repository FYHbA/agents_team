import { useDeferredValue, useEffect, useMemo, useState } from "react";

import { ArtifactDocumentViewer, extractMarkdownOutline, parseMarkdown } from "./ArtifactDocumentViewer";
import { TraceLogViewer } from "./TraceLogViewer";
import {
  avatarLabel,
  avatarTone,
  buildChatFinalOutputDocument,
  buildChatMessages,
  buildChatProcessItems,
  buildChatTimeline,
  buildLedgerFilterItems,
  buildMachineOutputSummary,
  buildRunSafetyState,
  compactText,
  filterVisibleRuns,
  formatCollapsedPreview,
  groupRunsByDay,
} from "./runStageAdapters";
import type { ChatMessage, RunLedgerFilter } from "./runStageAdapters";
import type { Locale, Translator } from "../i18n";
import type {
  WorkflowAgentSession,
  WorkflowArtifactDocument,
  WorkflowRunContextAudits,
  WorkflowRun,
  WorkflowRunArtifacts,
} from "../types";

type RunDetailTab = "overview" | "artifacts" | "chat" | "trace";

type RunStageProps = {
  t: Translator;
  locale: Locale;
  runs: WorkflowRun[];
  selectedRunId: string;
  selectedRun: WorkflowRun | null;
  runArtifacts: WorkflowRunArtifacts | null;
  artifactLoading: boolean;
  artifactError: string;
  runLog: string;
  agentSessions: WorkflowAgentSession[];
  agentSessionsLoading: boolean;
  agentSessionsError: string;
  runContextAudits: WorkflowRunContextAudits | null;
  contextAuditsLoading: boolean;
  contextAuditError: string;
  selectedArtifactKey: WorkflowArtifactDocument["key"];
  onSelectRun: (runId: string) => void;
  onSelectArtifact: (key: WorkflowArtifactDocument["key"]) => void;
  onExecuteRun: (runId: string) => void;
  onCancelRun: (runId: string) => void;
  onApproveRun: (runId: string, commandIds?: string[]) => void;
  onResumeRun: (runId: string) => void;
  onRetryRun: (runId: string) => void;
  onDeleteRun: (runId: string) => void;
  runLoading: boolean;
  runNeedsDangerousApproval: (run: WorkflowRun | null) => boolean;
  runStatusNote: (run: WorkflowRun) => string | null;
  backendLabel: (backend: WorkflowRun["steps"][number]["backend"]) => string;
  agentRoleLabel: (role: string) => string;
  statusLabel: (status: string) => string;
  formatDateTime: (value: string) => string;
  finalizedStepCount: (run: WorkflowRun) => number;
  readyArtifactCount: (artifacts: WorkflowRunArtifacts | null) => number;
  writtenMemoryCount: (run: WorkflowRun | null) => number;
  recalledMemoryCount: (run: WorkflowRun | null) => number;
  promotedGlobalRuleCount: (run: WorkflowRun | null) => number;
  embedded?: boolean;
};

export function RunStage({
  t,
  locale,
  runs,
  selectedRunId,
  selectedRun,
  runArtifacts,
  artifactLoading,
  artifactError,
  runLog,
  agentSessions,
  agentSessionsLoading,
  agentSessionsError,
  runContextAudits,
  contextAuditsLoading,
  contextAuditError,
  selectedArtifactKey,
  onSelectRun,
  onSelectArtifact,
  onExecuteRun,
  onCancelRun,
  onApproveRun,
  onResumeRun,
  onRetryRun,
  onDeleteRun,
  runLoading,
  runNeedsDangerousApproval,
  runStatusNote,
  backendLabel,
  agentRoleLabel,
  statusLabel,
  formatDateTime,
  finalizedStepCount,
  readyArtifactCount,
  writtenMemoryCount,
  recalledMemoryCount,
  promotedGlobalRuleCount,
  embedded = false,
}: RunStageProps) {
  const [detailTab, setDetailTab] = useState<RunDetailTab>("overview");
  const [runQuery, setRunQuery] = useState("");
  const [runFilter, setRunFilter] = useState<RunLedgerFilter>("all");
  const [chatExpanded, setChatExpanded] = useState<Record<string, boolean>>({});
  const deferredRunQuery = useDeferredValue(runQuery);

  useEffect(() => {
    setDetailTab("overview");
    setChatExpanded({});
  }, [selectedRunId]);

  const selectedArtifact =
    runArtifacts?.documents.find((document) => document.key === selectedArtifactKey) ?? runArtifacts?.documents[0] ?? null;
  const artifactCount = readyArtifactCount(runArtifacts);
  const artifactTarget = runArtifacts?.documents.length ?? 0;
  const artifactDocuments = runArtifacts?.documents ?? [];
  const stepProgress = selectedRun ? `${finalizedStepCount(selectedRun)} / ${selectedRun.step_runs.length}` : "0 / 0";
  const recalledCount = recalledMemoryCount(selectedRun);
  const writtenCount = writtenMemoryCount(selectedRun);
  const promotedRuleCount = promotedGlobalRuleCount(selectedRun);
  const contextAuditCount = runContextAudits?.audits.length ?? 0;
  const contextAuditBytes = runContextAudits?.total_input_bytes ?? 0;
  const contextAuditForbidden = runContextAudits?.total_forbidden_source_attempts ?? 0;
  const contextAuditInputTokens = runContextAudits?.total_input_tokens ?? 0;
  const contextAuditCachedTokens = runContextAudits?.total_cached_tokens ?? 0;
  const contextAuditOutputTokens = runContextAudits?.total_output_tokens ?? 0;
  const selectedRunNeedsApproval = runNeedsDangerousApproval(selectedRun);
  const { confirmableStepRuns, pendingDangerousCommands, approvedDangerousCommands } = useMemo(
    () => buildRunSafetyState(selectedRun),
    [selectedRun],
  );
  const normalizedRunQuery = deferredRunQuery.trim().toLowerCase();
  const ledgerFilterItems = useMemo(
    () => buildLedgerFilterItems(runs, t, runNeedsDangerousApproval),
    [runs, t, runNeedsDangerousApproval],
  );
  const visibleRuns = useMemo(
    () => filterVisibleRuns(runs, runFilter, normalizedRunQuery, runNeedsDangerousApproval),
    [runs, runFilter, normalizedRunQuery, runNeedsDangerousApproval],
  );
  const runGroups = useMemo(() => groupRunsByDay(visibleRuns), [visibleRuns]);
  const selectedArtifactIndex = artifactDocuments.findIndex((document) => document.key === selectedArtifact?.key);
  const availableArtifactDocuments = artifactDocuments.filter((document) => document.available);
  const selectedAvailableArtifactIndex = availableArtifactDocuments.findIndex((document) => document.key === selectedArtifact?.key);
  const previousArtifact = selectedAvailableArtifactIndex > 0 ? availableArtifactDocuments[selectedAvailableArtifactIndex - 1] : null;
  const nextArtifact =
    selectedAvailableArtifactIndex >= 0 && selectedAvailableArtifactIndex < availableArtifactDocuments.length - 1
      ? availableArtifactDocuments[selectedAvailableArtifactIndex + 1]
      : null;
  const selectedArtifactBlocks = useMemo(
    () => (selectedArtifact?.content_type === "markdown" && selectedArtifact.content ? parseMarkdown(selectedArtifact.content) : []),
    [selectedArtifact?.content, selectedArtifact?.content_type],
  );
  const artifactOutline = useMemo(() => extractMarkdownOutline(selectedArtifactBlocks), [selectedArtifactBlocks]);
  const artifactKindLabel = selectedArtifact ? t(`run.artifactKind.${selectedArtifact.content_type}`) : "";
  const selectedArtifactSummary = selectedArtifact ? buildMachineOutputSummary(selectedArtifact, locale) : null;
  const artifactDocumentMap = useMemo(
    () => new Map(artifactDocuments.map((document) => [document.key, document])),
    [artifactDocuments],
  );
  const chatMessages = useMemo(
    () => buildChatMessages(agentSessions, selectedRun, t("run.chatPending")),
    [agentSessions, selectedRun, t],
  );

  function isChatExpanded(message: ChatMessage): boolean {
    if (Object.prototype.hasOwnProperty.call(chatExpanded, message.id)) {
      return chatExpanded[message.id];
    }
    return message.status === "running" || message.status === "failed" || message.status === "cancelled";
  }

  function toggleChatMessage(messageId: string) {
    setChatExpanded((current) => ({
      ...current,
      [messageId]: !current[messageId],
    }));
  }

  function requestDeleteRun(run: WorkflowRun) {
    const label = compactText(`${run.team_name} · ${run.task}`, 120);
    if (!window.confirm(t("run.deleteConfirm", { label }))) {
      return;
    }
    onDeleteRun(run.id);
  }

  const lifecycleNote = selectedRun
    ? selectedRun.error
      ? compactText(selectedRun.error, 140)
      : runStatusNote(selectedRun) ?? compactText(selectedRun.task, 140)
    : "";

  const content = (
    <>
      <div className="stage-intro">
        <div>
          <p className="eyebrow">{t("nav.run")}</p>
          <h2>{t("run.heading")}</h2>
          {!embedded ? <p>{t("run.description")}</p> : null}
        </div>
      </div>

      <div className="run-stage-layout">
        <article className="glass-panel run-ledger-panel">
          <div className="panel-header">
            <h3>{t("run.ledger")}</h3>
            <span>{runs.length}</span>
          </div>
          <p className="workflow-copy">
            {t("run.ledgerSummary", {
              visible: visibleRuns.length,
              total: runs.length,
            })}
          </p>
          <div className="run-ledger-tools">
            <input
              type="search"
              className="run-ledger-search"
              value={runQuery}
              placeholder={t("run.searchPlaceholder")}
              onChange={(event) => setRunQuery(event.target.value)}
            />
            <div className="run-filter-row">
              {ledgerFilterItems.map((filterItem) => (
                <button
                  key={filterItem.key}
                  type="button"
                  className={`detail-tab ${runFilter === filterItem.key ? "selected" : ""}`}
                  onClick={() => setRunFilter(filterItem.key)}
                >
                  {filterItem.label} <span>{filterItem.count}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="run-list">
            {runs.length === 0 ? (
              <div className="empty-state">{t("run.ledgerEmpty")}</div>
            ) : visibleRuns.length === 0 ? (
              <div className="empty-state">{t("run.ledgerEmptyFiltered")}</div>
            ) : (
              <div className="run-ledger-groups">
                {runGroups.map((group) => (
                  <section key={group.key} className="run-group">
                    <div className="run-group-header">
                      <span className="meta-label">{group.label}</span>
                      <span>{group.runs.length}</span>
                    </div>
                    <div className="run-list">
                      {group.runs.map((run) => {
                        const pendingDangerousApproval = runNeedsDangerousApproval(run);
                        return (
                          <article key={run.id} className={`run-item ${selectedRunId === run.id ? "selected" : ""}`}>
                            <button
                              type="button"
                              className="run-item-button"
                              onClick={() => onSelectRun(run.id)}
                              aria-pressed={selectedRunId === run.id}
                            >
                              <div className="step-header">
                                <strong>{run.team_name}</strong>
                                <span className={`step-mode ${run.status}`}>{statusLabel(run.status)}</span>
                              </div>
                              <p>{run.task}</p>
                              <div className="step-meta">
                                <span>{formatDateTime(run.started_at ?? run.created_at)}</span>
                                <span>{run.attempt_count > 1 ? `${t("run.attempt")} ${run.attempt_count}` : statusLabel(run.status)}</span>
                              </div>
                              {runStatusNote(run) ? <div className="run-note">{runStatusNote(run)}</div> : null}
                              {run.error ? <div className="inline-error">{run.error}</div> : null}
                            </button>
                            <div className="button-row run-item-actions">
                              {run.status === "planned" ? (
                                <>
                                  {pendingDangerousApproval ? (
                                    <button type="button" className="secondary-button" onClick={() => onApproveRun(run.id)} disabled={runLoading}>
                                      {t("run.approveDangerous")}
                                    </button>
                                  ) : (
                                    <button type="button" className="secondary-button" onClick={() => onExecuteRun(run.id)} disabled={runLoading}>
                                      {t("run.start")}
                                    </button>
                                  )}
                                  <button type="button" className="secondary-button" onClick={() => onCancelRun(run.id)} disabled={runLoading}>
                                    {t("run.cancel")}
                                  </button>
                                </>
                              ) : null}
                              {run.status === "running" ? (
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() => onCancelRun(run.id)}
                                  disabled={runLoading || Boolean(run.cancel_requested_at)}
                                >
                                  {run.cancel_requested_at ? t("run.cancelling") : t("run.cancelRun")}
                                </button>
                              ) : null}
                              {(run.status === "failed" || run.status === "cancelled" || run.status === "short_circuited") && !pendingDangerousApproval ? (
                                <>
                                  {run.status !== "short_circuited" ? (
                                    <button type="button" className="secondary-button" onClick={() => onResumeRun(run.id)} disabled={runLoading}>
                                      {t("run.resume")}
                                    </button>
                                  ) : null}
                                  <button type="button" className="secondary-button" onClick={() => onRetryRun(run.id)} disabled={runLoading}>
                                    {t("run.retry")}
                                  </button>
                                </>
                              ) : null}
                              {run.status !== "running" ? (
                                <button
                                  type="button"
                                  className="secondary-button danger-button"
                                  onClick={() => requestDeleteRun(run)}
                                  disabled={runLoading}
                                >
                                  {t("run.delete")}
                                </button>
                              ) : null}
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </div>
        </article>

        <article className="glass-panel run-detail-panel">
          {!selectedRun ? (
            <div className="empty-state">{t("run.detailEmpty")}</div>
          ) : (
            <>
              <div className="run-detail-header">
                <div className="run-detail-heading">
                  <div className="run-detail-title-row">
                    <h3>{selectedRun.team_name}</h3>
                    <span className={`step-mode ${selectedRun.status}`}>{statusLabel(selectedRun.status)}</span>
                  </div>
                  <p className="workflow-copy">{selectedRun.task}</p>
                </div>
                <div className="run-detail-side">
                  <div className="run-detail-meta">
                    <span>{selectedRun.id}</span>
                    <span>{selectedRun.completed_at ? formatDateTime(selectedRun.completed_at) : formatDateTime(selectedRun.created_at)}</span>
                  </div>
                  {selectedRun.status !== "running" ? (
                    <div className="run-detail-actions">
                      <button
                        type="button"
                        className="secondary-button danger-button"
                        onClick={() => requestDeleteRun(selectedRun)}
                        disabled={runLoading}
                      >
                        {t("run.delete")}
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="detail-tab-row">
                {(["overview", "artifacts", "chat", "trace"] as RunDetailTab[]).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={`detail-tab ${detailTab === tab ? "selected" : ""}`}
                    onClick={() => setDetailTab(tab)}
                  >
                    {t(`run.${tab === "artifacts" ? "artifactTab" : tab === "chat" ? "chatTab" : tab === "trace" ? "traceTab" : "overview"}`)}
                  </button>
                ))}
              </div>

              {detailTab === "overview" ? (
                <div className="detail-section">
                  <div className="summary-grid">
                    <article className="summary-card">
                      <span className="meta-label">{t("run.lifecycle")}</span>
                      <strong>{statusLabel(selectedRun.status)}</strong>
                      <p>{lifecycleNote}</p>
                    </article>
                    <article className="summary-card">
                      <span className="meta-label">{t("run.stepProgress")}</span>
                      <strong>{stepProgress}</strong>
                      <p>{selectedRun.step_runs.length}</p>
                    </article>
                    <article className="summary-card">
                      <span className="meta-label">{t("run.artifacts")}</span>
                      <strong>{artifactTarget ? `${artifactCount} / ${artifactTarget}` : t("common.none")}</strong>
                      <p className={artifactError ? "warning-copy" : undefined}>
                        {artifactError
                          ? compactText(artifactError, 140)
                          : artifactLoading
                          ? t("common.refreshing")
                          : t("run.artifactsHint", { count: artifactCount })}
                      </p>
                    </article>
                    <article className="summary-card">
                      <span className="meta-label">{t("run.safety")}</span>
                      <strong>
                        {selectedRun.requires_dangerous_command_confirmation
                          ? selectedRunNeedsApproval
                            ? t("run.safetyNeeded")
                            : t("run.safetyApproved")
                          : t("run.safetyNotRequired")}
                      </strong>
                      <p>{selectedRunNeedsApproval ? t("run.safetyNote") : (runStatusNote(selectedRun) ?? t("common.ready"))}</p>
                    </article>
                    {selectedRun.reuse_decision === "continue_with_delta" ? (
                      <article className="summary-card">
                        <span className="meta-label">{t("run.deltaScope")}</span>
                        <strong>{selectedRun.delta_scope?.verification_focus ?? t("common.none")}</strong>
                        <p>{selectedRun.delta_scope?.scope_summary ?? selectedRun.delta_hint ?? t("common.none")}</p>
                      </article>
                    ) : null}
                    <article className="summary-card">
                      <span className="meta-label">{t("run.memoryRecalled")}</span>
                      <strong>{recalledCount}</strong>
                      <p>{memoryOverviewCopy("recalled", recalledCount, locale, t("common.none"))}</p>
                    </article>
                    <article className="summary-card">
                      <span className="meta-label">{t("run.memoryWritten")}</span>
                      <strong>{writtenCount}</strong>
                      <p>{memoryOverviewCopy("written", writtenCount, locale, t("common.none"))}</p>
                    </article>
                    <article className="summary-card">
                      <span className="meta-label">{t("run.globalRules")}</span>
                      <strong>{promotedRuleCount}</strong>
                      <p>{memoryOverviewCopy("rules", promotedRuleCount, locale, t("run.globalRulesHint"))}</p>
                    </article>
                    <article className="summary-card">
                      <span className="meta-label">{t("run.trace")}</span>
                      <strong>{selectedRun.completed_at ? formatDateTime(selectedRun.completed_at) : t("status.running")}</strong>
                      <p>{t("run.traceHint")}</p>
                    </article>
                    <article className="summary-card">
                      <span className="meta-label">{t("run.contextAudit")}</span>
                      <strong>{contextAuditsLoading ? t("common.loading") : contextAuditCount}</strong>
                      <p>
                        {contextAuditError
                          ? contextAuditError
                          : t("run.contextAuditHint", {
                              bytes: contextAuditBytes,
                              forbidden: contextAuditForbidden,
                              inputTokens: contextAuditInputTokens,
                              cachedTokens: contextAuditCachedTokens,
                              outputTokens: contextAuditOutputTokens,
                            })}
                      </p>
                    </article>
                  </div>

                  <div className="panel-header">
                    <h3>{t("run.stepLedger")}</h3>
                    <span>{stepProgress}</span>
                  </div>
                  <div className="step-list">
                    {selectedRun.step_runs.map((stepRun) => {
                      const localizedStep = localizeStepCopy(stepRun.step_id, locale, stepRun.title, stepRun.goal);
                      return (
                        <article key={stepRun.step_id} className="step-item">
                          <div className="step-header">
                            <strong>{localizedStep.title}</strong>
                            <span className={`step-mode ${stepRun.status}`}>{statusLabel(stepRun.status)}</span>
                          </div>
                          <p>{localizedStep.goal}</p>
                          <div className="step-meta">
                            <span>{agentRoleLabel(stepRun.agent_role)}</span>
                            <span>{backendLabel(stepRun.backend)}</span>
                            <span>{stepRun.depends_on.length ? t("common.after", { steps: stepRun.depends_on.join(", ") }) : t("common.entryStep")}</span>
                          </div>
                          {stepRun.command_previews.length ? (
                            <div className="command-list compact-list">
                              {stepRun.command_previews.map((preview) => (
                                <article key={`${stepRun.step_id}-${preview.label}-${preview.argv.join(" ")}`} className="command-item">
                                  <strong>{preview.label}</strong>
                                  <code>{preview.argv.join(" ")}</code>
                                  {preview.cwd ? <span>{t("run.commandCwd")}: {preview.cwd}</span> : null}
                                  {preview.scope_note ? <span>{preview.scope_note}</span> : null}
                                </article>
                              ))}
                            </div>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>

                  {selectedRun.requires_dangerous_command_confirmation || selectedRun.codex_commands.length || selectedRun.warnings.length ? (
                    <div className="detail-subsection">
                      <div className="panel-header">
                        <h3>{t("run.safetyPreview")}</h3>
                        <span>{selectedRunNeedsApproval ? t("run.safetyNeeded") : t("run.safetyApproved")}</span>
                      </div>

                      {pendingDangerousCommands.length ? (
                        <div className="button-row">
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => onApproveRun(selectedRun.id, pendingDangerousCommands.map((preview) => preview.command_id))}
                            disabled={runLoading}
                          >
                            {t("run.approveRemaining", { count: pendingDangerousCommands.length })}
                          </button>
                        </div>
                      ) : null}

                      {confirmableStepRuns.length ? (
                        <div className="step-list">
                          {confirmableStepRuns.map((stepRun) => (
                            <article key={stepRun.step_id} className="step-item">
                              <div className="step-header">
                                <strong>{stepRun.title}</strong>
                                <span className={`step-mode ${stepRun.status}`}>{statusLabel(stepRun.status)}</span>
                              </div>
                              <p>{stepRun.goal}</p>
                              <div className="step-meta">
                                <span>{agentRoleLabel(stepRun.agent_role)}</span>
                                <span>{backendLabel(stepRun.backend)}</span>
                                <span>{stepRun.depends_on.length ? t("common.after", { steps: stepRun.depends_on.join(", ") }) : t("common.entryStep")}</span>
                              </div>
                              {stepRun.command_previews.length ? (
                                <div className="command-list compact-list">
                                  {stepRun.command_previews.map((preview) => (
                                    <article key={`${stepRun.step_id}-${preview.label}-${preview.argv.join(" ")}`} className="command-item">
                                      <strong>{preview.label}</strong>
                                      <span className="meta-label">
                                        {preview.confirmed_at ? t("run.commandApproved") : t("run.commandPending")}
                                      </span>
                                      <code>{preview.argv.join(" ")}</code>
                                      {preview.cwd ? <span>{t("run.commandCwd")}: {preview.cwd}</span> : null}
                                      {preview.scope_note ? <span>{preview.scope_note}</span> : null}
                                      {preview.confirmed_at ? <span>{t("run.commandApprovedAt")}: {formatDateTime(preview.confirmed_at)}</span> : null}
                                      {preview.requires_confirmation && !preview.confirmed_at ? (
                                        <div className="button-row">
                                          <button
                                            type="button"
                                            className="secondary-button"
                                            onClick={() => onApproveRun(selectedRun.id, [preview.command_id])}
                                            disabled={runLoading}
                                          >
                                            {t("run.approveCommand")}
                                          </button>
                                        </div>
                                      ) : null}
                                    </article>
                                  ))}
                                </div>
                              ) : null}
                            </article>
                          ))}
                        </div>
                      ) : (
                        <div className="empty-state">{t("run.safetyPreviewEmpty")}</div>
                      )}

                      {approvedDangerousCommands.length ? (
                        <div className="run-note">
                          {t("run.approvalSummary", {
                            approved: approvedDangerousCommands.length,
                            pending: pendingDangerousCommands.length,
                          })}
                        </div>
                      ) : null}

                      {selectedRun.codex_commands.length ? (
                        <div className="detail-subsection">
                          <div className="panel-header">
                            <h3>{t("run.commandPreview")}</h3>
                            <span>{selectedRun.codex_commands.length}</span>
                          </div>
                          <div className="command-list compact-list">
                            {selectedRun.codex_commands.map((command) => (
                              <article key={`${command.mode}-${command.argv.join(" ")}`} className="command-item">
                                <strong>{command.purpose}</strong>
                                <span className="meta-label">{command.mode}</span>
                                <code>{command.argv.join(" ")}</code>
                                {command.cwd ? <span>{t("run.commandCwd")}: {command.cwd}</span> : null}
                              </article>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {selectedRun.warnings.length ? (
                        <div className="detail-subsection">
                          <div className="panel-header">
                            <h3>{t("run.warningsHeading")}</h3>
                            <span>{selectedRun.warnings.length}</span>
                          </div>
                          <div className="command-list compact-list">
                            {selectedRun.warnings.map((warning) => (
                              <article key={warning} className="command-item">
                                <strong>{warning}</strong>
                              </article>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {detailTab === "artifacts" ? (
                <div className="detail-section">
                  {artifactError ? <div className="inline-error">{artifactError}</div> : null}
                  {selectedArtifact ? (
                    <div className="artifact-workspace">
                      <aside className="artifact-side-panel">
                        <div className="artifact-side-section">
                          <div className="panel-header">
                            <h3>{t("run.artifactCollection")}</h3>
                            <span>{artifactCount} / {artifactTarget}</span>
                          </div>
                          <p className="workflow-copy">
                            {t("run.artifactCollectionHint", {
                              available: artifactCount,
                              total: artifactTarget,
                            })}
                          </p>
                          <div className="artifact-nav-list">
                            {artifactDocuments.map((document) => (
                              <button
                                key={document.key}
                                type="button"
                                className={`artifact-nav-card ${selectedArtifact?.key === document.key ? "selected" : ""}`}
                                onClick={() => onSelectArtifact(document.key)}
                              >
                                <strong>{localizedArtifactTitle(document.key, document.title, locale)}</strong>
                                <span>{document.available ? t("common.ready") : t("common.waiting")}</span>
                              </button>
                            ))}
                          </div>
                        </div>

                        <div className="artifact-side-section">
                          <div className="panel-header">
                            <h3>{t("run.artifactOutline")}</h3>
                            <span>{artifactOutline.length}</span>
                          </div>
                          {artifactOutline.length === 0 ? (
                            <div className="empty-state">{t("run.artifactOutlineEmpty")}</div>
                          ) : (
                            <div className="artifact-outline-list">
                              {artifactOutline.map((item) => (
                                <button
                                  key={item.id}
                                  type="button"
                                  className="artifact-outline-button"
                                  style={{ paddingLeft: `${12 + Math.max(0, item.depth - 1) * 16}px` }}
                                  onClick={() => {
                                    const node = document.getElementById(item.id);
                                    node?.scrollIntoView({ behavior: "smooth", block: "start" });
                                  }}
                                >
                                  {item.text}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </aside>

                      <div className="artifact-detail-shell">
                        <div className="artifact-detail-header">
                          <div>
                            <span className="meta-label">{localizedArtifactTitle(selectedArtifact.key, selectedArtifact.title, locale)}</span>
                            <strong>{selectedArtifact.available ? t("common.ready") : t("common.waiting")}</strong>
                          </div>
                          <div className="artifact-detail-meta">
                            <span className={`step-mode ${selectedArtifact.available ? "completed" : "planned"}`}>
                              {selectedArtifact.available ? t("common.ready") : t("common.waiting")}
                            </span>
                            <span className="artifact-type-chip">{artifactKindLabel}</span>
                          </div>
                        </div>
                        <div className="artifact-reader-toolbar">
                          <span className="workflow-copy">
                            {t("run.artifactPosition", {
                              current: selectedArtifactIndex + 1,
                              total: artifactTarget,
                            })}
                          </span>
                          <div className="button-row">
                            <button
                              type="button"
                              className="secondary-button"
                              onClick={() => previousArtifact && onSelectArtifact(previousArtifact.key)}
                              disabled={!previousArtifact}
                            >
                              {t("run.previousArtifact")}
                            </button>
                            <button
                              type="button"
                              className="secondary-button"
                              onClick={() => nextArtifact && onSelectArtifact(nextArtifact.key)}
                              disabled={!nextArtifact}
                            >
                              {t("run.nextArtifact")}
                            </button>
                          </div>
                        </div>
                        {selectedArtifact.path ? (
                          <div className="artifact-path-shell">
                            <span className="meta-label">{t("run.artifactPathLabel")}</span>
                            <code className="artifact-path">{selectedArtifact.path}</code>
                          </div>
                        ) : null}
                        {selectedArtifactSummary ? (
                          <article className="machine-output-note">
                            <span className="meta-label">{localizedArtifactTitle(selectedArtifact.key, selectedArtifact.title, locale)}</span>
                            <p>{selectedArtifactSummary}</p>
                          </article>
                        ) : null}
                        <ArtifactDocumentViewer
                          document={selectedArtifact}
                          emptyLabel={t("run.artifactEmpty")}
                          blocks={selectedArtifactBlocks}
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="empty-state">{t("run.artifactEmpty")}</div>
                  )}
                </div>
              ) : null}

              {detailTab === "chat" ? (
                <div className="detail-section">
                  <div className="panel-header">
                    <h3>{t("run.chatHeading")}</h3>
                    <span>{chatMessages.length}</span>
                  </div>
                  {agentSessionsError ? <div className="inline-error">{agentSessionsError}</div> : null}
                  <div className="chat-room-shell">
                    <p className="workflow-copy">{t("run.chatHint")}</p>
                    <div className="chat-thread chat-scroll-frame">
                    {agentSessionsLoading ? (
                      <div className="empty-state">{t("run.agentSessionsLoading")}</div>
                    ) : chatMessages.length === 0 ? (
                      <div className="empty-state">{t("run.chatEmpty")}</div>
                    ) : (
                      chatMessages.map((message) => {
                        const expanded = isChatExpanded(message);
                        const processItems = buildChatProcessItems(message, t, backendLabel);
                        const timeline = buildChatTimeline(message);
                        const finalOutputDocument = buildChatFinalOutputDocument(message, artifactDocumentMap, t, timeline.finalMessage);
                        const finalOutputSummary = buildMachineOutputSummary(finalOutputDocument, locale);
                        const collapsedMessageCount = processItems.length + timeline.thinkingMessages.length + timeline.commands.length + 1;
                        const localizedStep = localizeStepCopy(message.stepId, locale, message.title, message.goal);
                        const collapsedPreview = formatCollapsedPreview(
                          message.collapsedPreview ?? timeline.finalMessage ?? message.body,
                          localizedStep.goal || t("run.chatPending"),
                        );
                        return (
                          <article key={message.id} className={`chat-message chat-turn ${message.status} ${expanded ? "expanded" : "collapsed"}`}>
                            <div className="chat-rail">
                              <div className={`chat-avatar ${avatarTone(message.agentRole)}`}>{avatarLabel(message.agentRole)}</div>
                            </div>
                            <div className="chat-turn-main">
                              <div className="chat-bubble">
                                <div className="chat-meta">
                                  <div className="chat-meta-leading">
                                    <button
                                      type="button"
                                      className={`chat-toggle-button chat-toggle-button-inline ${expanded ? "expanded" : "collapsed"}`}
                                      onClick={() => toggleChatMessage(message.id)}
                                      aria-expanded={expanded}
                                      aria-label={expanded ? t("run.chatCollapse") : t("run.chatExpand")}
                                    >
                                      <span className="chat-toggle-glyph" aria-hidden="true" />
                                    </button>
                                    <strong>{agentRoleLabel(message.agentRole)}</strong>
                                  </div>
                                  <span>{message.timestamp ? formatDateTime(message.timestamp) : t("common.waiting")}</span>
                                </div>
                                <div className="chat-title-row">
                                  <span className="chat-title">{localizedStep.title}</span>
                                  <span className={`step-mode ${message.status}`}>{statusLabel(message.status)}</span>
                                </div>
                                <div className="chat-body-shell">
                                  {expanded ? (
                                    <div className="chat-expanded-shell">
                                      <div className="chat-expanded-stack">
                                        {timeline.thinkingMessages.length > 0 ? (
                                          <details className="chat-thinking-shell" open={message.status === "running"}>
                                            <summary className="chat-inline-summary">
                                              <span>{message.status === "running" ? t("run.chatThinkingLive") : t("run.chatThinkingDone")}</span>
                                              <span className="chat-inline-count">{t("run.chatThinkingSummary", { count: timeline.thinkingMessages.length })}</span>
                                            </summary>
                                            <div className="chat-thinking-list">
                                              {timeline.thinkingMessages.map((thought, thoughtIndex) => (
                                                <article key={`${message.id}-thought-${thoughtIndex}`} className="chat-thinking-item">
                                                  <span className="meta-label">{t("run.chatThinkingLabel")}</span>
                                                  <p>{thought}</p>
                                                </article>
                                              ))}
                                            </div>
                                          </details>
                                        ) : null}
                                        {timeline.commands.length > 0 ? (
                                          <details className="chat-command-shell">
                                            <summary className="chat-inline-summary">
                                              <span>{t("run.chatCommandSummary", { count: timeline.commands.length })}</span>
                                              <span className="chat-inline-count">{t("run.chatCommandCount", { count: timeline.commands.length })}</span>
                                            </summary>
                                            <div className="chat-command-list">
                                              {timeline.commands.map((command) => (
                                                <article key={`${message.id}-${command.id}-${command.sequence}`} className="chat-command-item">
                                                  <div className="chat-command-meta">
                                                    <strong>{command.label}</strong>
                                                    <span className={`step-mode ${command.status === "failed" ? "failed" : command.status === "completed" ? "completed" : "running"}`}>
                                                      {statusLabel(command.status === "cancelled" ? "cancelled" : command.status === "failed" ? "failed" : command.status === "running" ? "running" : "completed")}
                                                    </span>
                                                  </div>
                                                  <code>{command.command}</code>
                                                  {command.output ? (
                                                    <details className="chat-command-output">
                                                      <summary>{t("run.chatCommandOutput")}</summary>
                                                      <pre className="log-viewer trace-raw-log">{command.output}</pre>
                                                    </details>
                                                  ) : null}
                                                </article>
                                              ))}
                                            </div>
                                          </details>
                                        ) : null}
                                        <div className="chat-preview-block">
                                          <div className="chat-output-header">
                                            <span className="meta-label">{t("run.chatFinalOutput")}</span>
                                            <span>{localizedArtifactTitle(finalOutputDocument.key, finalOutputDocument.title, locale)}</span>
                                          </div>
                                          {finalOutputSummary ? (
                                            <article className="machine-output-note compact">
                                              <p>{finalOutputSummary}</p>
                                            </article>
                                          ) : null}
                                          <div className="chat-output-viewer">
                                            <ArtifactDocumentViewer document={finalOutputDocument} emptyLabel={t("run.chatPending")} />
                                          </div>
                                        </div>
                                      </div>
                                    </div>
                                  ) : (
                                    <div className="chat-collapsed-summary">
                                      <div className="chat-collapsed-row">
                                        <p className="chat-collapsed-preview">{collapsedPreview}</p>
                                        <div className="chat-collapsed-meta">
                                          <span className="chat-collapsed-chip">{statusLabel(message.status)}</span>
                                          <span className="chat-collapsed-chip">{t("run.chatCollapsedCount", { count: collapsedMessageCount })}</span>
                                          {timeline.thinkingMessages.length > 0 ? (
                                            <span className="chat-collapsed-chip">{t("run.chatThinkingSummary", { count: timeline.thinkingMessages.length })}</span>
                                          ) : null}
                                          {timeline.commands.length > 0 ? (
                                            <span className="chat-collapsed-chip">{t("run.chatCommandCount", { count: timeline.commands.length })}</span>
                                          ) : null}
                                        </div>
                                      </div>
                                    </div>
                                  )}
                                </div>
                                <div className="chat-submeta">
                                  <span>{backendLabel(message.backend)}</span>
                                  {message.provider ? <span>{message.provider}</span> : null}
                                </div>
                              </div>
                              {expanded ? (
                                <div className="chat-process-panel open">
                                  <div className="chat-process-section">
                                    <span className="meta-label">{t("run.chatProcessHeading")}</span>
                                    <div className="chat-process-list">
                                      {processItems.map((item) => (
                                        <article key={`${message.id}-${item.label}-${item.value}`} className="chat-process-item">
                                          <span className="meta-label">{item.label}</span>
                                          <strong>{item.value}</strong>
                                          {item.meta ? <span>{item.meta}</span> : null}
                                        </article>
                                      ))}
                                    </div>
                                  </div>
                                </div>
                              ) : null}
                            </div>
                          </article>
                        );
                      })
                    )}
                    </div>
                  </div>
                </div>
              ) : null}

              {detailTab === "trace" ? (
                <div className="detail-section">
                  <TraceLogViewer t={t} log={runLog} emptyLabel={t("run.traceEmpty")} formatDateTime={formatDateTime} />
                </div>
              ) : null}
            </>
          )}
        </article>
      </div>
    </>
  );

  if (embedded) {
    return <div className="embedded-stage embedded-run-stage">{content}</div>;
  }

  return <section className="stage-panel">{content}</section>;
}

function localizeStepCopy(stepId: string, locale: Locale, fallbackTitle: string, fallbackGoal: string | null): { title: string; goal: string } {
  const localized = STEP_COPY[stepId];
  const variant = locale === "zh-CN" ? localized?.zh : localized?.en;
  return {
    title: variant?.title ?? fallbackTitle,
    goal: variant?.goal ?? fallbackGoal ?? "",
  };
}

function localizedArtifactTitle(key: WorkflowArtifactDocument["key"], fallbackTitle: string, locale: Locale): string {
  const localized = ARTIFACT_TITLES[key];
  if (!localized) {
    return fallbackTitle;
  }
  return locale === "zh-CN" ? localized.zh : localized.en;
}

function memoryOverviewCopy(kind: "recalled" | "written" | "rules", count: number, locale: Locale, emptyLabel: string): string {
  if (count <= 0) {
    return emptyLabel;
  }
  if (locale === "zh-CN") {
    if (kind === "recalled") {
      return "这次运行带上了已有的项目或全局记忆。";
    }
    if (kind === "written") {
      return "这次运行写回了新的项目或全局记忆。";
    }
    return "这次运行沉淀了可复用的全局规则。";
  }
  if (kind === "recalled") {
    return "This run started with recalled project or global memory.";
  }
  if (kind === "written") {
    return "This run wrote new project or global memory back to the workspace.";
  }
  return "This run promoted reusable global rules.";
}

const STEP_COPY: Record<string, { zh: { title: string; goal: string }; en: { title: string; goal: string } }> = {
  plan: {
    zh: { title: "规划这次执行", goal: "把需求拆成清晰步骤、审批点和产物预期。" },
    en: { title: "Plan the run", goal: "Break the request into clear stages, approvals, and expected artifacts." },
  },
  research: {
    zh: { title: "检查代码和上下文", goal: "先补齐必要上下文，再进入实现，避免盲改。" },
    en: { title: "Inspect code and context", goal: "Collect enough context before implementation so the edits stay grounded." },
  },
  implement: {
    zh: { title: "直接修改文件", goal: "直接在目标项目里完成需要的改动。" },
    en: { title: "Edit files directly", goal: "Make the requested changes in the target project." },
  },
  verify: {
    zh: { title: "运行检查与实验", goal: "运行最相关的测试、脚本或命令检查，确认结果可用。" },
    en: { title: "Run checks and experiments", goal: "Run the most relevant tests, scripts, or checks for the task." },
  },
  verify_tests: {
    zh: { title: "运行回归测试", goal: "验证这次改动没有破坏已有行为。" },
    en: { title: "Run regression tests", goal: "Verify that the change does not break existing behavior." },
  },
  verify_build: {
    zh: { title: "运行构建与补充检查", goal: "补足构建、矩阵或补充校验，确认结果更稳。" },
    en: { title: "Run build and matrix checks", goal: "Run build or supplemental matrix checks when they help confirm the result." },
  },
  review: {
    zh: { title: "审查结果", goal: "检查质量、回归风险和遗漏的边界情况。" },
    en: { title: "Review the result", goal: "Inspect quality, regression risk, and missing edge cases before handoff." },
  },
  report: {
    zh: { title: "生成交接报告", goal: "整理改动、结果、后续事项和复现命令，但不自动提交 Git。" },
    en: { title: "Produce handoff report", goal: "Summarize changes, outcomes, follow-ups, and reproduction commands without auto-committing Git." },
  },
};

const ARTIFACT_TITLES: Partial<Record<WorkflowArtifactDocument["key"], { zh: string; en: string }>> = {
  planning_brief: { zh: "规划简报", en: "Planning brief" },
  report: { zh: "最终交接", en: "Final report" },
  changes: { zh: "变更摘要", en: "Change summary" },
  last_message: { zh: "最后回复", en: "Final message" },
  project_snapshot: { zh: "项目快照", en: "Project snapshot" },
  verification_brief: { zh: "验证简报", en: "Verification brief" },
  parallel_branches: { zh: "并行分支", en: "Parallel branches" },
  memory_context: { zh: "运行记忆", en: "Workflow memory" },
  research_result: { zh: "调研合约", en: "Research contract" },
  verify_summary: { zh: "验证合约", en: "Verify contract" },
  review_result: { zh: "审查合约", en: "Review contract" },
  final_state: { zh: "终态合约", en: "Final-state contract" },
};
