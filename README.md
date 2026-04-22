# Agents Team

Agents Team is a local-first multi-agent code collaboration workbench.
It is designed to solve a gap in current Codex usage: multiple conversations can exist at once, but they do not naturally coordinate, share workflow state, or operate as an explicit team.

This repository contains the first product skeleton:

- A browser-based frontend for project switching, task drafting, and team-room style collaboration
- A FastAPI backend for orchestration, local filesystem access, and Codex integration scaffolding
- A foundation for project-local runtime state via `.agents-team/`

## Product direction

V1 is focused on code-task collaboration.

- Local-first
- Multi-project switching
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

## Current backend endpoints

- `GET /api/health`
- `GET /api/codex/summary`
- `GET /api/codex/capabilities`
- `GET /api/codex/sessions`
- `POST /api/codex/sessions/{session_id}/bridge`
- `GET /api/projects/discovered`
- `GET /api/projects/tree?path=<project-dir>`
- `GET /api/projects/runtime?path=<project-dir>`
- `POST /api/projects/runtime/init`
- `POST /api/workflows/plan`
- `POST /api/workflows/runs`
- `GET /api/workflows/runs?project_path=<project-dir>`
- `GET /api/workflows/runs/{run_id}`

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

## Codex integration stance

The current plan is:

- Prefer Codex CLI and server-style integration where possible
- Reuse resumable sessions when stable enough
- Avoid making Codex internal session files the only source of truth
- Keep Codex config handling read-only in V1

More detail lives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
