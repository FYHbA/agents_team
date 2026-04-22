from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.config import Settings
from app.models.dto import DiscoveredProject, ProjectTreeEntry, ProjectTreeResponse
from app.services.codex import discover_codex_projects


def discover_projects(settings: Settings) -> list[DiscoveredProject]:
    discovered = [
        DiscoveredProject(path=str(path), source="codex-config", trusted=True)
        for path in discover_codex_projects(settings)
    ]
    discovered.sort(key=lambda item: item.path.lower())
    return discovered


def _build_tree(path: Path, depth: int) -> list[ProjectTreeEntry]:
    if depth <= 0 or not path.is_dir():
        return []

    entries: list[ProjectTreeEntry] = []
    children = sorted(path.iterdir(), key=lambda child: (child.is_file(), child.name.lower()))
    for child in children[:80]:
        if child.name in {".git", "node_modules", ".venv", "__pycache__"}:
            continue
        entry_type = "directory" if child.is_dir() else "file"
        nested = _build_tree(child, depth - 1) if child.is_dir() else []
        entries.append(
            ProjectTreeEntry(
                name=child.name,
                path=str(child),
                entry_type=entry_type,
                children=nested,
            )
        )
    return entries


def list_directory(path_str: str, depth: int = 1) -> ProjectTreeResponse:
    path = Path(path_str).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path does not exist: {path}")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")

    return ProjectTreeResponse(root=str(path), entries=_build_tree(path, depth=depth))
