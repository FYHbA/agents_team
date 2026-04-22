from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    api_prefix: str
    cors_origins: tuple[str, ...]
    codex_home: Path
    agents_team_home: Path
    default_allow_network: bool
    default_allow_installs: bool
    default_confirm_dangerous_commands: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw_origins = os.getenv("AGENTS_TEAM_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    cors_origins = tuple(origin.strip() for origin in raw_origins.split(",") if origin.strip())
    codex_home = Path(os.getenv("CODEX_HOME", Path.home() / ".codex"))
    agents_team_home = Path(os.getenv("AGENTS_TEAM_HOME", Path.home() / ".agents-team"))

    return Settings(
        app_name="Agents Team API",
        api_prefix="/api",
        cors_origins=cors_origins,
        codex_home=codex_home,
        agents_team_home=agents_team_home,
        default_allow_network=_bool_env("AGENTS_TEAM_ALLOW_NETWORK", True),
        default_allow_installs=_bool_env("AGENTS_TEAM_ALLOW_INSTALLS", True),
        default_confirm_dangerous_commands=_bool_env("AGENTS_TEAM_CONFIRM_DANGEROUS", True),
    )
