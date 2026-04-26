import type { WorkflowPlan } from "../types";
import type { Translator } from "../i18n";

type BuildStageProps = {
  t: Translator;
  selectedProject: string;
  task: string;
  allowNetwork: boolean;
  allowInstalls: boolean;
  plan: WorkflowPlan | null;
  loading: boolean;
  runLoading: boolean;
  planError: string;
  runError: string;
  backendLabel: (backend: WorkflowPlan["steps"][number]["backend"]) => string;
  executionLabel: (execution: WorkflowPlan["steps"][number]["execution"]) => string;
  agentRoleLabel: (role: string) => string;
  onTaskChange: (value: string) => void;
  onAllowNetworkChange: (value: boolean) => void;
  onAllowInstallsChange: (value: boolean) => void;
  onDraftWorkflow: () => void;
  onCreateRun: () => void;
  embedded?: boolean;
};

export function BuildStage({
  t,
  selectedProject,
  task,
  allowNetwork,
  allowInstalls,
  plan,
  loading,
  runLoading,
  planError,
  runError,
  backendLabel,
  executionLabel,
  agentRoleLabel,
  onTaskChange,
  onAllowNetworkChange,
  onAllowInstallsChange,
  onDraftWorkflow,
  onCreateRun,
  embedded = false,
}: BuildStageProps) {
  const shouldShowTaskChecklist = task.trim().length < 8;
  const canDraft = task.trim().length >= 8;
  const canRun = canDraft && Boolean(selectedProject);
  const emphasizeRun = Boolean(plan);
  const checklistItems = [
    {
      label: t("build.checklistGoalLabel"),
      description: t("build.checklistGoalText"),
    },
    {
      label: t("build.checklistConstraintsLabel"),
      description: t("build.checklistConstraintsText"),
    },
    {
      label: t("build.checklistDoneLabel"),
      description: t("build.checklistDoneText"),
    },
  ];

  const content = (
    <>
      <div className="stage-intro">
        <div>
          <p className="eyebrow">{t("nav.build")}</p>
          <h2>{t("build.heading")}</h2>
          {!embedded ? <p>{t("build.description")}</p> : null}
        </div>
        {!embedded ? <span className="project-pill">{selectedProject || t("project.notSelected")}</span> : null}
      </div>

      <div className="build-stage-grid">
        <article className="glass-panel build-composer">
          <label className="field-group">
            <span>{t("build.taskLabel")}</span>
            <textarea
              value={task}
              onChange={(event) => onTaskChange(event.target.value)}
              rows={8}
              placeholder={t("build.taskPlaceholder")}
            />
          </label>
          <div className="field-hint-row">
            <span className="field-hint">{t("build.taskHint")}</span>
            {task.trim().length > 0 && task.trim().length < 8 ? (
              <span className="field-hint warning">{t("build.taskTooShort")}</span>
            ) : null}
          </div>
          {shouldShowTaskChecklist ? (
            <div className="build-task-guide">
              {checklistItems.map((item) => (
                <article key={item.label} className="summary-card build-guide-card">
                  <span className="meta-label">{item.label}</span>
                  <p>{item.description}</p>
                </article>
              ))}
            </div>
          ) : null}
          <div className="button-row build-action-row">
            <button
              type="button"
              className={emphasizeRun ? "secondary-button" : "primary-button"}
              onClick={onDraftWorkflow}
              disabled={loading || !canDraft}
            >
              {loading ? t("build.planLoading") : t("build.planButton")}
            </button>
            <button
              type="button"
              className={emphasizeRun ? "primary-button" : "secondary-button"}
              onClick={onCreateRun}
              disabled={runLoading || !canRun}
            >
              {runLoading ? t("build.runLoading") : t("build.runButton")}
            </button>
          </div>
          <details className="advanced-section">
            <summary>{t("build.advancedToggle")}</summary>
            <div className="advanced-section-body">
              <div className="toggle-row">
                <label>
                  <input type="checkbox" checked={allowNetwork} onChange={(event) => onAllowNetworkChange(event.target.checked)} />
                  {t("build.allowNetwork")}
                </label>
                <label>
                  <input type="checkbox" checked={allowInstalls} onChange={(event) => onAllowInstallsChange(event.target.checked)} />
                  {t("build.allowInstalls")}
                </label>
              </div>
              <p className="workflow-copy">{t("build.advancedDescription")}</p>
            </div>
          </details>
          {planError ? <div className="inline-error">{planError}</div> : null}
          {runError ? <div className="inline-error">{runError}</div> : null}
        </article>

        <article className="glass-panel build-plan-panel">
          <div className="panel-header">
            <h3>{t("build.planSummary")}</h3>
            <span>{plan?.team_name ?? t("common.waiting")}</span>
          </div>
          {plan ? (
            <>
              <p className="workflow-copy">{plan.summary}</p>
              <div className="agent-grid">
                {plan.agents.map((agent) => (
                  <article key={agent.role} className="agent-card">
                    <span className="agent-role">{agentRoleLabel(agent.role)}</span>
                    <strong>{agent.name}</strong>
                    <p>{agent.reason}</p>
                  </article>
                ))}
              </div>
              <div className="step-list">
                {plan.steps.map((step) => (
                  <article key={step.id} className="step-item">
                    <div className="step-header">
                      <strong>{step.title}</strong>
                      <span className={`step-mode ${step.execution}`}>{executionLabel(step.execution)}</span>
                    </div>
                    <p>{step.goal}</p>
                    <div className="step-meta">
                      <span>{agentRoleLabel(step.agent_role)}</span>
                      <span>{backendLabel(step.backend)}</span>
                      <span>{step.depends_on.length ? t("common.after", { steps: step.depends_on.join(", ") }) : t("common.entryStep")}</span>
                    </div>
                    {step.command_previews.length ? (
                      <div className="command-list compact-list">
                        {step.command_previews.map((preview) => (
                          <article key={`${step.id}-${preview.label}-${preview.argv.join(" ")}`} className="command-item">
                            <strong>{preview.label}</strong>
                            <code>{preview.argv.join(" ")}</code>
                            {preview.scope_note ? <span>{preview.scope_note}</span> : null}
                          </article>
                        ))}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
              <div className="guidance-grid">
                <article className="summary-card">
                  <span className="meta-label">{t("build.memoryPlanner")}</span>
                  <strong>{plan.memory_guidance.planner.length}</strong>
                  <p>{plan.memory_guidance.planner.join(" | ") || t("common.none")}</p>
                </article>
                <article className="summary-card">
                  <span className="meta-label">{t("build.memoryReviewer")}</span>
                  <strong>{plan.memory_guidance.reviewer.length}</strong>
                  <p>{plan.memory_guidance.reviewer.join(" | ") || t("common.none")}</p>
                </article>
                <article className="summary-card">
                  <span className="meta-label">{t("build.memoryReporter")}</span>
                  <strong>{plan.memory_guidance.reporter.length}</strong>
                  <p>{plan.memory_guidance.reporter.join(" | ") || t("common.none")}</p>
                </article>
              </div>
            </>
          ) : (
            <div className="build-plan-empty">
              <div className="empty-state">{t("build.planEmpty")}</div>
              <p className="workflow-copy">{t("build.taskHint")}</p>
            </div>
          )}
        </article>
      </div>
    </>
  );

  if (embedded) {
    return <div className="embedded-stage embedded-build-stage">{content}</div>;
  }

  return <section className="stage-panel">{content}</section>;
}
