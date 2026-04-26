# agents_team

`agents_team` is the repository for Agents Team, a local-first multi-agent code collaboration workbench.
It is designed to solve a gap in current Codex usage: multiple conversations can exist at once, but they do not naturally coordinate, share workflow state, or operate as an explicit team.

This repository contains the first product skeleton:

- A browser-based frontend for opening one project folder at a time, drafting tasks, and staying inside a persistent workbench
- A FastAPI backend for orchestration, local filesystem access, and Codex integration scaffolding
- A foundation for project-local runtime state via `.agents-team/`

## Product direction

V1 is focused on code-task collaboration.

- Local-first
- Single-project workbench focus
- Strict workflow collaboration
- Auto-generated agent teams
- Direct file editing by agents
- Human-controlled Git actions
- Read-only Codex config visibility
- Codex session reuse where possible

## Repository layout

```text
frontend/   React + Vite workspace
backend/    FastAPI service and orchestration skeleton
docs/       Architecture and product notes
```

## Quick start

### Backend

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ./backend
uvicorn app.main:app --reload --app-dir backend
```

Linux/macOS:

```bash
python -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./backend
uvicorn app.main:app --reload --app-dir backend
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

The frontend uses relative `/api` requests in development.
Vite proxies those requests to the backend dev server.

### Dev Launcher

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev-up.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev-status.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev-down.ps1
```

## Current backend endpoints

- `GET /api/health`
- `GET /api/codex/summary`
- `GET /api/projects/discovered`
- `GET /api/projects/roots`
- `GET /api/projects/recent`
- `POST /api/projects/workspaces/open`
- `POST /api/projects/pick`
- `GET /api/projects/tree?path=<project-dir>`
- `GET /api/projects/runtime?path=<project-dir>`
- `POST /api/projects/runtime/init`
- `POST /api/projects/runtime/mirror`
- `POST /api/projects/runtime/export`
- `POST /api/projects/runtime/import`
- `POST /api/workflows/plan`
- `POST /api/workflows/runs`
- `GET /api/workflows/runs?project_path=<project-dir>`
- `GET /api/workflows/runs/{run_id}`
- `DELETE /api/workflows/runs/{run_id}`
- `POST /api/workflows/runs/{run_id}/execute`
- `GET /api/workflows/runs/{run_id}/log`
- `GET /api/workflows/runs/{run_id}/artifacts`
- `GET /api/workflows/runs/{run_id}/context-audits`
- `GET /api/workflows/runs/{run_id}/events`
- `POST /api/workflows/runs/{run_id}/cancel`
- `POST /api/workflows/runs/{run_id}/approve-dangerous`
- `POST /api/workflows/runs/{run_id}/resume`
- `POST /api/workflows/runs/{run_id}/retry`
- `GET /api/workflows/runs/{run_id}/agent-sessions`
- `GET /api/workflows/queue`

## Local runtime state

The product is designed to create a hidden control directory inside managed user projects:

```text
<project>/.agents-team/
```

That directory is meant to hold:

- project-local metadata
- workflow runs
- reports
- artifact indexes
- project memory
- logs

The product itself may also use a global app home directory under the user's home directory.

Workflow runs now persist step-level execution state, attempt counts, cancellation metadata, logs, generated reports, artifact bundles, and a realtime event stream under the project-local runtime and HTTP API surface.
Workflow execution now enters a persistent global SQLite-backed run queue before worker execution, so queued/running items can be claimed safely across backend processes and recovered after a backend restart instead of depending only on the original request thread.
Run metadata, step ledger state, and cross-project run lookup metadata now also live in the same control-plane SQLite store instead of separate `run.json` and `run-index.json` files.
Runs now also recall project/global memory at creation time, inject that context into workflow execution, and write fresh handoff memory back on terminal states.
Codex-backed workflow steps no longer run directly inside the real project tree. They now execute inside isolated context workspaces under the global app home, with projected source files for edit-capable steps and generated `.agents-context/` state files for machine-readable handoffs.
Those machine-readable handoffs are now persisted under each run as JSON contracts such as `research-result.json`, `verify-summary.json`, `review-result.json`, and `final-state.json`, while markdown artifacts remain human-facing renderings derived from those contracts.
Every Codex-backed step also writes a context-audit record into the control-plane database so the backend can track which structured sources were exposed to the model, how many bytes were included, and whether any forbidden raw workflow files were requested.
When the upstream `codex exec --json` stream includes usage data, those same context-audit records now also capture real `input_tokens`, `cached_input_tokens`, and `output_tokens`.
Research can now also short-circuit a run when it determines the task is already covered by a recent successful run or already satisfied by the current project state. In that case the workflow skips later execution steps, still produces a final handoff, and records the run as `short_circuited` instead of pretending it was a normal completion.
For near-duplicate tasks that still need a small follow-up, research can now emit `continue_with_delta`. The scheduler preserves the run, persists a structured delta scope, rewrites later step goals, trims command previews, and narrows verification lanes so implement / verify / review / report focus only on the remaining delta instead of replaying the full original workflow.
The browser UI now surfaces both layers directly: the run artifact view can open the persisted JSON contracts, and diagnostics can show per-step context-audit summaries for the currently selected run.
Queue items now carry worker ownership, heartbeats, and lease expiry so stuck claims can be detected and recovered safely.
Queue diagnostics now also stay summary-first under longer dogfooding sessions: the dashboard keeps all counts, but only surfaces active work, recent terminal queue items, and the most relevant worker rows by default.
Each workflow step now produces its own tracked agent-session record with backend identity, worker ownership, provider path, and lifecycle timestamps.
Workflow planning now includes explicit dependency edges between steps, and matrix-style tasks can execute verification waves in parallel before review and reporting rejoin the graph.
Parallel verification branches can now be emitted as separately claimed queue items so different workers inside the backend process can consume them concurrently instead of relying on one coordinator thread to execute the whole wave.
When a verification branch fails, the workflow can still carry partial success into review and report, with the final run marked failed after handoff artifacts are produced.
Project-local control-plane mirrors and export/import snapshots now let the global SQLite control state be copied into `.agents-team/` and restored later.
The frontend now supports bilingual UI text, a launcher + persistent single-project workbench flow, and a single-project path-first interaction model.
Project opening and switching are now more browser-friendly: the UI can read recent projects from the backend registry, preserve view/project/run state in the URL, call a native folder picker on the backend host when available, and fall back to browsing the backend host filesystem with breadcrumbs and local folder filtering when the environment does not support a native picker.
Once a project is open, task drafting, runtime tools, run orchestration, artifacts, quick project switching, and secondary diagnostics stay in one continuous workbench instead of separate top-level pages.
The workbench now separates its two primary jobs into dedicated full-width sections: one area for building the team and shaping the next run, and one area for the run cockpit itself. This makes it easier to focus on composition first and execution second.
The run cockpit also now includes a chat-style agent session view, so step-scoped agent updates can be read more like a conversation timeline instead of a raw metadata list.
Agent sessions now also persist structured per-session event timelines, so the chat room can distinguish between in-progress thinking text, shell-command activity, and the final answer instead of flattening everything into one summary blob.
That agent-session API now also exposes explicit presentation fields for `thinking`, `final`, `collapsed preview`, and normalized command entries, so old summary-only runs and newer structured-event runs collapse consistently instead of relying on frontend inference.
The build surface now offers short task-drafting guidance when the request is still too thin, which helps first-time users shape a runnable brief without leaving the main composition flow.
The run ledger now has lightweight search, deferred filtering, and date-grouped sections, so browsing older runs stays workable once a project starts accumulating real history.
Inactive run ledger entries can now also be deleted end-to-end, which removes the stored run record, queue history, agent sessions, and saved artifacts together instead of leaving stale cockpit entries behind.
Artifact reading is also more document-friendly now: markdown artifacts render with headings, lists, quotes, and code blocks instead of only as one raw preformatted text block, and the reader now includes a cross-document navigator, previous/next actions, a heading outline for the current document, and clearer path/type labeling.
Run detail summary cards now live inside the overview tab instead of staying pinned above every detail view, and the chat room behaves more like a process transcript: active turns stay expanded, completed turns collapse into a compact message count, users can reopen any turn, expanded turns show the full final output plus process details, and the thread scrolls inside its own frame instead of taking over the whole page.
When a session includes structured events, the chat room now follows a more Codex-like turn model: thinking notes stay open while the run is active, shell commands stay collapsed unless the user expands them, and once the step finishes the thinking collapses behind a disclosure while the final answer stays visible. The disclosure control itself now reads more like Codex too, with a tighter circular toggle and a softer expand/collapse transition instead of a generic pill button.
When a chat turn is expanded, the UI now tries to show stage-specific result cards instead of only a long prose blob: files touched, checks run, warnings, suggested follow-ups, and other high-signal outcomes are pulled from the run's artifacts when that data exists.
The trace tab no longer dumps every giant stdout/stderr block inline by default either. It now summarizes oversized stream output into compact cards with event counts, command counts, agent updates, and hidden-output totals, while still letting you open the raw block when you need the full log.
Secondary surfaces now use less implementation-heavy language as well, especially around queued work, artifact types, and step-stage labels.
The default planning path now stays focused on the task draft and execution policy, while lower-value Codex session resume controls are kept out of the main build surface so the UI is easier to understand for general users.
Workflow drafts and run details now surface structured command previews for verification and Codex bridge paths, so dangerous-command approval is based on visible expected actions rather than a generic warning.
Dangerous command approval can now be handled per command preview, with partial approvals preserved until the remaining gated commands are confirmed.
Queue diagnostics now detect expired worker leases, requeue stale running items, and surface healthy-vs-abnormal worker state in a more compact summary-first view.
Artifact bundles now include a parallel-branch summary document for matrix-style verification waves, which makes branch outcomes easier to audit after partial failures.
Planner, reviewer, and reporter guidance now derive directly from structured memory so continuity checks and handoff priorities stay visible across the full workflow.
Research and verify steps now write structured findings back into project memory, so later plans can recall concrete context and verification evidence instead of only final handoff summaries.
High-signal research and verify findings can now be promoted into reusable global rules, and future workflow planning will treat those rules as stronger cross-project guidance.
Planner, reviewer, and reporter now execute through distinct backend modules instead of sharing one generic step backend, and the cockpit surfaces those backend identities plus the planner's standalone planning brief artifact.
Those planner, reviewer, and reporter backends now attempt their own delegated non-interactive Codex execution chains first, with local fallback behavior preserved when Codex is unavailable.
Research and verify now follow the same pattern: each has its own delegated backend path, its own role-specific artifact, and a local fallback when Codex delegation is unavailable.
At this point the full strict workflow has explicit role-scoped backends for planner, research, implement, verify, review, and report, with execution coordinated by a persistent SQLite queue-backed worker inside the backend process and each step independently tracked as an agent session.
Runs that include command-backed steps now pause behind an explicit dangerous-command approval gate before execution, resume, or retry can proceed.

## Codex integration stance

The current plan is:

- Prefer Codex CLI and server-style integration where possible
- Reuse resumable sessions when stable enough
- Avoid making Codex internal session files the only source of truth
- Keep Codex config handling read-only in V1

More detail lives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
