# Architecture

## Goal

Agents Team is a local-first orchestration layer for multiple code-oriented agents.
It should coordinate planning, coding, testing, reviewing, and reporting while keeping one active local project in focus at a time and integrating with local Codex capabilities.

## V1 system shape

```text
React frontend
    ->
FastAPI orchestration backend
    ->
Local services
    - filesystem browsing
    - workflow planner
    - runtime policy checks
    - project memory
    - global experience memory
    - Codex adapter
    ->
Execution layer
    - persistent SQLite-backed run queue
    - queue worker and recovery loop
    - worker ownership, heartbeats, and leases
    - step-scoped agent session tracking
    - per-session event timelines for thought / command / final-answer rendering
    - dependency-aware workflow graph scheduler
    - separately claimed branch jobs for parallel waves
    - Codex-backed runs
    - shell commands
    - Python tasks
```

## Core product concepts

### Project

A local folder the user wants the team to work on.
Each project may contain a hidden `.agents-team/` directory for runtime state.

### Team

A temporary or reusable set of role-specific agents created for a task.

### Workflow

A strict multi-step plan such as:

`planner -> coder -> runner/tester -> reviewer -> summarizer`

Steps may run in serial or parallel depending on the task.
The runtime should treat this as a dependency graph rather than a flat ordered list, so independent verification waves can execute concurrently and then rejoin before review/report.

### Artifact

Any tangible output from a run:

- changed files
- test logs
- experiment records
- reports
- session notes
- reproducible command lists

## Storage model

### Global home

Use the app's global home directory for:

- app settings
- project registry
- global memory
- cached Codex session metadata
- the persistent control-plane SQLite database for queue state and run metadata

### Project-local runtime

Use `<project>/.agents-team/` for:

- run history
- reports
- project memory
- logs
- artifact indexes
- project-local control-plane mirror/export snapshots

## Codex integration

### Preferred order

1. CLI/server bridge
2. Session indexing and linking
3. File-level parsing only as a fallback

### Reason

Codex session files and internal databases may change over time.
CLI and service entry points are a safer integration boundary.

### V1 Codex adapter responsibilities

- surface Codex home and config path
- discover recent sessions
- discover trusted projects from config
- attempt session continuation through supported commands
- launch new Codex-backed runs if session continuation is unavailable

## Safety model

- dangerous commands require confirmation
- when command-backed checks can be detected ahead of time, the UI should surface a command preview before approval
- command approval should be able to progress at the per-command level, with the run unblocked only after all required commands are confirmed
- less risky execution policies should remain configurable
- network access and package installation must be user-editable settings
- Git commit and push stay human-controlled in V1

## Runtime orchestration

- workflow start, resume, and retry should enqueue durable jobs before execution begins
- queue claims should be atomic across backend processes
- run metadata and queue metadata should share a consistent persistent store
- worker ownership should be explicit and renewed through heartbeats / leases while work is active
- stale worker leases should be recoverable, with expired queue items requeued and stale workers surfaced in diagnostics
- each workflow step should be observable as its own agent session, not only as a field on the final run record
- agent sessions should also be able to expose ordered event timelines so the frontend can render live thinking text, collapsible shell activity, and final answers without reverse-engineering one flat summary string
- dependency-aware schedulers should be able to emit parallel branch jobs that different workers can claim independently
- parallel branch waves should emit enough branch-level state and artifacts to explain partial failures after review/report
- branch failure policy should be explicit: some downstream steps such as review may continue on failed verification branches while the overall run still resolves to failed
- backend startup should recover interrupted queue items and orphaned running runs
- synchronous execution paths may still exist for tests, but product traffic should flow through the queue worker

## First implementation target

The first milestone should deliver:

- a working frontend shell
- a working backend shell
- project discovery
- Codex summary and recent-session visibility
- workflow planning endpoint
- UI for drafting a task and viewing the proposed team and step plan

## Frontend UX direction

- the primary user path should be launcher -> single-project workbench -> run cockpit
- diagnostics should exist, but as a secondary surface inside the workbench rather than the dominant first view
- UI text should support both Chinese and English
- local project opening should support backend-persisted recent projects, manual paths, discovered projects, and backend-host filesystem browsing with a native folder picker bridge when available
- URL state should preserve the current view and selected project/run so browser refresh and shared links degrade gracefully
- the visual language should feel like a focused dark-tech product, not a warm admin dashboard
