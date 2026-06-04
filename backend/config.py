"""Backend configuration — engine and ledger selection from the environment.

Engine selection is the backend's responsibility (docs/ai-engines.md): ``MockEngine``
is the default; ``AnthropicEngine`` / ``VertexEngine`` require credentials and are
wired up in roadmap M6.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from devsecbuddy import DEFAULT_DB_PATH


@dataclass
class Settings:
    engine: str = "mock"                # DEVSECBUDDY_ENGINE — default engine for runs
    db_path: str = DEFAULT_DB_PATH      # DEVSECBUDDY_DB     — SQLite ledger location
    cors_origins: tuple[str, ...] = ("*",)  # frontend (M3) runs on a different origin


def load_settings() -> Settings:
    """Build settings from environment variables, falling back to safe defaults."""
    origins = os.environ.get("DEVSECBUDDY_CORS_ORIGINS")
    return Settings(
        engine=os.environ.get("DEVSECBUDDY_ENGINE", "mock"),
        db_path=os.environ.get("DEVSECBUDDY_DB", DEFAULT_DB_PATH),
        cors_origins=tuple(o.strip() for o in origins.split(",")) if origins else ("*",),
    )
