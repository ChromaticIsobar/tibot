"""Container health check for content and database availability."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from tibot.domain import ContentCatalog


def main() -> None:
    ContentCatalog.load()
    path = Path(os.getenv("DATABASE_PATH", "data/tibot.db"))
    if not path.exists():
        raise SystemExit("Database has not been created")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        query = "SELECT version FROM schema_versions ORDER BY version DESC LIMIT 1"
        connection.execute(query).fetchone()


if __name__ == "__main__":
    main()
