import type { ReactNode } from "react";

import type { WorkflowArtifactDocument } from "../types";

type ArtifactDocumentViewerProps = {
  document: WorkflowArtifactDocument;
  emptyLabel: string;
  blocks?: MarkdownBlock[];
};

export type MarkdownBlock =
  | { type: "heading"; depth: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "code"; language: string; content: string }
  | { type: "blockquote"; lines: string[] }
  | { type: "rule" };

export type MarkdownHeadingOutline = {
  id: string;
  depth: number;
  text: string;
};

const HORIZONTAL_RULE_RE = /^-{3,}$/;
const UNORDERED_LIST_RE = /^[-*+]\s+/;
const ORDERED_LIST_RE = /^\d+\.\s+/;

export function ArtifactDocumentViewer({ document, emptyLabel, blocks: providedBlocks }: ArtifactDocumentViewerProps) {
  if (!document.content) {
    return <div className="empty-state">{emptyLabel}</div>;
  }

  if (document.content_type === "text" || document.content_type === "json") {
    return <pre className="artifact-viewer text">{document.content}</pre>;
  }

  const blocks = providedBlocks ?? parseMarkdown(document.content);
  return (
    <div className="artifact-viewer markdown">
      <div className="markdown-document">
        {blocks.map((block, index) => renderBlock(block, index))}
      </div>
    </div>
  );
}

function renderBlock(block: MarkdownBlock, index: number): ReactNode {
  switch (block.type) {
    case "heading": {
      const headingTags = ["h2", "h3", "h4", "h5", "h6"] as const;
      const HeadingTag = headingTags[Math.min(block.depth, headingTags.length) - 1] ?? "h6";
      return (
        <HeadingTag
          key={`heading-${index}`}
          id={markdownHeadingId(block.text, index)}
          className={`markdown-heading depth-${block.depth}`}
        >
          {renderInline(block.text, `heading-${index}`)}
        </HeadingTag>
      );
    }
    case "paragraph":
      return (
        <p key={`paragraph-${index}`} className="markdown-paragraph">
          {renderInline(block.text, `paragraph-${index}`)}
        </p>
      );
    case "list": {
      const ListTag = block.ordered ? "ol" : "ul";
      return (
        <ListTag key={`list-${index}`} className={`markdown-list ${block.ordered ? "ordered" : "unordered"}`}>
          {block.items.map((item, itemIndex) => (
            <li key={`list-${index}-${itemIndex}`}>{renderInline(item, `list-${index}-${itemIndex}`)}</li>
          ))}
        </ListTag>
      );
    }
    case "code":
      return (
        <div key={`code-${index}`} className="markdown-code-shell">
          {block.language ? <span className="markdown-code-language">{block.language}</span> : null}
          <pre className="markdown-code-block">
            <code>{block.content}</code>
          </pre>
        </div>
      );
    case "blockquote":
      return (
        <blockquote key={`blockquote-${index}`} className="markdown-blockquote">
          {block.lines.map((line, lineIndex) => (
            <p key={`blockquote-${index}-${lineIndex}`}>{renderInline(line, `blockquote-${index}-${lineIndex}`)}</p>
          ))}
        </blockquote>
      );
    case "rule":
      return <hr key={`rule-${index}`} className="markdown-rule" />;
    default:
      return null;
  }
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const tokenPattern = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)]+)\)/g;
  let cursor = 0;
  let match: RegExpExecArray | null = tokenPattern.exec(text);

  while (match) {
    if (match.index > cursor) {
      parts.push(text.slice(cursor, match.index));
    }

    if (match[1]) {
      parts.push(
        <code key={`${keyPrefix}-code-${match.index}`} className="markdown-inline-code">
          {match[1]}
        </code>,
      );
    } else if (match[2]) {
      parts.push(
        <strong key={`${keyPrefix}-strong-${match.index}`} className="markdown-strong">
          {match[2]}
        </strong>,
      );
    } else if (match[3] && match[4]) {
      const href = match[4].replace(/^<|>$/g, "");
      if (/^https?:\/\//i.test(href)) {
        parts.push(
          <a
            key={`${keyPrefix}-link-${match.index}`}
            className="markdown-link"
            href={href}
            target="_blank"
            rel="noreferrer"
          >
            {match[3]}
          </a>,
        );
      } else {
        parts.push(
          <span key={`${keyPrefix}-linkish-${match.index}`} className="markdown-linkish" title={href}>
            {match[3]}
          </span>,
        );
      }
    }

    cursor = tokenPattern.lastIndex;
    match = tokenPattern.exec(text);
  }

  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return parts;
}

export function markdownHeadingId(text: string, index: number): string {
  const slug = text
    .toLowerCase()
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
  return `${slug || "section"}-${index}`;
}

export function extractMarkdownOutline(blocks: MarkdownBlock[]): MarkdownHeadingOutline[] {
  return blocks.flatMap((block, index) =>
    block.type === "heading"
      ? [
          {
            id: markdownHeadingId(block.text, index),
            depth: block.depth,
            text: block.text,
          },
        ]
      : [],
  );
}

export function parseMarkdown(content: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const rawLine = lines[index];
    const line = rawLine.trimEnd();

    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.startsWith("```")) {
      const language = line.slice(3).trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({ type: "code", language, content: codeLines.join("\n") });
      continue;
    }

    if (line.startsWith(">")) {
      const quoteLines: string[] = [];
      while (index < lines.length && lines[index].trimStart().startsWith(">")) {
        quoteLines.push(lines[index].trimStart().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "blockquote", lines: quoteLines });
      continue;
    }

    if (HORIZONTAL_RULE_RE.test(line.trim())) {
      blocks.push({ type: "rule" });
      index += 1;
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      blocks.push({ type: "heading", depth: headingMatch[1].length, text: headingMatch[2].trim() });
      index += 1;
      continue;
    }

    if (UNORDERED_LIST_RE.test(line.trim()) || ORDERED_LIST_RE.test(line.trim())) {
      const ordered = ORDERED_LIST_RE.test(line.trim());
      const items: string[] = [];
      while (index < lines.length) {
        const currentLine = lines[index].trim();
        if (ordered && ORDERED_LIST_RE.test(currentLine)) {
          items.push(currentLine.replace(/^\d+\.\s+/, "").trim());
          index += 1;
          continue;
        }
        if (!ordered && UNORDERED_LIST_RE.test(currentLine)) {
          items.push(currentLine.replace(/^[-*+]\s+/, "").trim());
          index += 1;
          continue;
        }
        break;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }

    const paragraphLines = [line.trim()];
    index += 1;
    while (index < lines.length) {
      const nextLine = lines[index];
      const trimmedNextLine = nextLine.trim();
      if (
        !trimmedNextLine ||
        trimmedNextLine.startsWith("```") ||
        trimmedNextLine.startsWith(">") ||
        HORIZONTAL_RULE_RE.test(trimmedNextLine) ||
        /^(#{1,6})\s+/.test(trimmedNextLine) ||
        UNORDERED_LIST_RE.test(trimmedNextLine) ||
        ORDERED_LIST_RE.test(trimmedNextLine)
      ) {
        break;
      }
      paragraphLines.push(trimmedNextLine);
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraphLines.join(" ") });
  }

  return blocks;
}
