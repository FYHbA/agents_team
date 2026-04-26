import { useDeferredValue, useMemo } from "react";

import type { Translator } from "../i18n";

type TraceLogViewerProps = {
  t: Translator;
  log: string;
  emptyLabel: string;
  formatDateTime: (value: string) => string;
};

type TraceEntry =
  | {
      kind: "message";
      id: string;
      timestamp: string | null;
      title: string;
      details: string[];
      summary: string | null;
    }
  | {
      kind: "stream";
      id: string;
      timestamp: string | null;
      title: string;
      stream: "stdout" | "stderr";
      raw: string;
      summary: TraceStreamSummary;
    };

type TraceStreamSummary = {
  totalEvents: number;
  commandCount: number;
  agentMessageCount: number;
  outputBlockCount: number;
  outputLineCount: number;
  commandPreviews: string[];
  agentPreviews: string[];
  plainPreviews: string[];
};

export function TraceLogViewer({ t, log, emptyLabel, formatDateTime }: TraceLogViewerProps) {
  const deferredLog = useDeferredValue(log);
  const entries = useMemo(() => parseTraceLog(deferredLog), [deferredLog]);
  const refreshing = deferredLog !== log;

  if (!log.trim()) {
    return <div className="empty-state">{emptyLabel}</div>;
  }

  return (
    <div className="trace-shell">
      <p className="workflow-copy">
        {refreshing ? `${t("common.refreshing")} ` : ""}
        {t("run.traceSummaryHint")}
      </p>
      {entries.length === 0 ? (
        <div className="empty-state">{emptyLabel}</div>
      ) : (
        entries.map((entry) =>
          entry.kind === "stream" ? (
            <article key={entry.id} className={`trace-entry trace-stream-entry ${entry.stream}`}>
              <div className="trace-entry-header">
                <div className="trace-entry-heading">
                  <strong>{entry.title || t("run.traceStreamUntitled")}</strong>
                  <div className="trace-entry-meta">
                    {entry.timestamp ? <span>{formatDateTime(entry.timestamp)}</span> : null}
                    <span className={`trace-stream-pill ${entry.stream}`}>{t(`run.traceStream.${entry.stream}`)}</span>
                  </div>
                </div>
              </div>

              <div className="trace-summary-grid">
                <article className="trace-stat-card">
                  <span className="meta-label">{t("run.traceEvents")}</span>
                  <strong>{entry.summary.totalEvents}</strong>
                </article>
                <article className="trace-stat-card">
                  <span className="meta-label">{t("run.traceCommands")}</span>
                  <strong>{entry.summary.commandCount}</strong>
                </article>
                <article className="trace-stat-card">
                  <span className="meta-label">{t("run.traceAgentUpdates")}</span>
                  <strong>{entry.summary.agentMessageCount}</strong>
                </article>
                <article className="trace-stat-card">
                  <span className="meta-label">{t("run.traceOutputBlocks")}</span>
                  <strong>{entry.summary.outputBlockCount}</strong>
                  <span>{t("run.traceOutputLines", { count: entry.summary.outputLineCount })}</span>
                </article>
              </div>

              {entry.summary.commandPreviews.length > 0 ? (
                <div className="trace-section">
                  <span className="meta-label">{t("run.traceCommands")}</span>
                  <ul className="trace-list">
                    {entry.summary.commandPreviews.map((preview) => (
                      <li key={`${entry.id}-${preview}`}>{preview}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {entry.summary.agentPreviews.length > 0 ? (
                <div className="trace-section">
                  <span className="meta-label">{t("run.traceAgentUpdates")}</span>
                  <ul className="trace-list">
                    {entry.summary.agentPreviews.map((preview) => (
                      <li key={`${entry.id}-${preview}`}>{preview}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {entry.summary.plainPreviews.length > 0 ? (
                <div className="trace-section">
                  <span className="meta-label">{t("run.tracePlainLines")}</span>
                  <ul className="trace-list">
                    {entry.summary.plainPreviews.map((preview) => (
                      <li key={`${entry.id}-${preview}`}>{preview}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <details className="trace-raw-details">
                <summary>{t("run.traceRawToggle", { stream: t(`run.traceStream.${entry.stream}`) })}</summary>
                <pre className="log-viewer trace-raw-log">{entry.raw}</pre>
              </details>
            </article>
          ) : (
            <article key={entry.id} className="trace-entry">
              <div className="trace-entry-header">
                <div className="trace-entry-heading">
                  <strong>{entry.title}</strong>
                  {entry.timestamp ? (
                    <div className="trace-entry-meta">
                      <span>{formatDateTime(entry.timestamp)}</span>
                    </div>
                  ) : null}
                </div>
              </div>

              {entry.summary ? <p className="workflow-copy">{entry.summary}</p> : null}

              {entry.details.length > 0 ? (
                <details className="trace-raw-details">
                  <summary>{t("run.traceEntryToggle", { count: entry.details.length })}</summary>
                  <pre className="log-viewer trace-raw-log">{entry.details.join("\n")}</pre>
                </details>
              ) : null}
            </article>
          ),
        )
      )}
    </div>
  );
}

function parseTraceLog(log: string): TraceEntry[] {
  const entries: TraceEntry[] = [];
  const lines = log.replace(/\r\n/g, "\n").split("\n");
  let index = 0;
  let entryId = 0;

  while (index < lines.length) {
    const line = lines[index];
    const timestampMatch = line.match(/^\[([^\]]+)\]\s+(.*)$/);

    if (!timestampMatch) {
      const looseLines: string[] = [];
      while (index < lines.length && !lines[index].match(/^\[([^\]]+)\]\s+(.*)$/)) {
        if (lines[index].trim()) {
          looseLines.push(lines[index]);
        }
        index += 1;
      }

      if (looseLines.length > 0) {
        entries.push({
          kind: "message",
          id: `trace-${entryId++}`,
          timestamp: null,
          title: "Context",
          details: looseLines,
          summary: compactTraceText(looseLines.join(" ")),
        });
      }
      continue;
    }

    const [, rawTimestamp, rawTitle] = timestampMatch;
    const timestamp = normalizeTraceTimestamp(rawTimestamp);
    const streamMatch = rawTitle.match(/^(.*)\s+(stdout|stderr):$/);
    index += 1;

    if (streamMatch) {
      const streamLines: string[] = [];
      while (index < lines.length && !lines[index].match(/^\[([^\]]+)\]\s+(.*)$/)) {
        streamLines.push(lines[index]);
        index += 1;
      }
      const raw = streamLines.join("\n");
      entries.push({
        kind: "stream",
        id: `trace-${entryId++}`,
        timestamp,
        title: streamMatch[1].trim(),
        stream: streamMatch[2] as "stdout" | "stderr",
        raw,
        summary: summarizeTraceStream(raw),
      });
      continue;
    }

    const detailLines: string[] = [];
    while (index < lines.length && !lines[index].match(/^\[([^\]]+)\]\s+(.*)$/)) {
      if (lines[index].trim()) {
        detailLines.push(lines[index]);
      }
      index += 1;
    }

    entries.push({
      kind: "message",
      id: `trace-${entryId++}`,
      timestamp,
      title: rawTitle,
      details: detailLines,
      summary: detailLines.length > 0 ? compactTraceText(detailLines.join(" ")) : null,
    });
  }

  return entries;
}

function summarizeTraceStream(raw: string): TraceStreamSummary {
  const lines = raw.split("\n").filter((line) => line.trim().length > 0);
  const commandPreviews: string[] = [];
  const agentPreviews: string[] = [];
  const plainPreviews: string[] = [];
  let totalEvents = 0;
  let commandCount = 0;
  let agentMessageCount = 0;
  let outputBlockCount = 0;
  let outputLineCount = 0;

  for (const line of lines) {
    try {
      const event = JSON.parse(line) as {
        type?: string;
        item?: {
          type?: string;
          text?: string;
          command?: string;
          aggregated_output?: string;
        };
      };
      totalEvents += 1;
      const item = event.item;
      if (!item) {
        continue;
      }

      if (item.type === "agent_message" && item.text) {
        agentMessageCount += 1;
        pushUnique(agentPreviews, compactTraceText(item.text, 160), 3);
      }

      if (item.type === "command_execution" && item.command) {
        commandCount += 1;
        pushUnique(commandPreviews, summarizeCommand(item.command), 4);
        if (item.aggregated_output) {
          outputBlockCount += 1;
          outputLineCount += item.aggregated_output.split("\n").filter((entry) => entry.trim().length > 0).length;
        }
      }
    } catch {
      pushUnique(plainPreviews, compactTraceText(line, 140), 3);
    }
  }

  return {
    totalEvents,
    commandCount,
    agentMessageCount,
    outputBlockCount,
    outputLineCount,
    commandPreviews,
    agentPreviews,
    plainPreviews,
  };
}

function summarizeCommand(command: string): string {
  const normalized = command.replace(/\s+/g, " ").trim();
  const inlinePowerShell = normalized.match(/-Command\s+'([^']+)'/i);
  const usefulCommand = inlinePowerShell?.[1] ?? normalized;
  return compactTraceText(usefulCommand, 120);
}

function normalizeTraceTimestamp(value: string): string {
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z$/.test(value)) {
    return value.replace(" ", "T");
  }
  return value;
}

function compactTraceText(value: string, maxLength = 220): string {
  const collapsed = value.replace(/\s+/g, " ").trim();
  if (collapsed.length <= maxLength) {
    return collapsed;
  }
  return `${collapsed.slice(0, Math.max(0, maxLength - 3)).trimEnd()}...`;
}

function pushUnique(target: string[], value: string, limit: number) {
  if (!value || target.includes(value) || target.length >= limit) {
    return;
  }
  target.push(value);
}
