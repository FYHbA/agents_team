from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text("", encoding="utf-8")

    return Settings(
        app_name="Agents Team API",
        api_prefix="/api",
        cors_origins=(),
        codex_home=codex_home,
        agents_team_home=tmp_path / ".agents-team-home",
        default_allow_network=True,
        default_allow_installs=True,
        default_confirm_dangerous_commands=True,
    )
