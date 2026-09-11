"""Container health check for content and database availability."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from tibot.domain import ContentCatalog
from tibot.infrastructure.sql_loader import load_queries


def main() -> None:
    ContentCatalog.load()
    path = Path(os.getenv("DATABASE_PATH", "data/tibot.db"))
    if not path.exists():
        raise SystemExit("Database has not been created")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.execute(load_queries()["healthcheck"]).fetchone()


if __name__ == "__main__":
    main()
