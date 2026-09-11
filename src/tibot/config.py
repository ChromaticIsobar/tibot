"""Environment-driven runtime configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    log_level: int

    @classmethod
    def from_environment(cls) -> Settings:
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("BOT_TOKEN is required")
        database_path = Path(os.getenv("DATABASE_PATH", "data/tibot.db"))
        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = logging.getLevelNamesMapping().get(level_name)
        if level is None:
            raise ValueError(f"Invalid LOG_LEVEL: {level_name}")
        return cls(token, database_path, level)
