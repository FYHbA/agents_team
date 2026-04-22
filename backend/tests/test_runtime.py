from __future__ import annotations

from pathlib import Path

from app.services.runtime import get_project_runtime, init_project_runtime


def test_project_runtime_init_creates_expected_layout(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "demo-project"
    project_path.mkdir()

    missing = get_project_runtime(str(project_path), test_settings)
    assert missing.state == "missing"

    created = init_project_runtime(str(project_path), test_settings)
    assert created.state == "initialized"
    assert Path(created.runtime_path).exists()
    assert Path(created.settings_path).exists()

    expected_directories = {
        Path(created.runtime_path) / "runs",
        Path(created.runtime_path) / "reports",
        Path(created.runtime_path) / "artifacts",
        Path(created.runtime_path) / "memory",
        Path(created.runtime_path) / "logs",
    }
    assert all(directory.exists() for directory in expected_directories)

    existing = init_project_runtime(str(project_path), test_settings)
    assert existing.state == "existing"
