# Architecture

## Goal

Agents Team is a local-first orchestration layer for multiple code-oriented agents.
It should coordinate planning, coding, testing, reviewing, and reporting across multiple projects while integrating with local Codex capabilities.

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

### Project-local runtime

Use `<project>/.agents-team/` for:

- run history
- reports
- project memory
- logs
- artifact indexes

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
- less risky execution policies should remain configurable
- network access and package installation must be user-editable settings
- Git commit and push stay human-controlled in V1

## First implementation target

The first milestone should deliver:

- a working frontend shell
- a working backend shell
- project discovery
- Codex summary and recent-session visibility
- workflow planning endpoint
- UI for drafting a task and viewing the proposed team and step plan
