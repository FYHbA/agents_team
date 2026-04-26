import { useMemo, useState } from "react";
import type { ChangeEvent } from "react";

import type { Translator } from "../i18n";
import type {
  ProjectRecord,
  ProjectRootEntry,
  ProjectRuntime,
  ProjectRuntimeMirrorResult,
  ProjectTreeEntry,
  RecentProjectRecord,
} from "../types";

type ProjectStageProps = {
  t: Translator;
  projects: ProjectRecord[];
  recentProjects: RecentProjectRecord[];
  projectRoots: ProjectRootEntry[];
  browserRoot: string;
  browserEntries: ProjectTreeEntry[];
  browserLoading: boolean;
  browserError: string;
  selectedProject: string;
  manualProjectPath: string;
  onManualProjectPathChange: (value: string) => void;
  onOpenProject: (path: string, source?: "manual" | "picker" | "codex-config" | "filesystem") => void;
  onPickProject: () => void;
  onBrowseRoot: (path: string) => void;
  onOpenFromBrowser: (path: string) => void;
  pickerAvailable: boolean;
  runtime: ProjectRuntime | null;
  runtimeLoading: boolean;
  runtimeError: string;
  onInitRuntime: () => void;
  onMirrorRuntime: () => void;
  onExportRuntime: () => void;
  onImportRuntime: () => void;
  mirrorLoading: boolean;
  mirrorResult: ProjectRuntimeMirrorResult | null;
  mirrorError: string;
  sourceLabel: (source: ProjectRecord["source"]) => string;
};

export function ProjectStage({
  t,
  projects,
  recentProjects,
  projectRoots,
  browserRoot,
  browserEntries,
  browserLoading,
  browserError,
  selectedProject,
  manualProjectPath,
  onManualProjectPathChange,
  onOpenProject,
  onPickProject,
  onBrowseRoot,
  onOpenFromBrowser,
  pickerAvailable,
  runtime,
  runtimeLoading,
  runtimeError,
  onInitRuntime,
  onMirrorRuntime,
  onExportRuntime,
  onImportRuntime,
  mirrorLoading,
  mirrorResult,
  mirrorError,
  sourceLabel,
}: ProjectStageProps) {
  const [browserQuery, setBrowserQuery] = useState("");
  const recentWithoutSelected = recentProjects.filter((project) => project.path !== selectedProject).slice(0, 6);
  const hasRecentProjects = recentWithoutSelected.length > 0;
  const discoveredProjects = projects.filter((project) => project.path !== selectedProject).slice(0, 8);
  const browserCrumbs = useMemo(() => buildPathCrumbs(browserRoot), [browserRoot]);
  const browserParentPath = browserCrumbs.length > 1 ? browserCrumbs[browserCrumbs.length - 2]?.path ?? "" : "";
  const filteredBrowserEntries = useMemo(() => {
    const query = browserQuery.trim().toLowerCase();
    if (!query) {
      return browserEntries;
    }
    return browserEntries.filter((entry) => entry.name.toLowerCase().includes(query) || entry.path.toLowerCase().includes(query));
  }, [browserEntries, browserQuery]);

  return (
    <section className="stage-panel launcher-stage">
      <div className="stage-intro">
        <div>
          <p className="eyebrow">{t("nav.project")}</p>
          <h2>{t("project.heading")}</h2>
          <p>{t("project.description")}</p>
        </div>
      </div>

      <div className="launcher-primary-grid">
        <article className="glass-panel launcher-primary-card">
          <div className="panel-header">
            <h3>{t("project.openingHeading")}</h3>
            <span>{selectedProject ? t("project.openingReady") : t("project.openingPending")}</span>
          </div>
          <p className="launcher-lead">{t("project.openingDescription")}</p>
          <label className="field-group">
            <span>{t("project.manualLabel")}</span>
            <div className="path-entry-row">
              <input
                type="text"
                value={manualProjectPath}
                placeholder={t("project.manualPlaceholder")}
                onChange={(event: ChangeEvent<HTMLInputElement>) => onManualProjectPathChange(event.target.value)}
              />
              <button
                type="button"
                className="primary-button"
                onClick={() => onOpenProject(manualProjectPath, "manual")}
                disabled={!manualProjectPath.trim()}
              >
                {t("project.openPath")}
              </button>
            </div>
          </label>
          <p className="field-hint">{t("project.manualHint")}</p>
          <div className="button-row">
            {pickerAvailable ? (
              <button type="button" className="secondary-button" onClick={onPickProject}>
                {t("project.pickFolder")}
              </button>
            ) : (
              <span className="inline-note">{t("project.pickFolderUnavailableHint")}</span>
            )}
            {selectedProject ? (
              <span className="project-pill" title={selectedProject}>
                {compactPath(selectedProject)}
              </span>
            ) : null}
          </div>
          {runtimeError ? <div className="inline-error">{runtimeError}</div> : null}
        </article>

        <article className={`glass-panel launcher-secondary-card ${hasRecentProjects ? "" : "launcher-secondary-empty"}`}>
          <div className="panel-header">
            <h3>{hasRecentProjects ? t("project.recent") : t("project.firstUseHeading")}</h3>
            <span>{hasRecentProjects ? recentWithoutSelected.length : t("project.firstUseBadge")}</span>
          </div>
          {hasRecentProjects ? (
            <div className="project-card-list">
              {recentWithoutSelected.map((project) => (
                <button key={project.path} type="button" className="project-card" onClick={() => onOpenProject(project.path, "filesystem")}>
                  <strong>{project.path}</strong>
                  <span className="recent-project-meta">{formatRecentProjectDate(project.updated_at)}</span>
                </button>
              ))}
            </div>
          ) : (
            <>
              <p className="launcher-lead">{t("project.firstUseDescription")}</p>
              <div className="launcher-tip-list">
                {[t("project.tipPaste"), pickerAvailable ? t("project.tipPicker") : t("project.tipBrowser"), t("project.tipOneProject")].map(
                  (tip, index) => (
                    <article key={tip} className="launcher-tip-item">
                      <span className="launcher-tip-index">{index + 1}</span>
                      <p>{tip}</p>
                    </article>
                  ),
                )}
              </div>
            </>
          )}
        </article>
      </div>

      <details className="glass-panel launcher-advanced">
        <summary>{t("project.moreOptions")}</summary>
        <div className="launcher-advanced-grid">
          <article className="launcher-advanced-section">
            <div className="panel-header">
              <h3>{t("project.browser")}</h3>
              <span>{browserLoading ? t("common.loading") : browserRoot || t("common.waiting")}</span>
            </div>
            <div className="workspace-header-actions browser-toolbar">
              <button type="button" className="secondary-button" onClick={() => onBrowseRoot(browserParentPath)} disabled={!browserParentPath}>
                {t("project.browserUp")}
              </button>
              <input
                type="text"
                value={browserQuery}
                placeholder={t("project.browserSearchPlaceholder")}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setBrowserQuery(event.target.value)}
              />
            </div>
            <div className="button-row">
              {projectRoots.map((root) => (
                <button key={root.path} type="button" className="secondary-button" onClick={() => onBrowseRoot(root.path)}>
                  {root.name}
                </button>
              ))}
            </div>
            <div className="breadcrumb-row">
              {browserCrumbs.map((crumb) => (
                <button
                  key={crumb.path}
                  type="button"
                  className={`breadcrumb-chip ${crumb.path === browserRoot ? "active" : ""}`}
                  onClick={() => onBrowseRoot(crumb.path)}
                >
                  {crumb.label}
                </button>
              ))}
            </div>
            {browserError ? <div className="inline-error">{browserError}</div> : null}
            <div className="project-card-list compact-list launcher-browser-list">
              {filteredBrowserEntries.length === 0 ? (
                <div className="empty-state">{browserLoading ? t("common.loading") : t("project.browserEmpty")}</div>
              ) : (
                filteredBrowserEntries.map((entry) => (
                  <button
                    key={entry.path}
                    type="button"
                    className="project-card"
                    onClick={() => (entry.entry_type === "directory" ? onBrowseRoot(entry.path) : onOpenFromBrowser(entry.path))}
                  >
                    <strong>{entry.name}</strong>
                    <span>{entry.path}</span>
                  </button>
                ))
              )}
            </div>
          </article>

          <article className="launcher-advanced-section">
            <div className="panel-header">
              <h3>{t("project.discovered")}</h3>
              <span>{discoveredProjects.length}</span>
            </div>
            <div className="project-card-list compact-list launcher-discovered-list">
              {discoveredProjects.length === 0 ? (
                <div className="empty-state">{t("project.noneDiscovered")}</div>
              ) : (
                discoveredProjects.map((project) => (
                  <button
                    key={project.path}
                    type="button"
                    className="project-card"
                    onClick={() => onOpenProject(project.path, project.source)}
                  >
                    <strong>{project.path}</strong>
                    <span>{sourceLabel(project.source)}</span>
                  </button>
                ))
              )}
            </div>
          </article>
        </div>
      </details>
    </section>
  );
}

function buildPathCrumbs(path: string): Array<{ label: string; path: string }> {
  if (!path) {
    return [];
  }

  if (/^[A-Za-z]:[\\/]/.test(path)) {
    const normalized = path.replace(/\//g, "\\");
    const drive = normalized.slice(0, 2);
    const parts = normalized.slice(3).split("\\").filter(Boolean);
    const crumbs = [{ label: drive, path: `${drive}\\` }];
    let current = `${drive}\\`;
    for (const part of parts) {
      current = current.endsWith("\\") ? `${current}${part}` : `${current}\\${part}`;
      crumbs.push({ label: part, path: current });
    }
    return crumbs;
  }

  const parts = path.split("/").filter(Boolean);
  const crumbs = [{ label: "/", path: "/" }];
  let current = "";
  for (const part of parts) {
    current = `${current}/${part}`;
    crumbs.push({ label: part, path: current });
  }
  return crumbs;
}

function formatRecentProjectDate(value: string): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function compactPath(path: string, limit = 44): string {
  if (path.length <= limit) {
    return path;
  }
  const visible = Math.max(8, Math.floor((limit - 3) / 2));
  return `${path.slice(0, visible)}...${path.slice(-visible)}`;
}
