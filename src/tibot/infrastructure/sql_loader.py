"""Load named SQL statements from package resources."""

from __future__ import annotations

from importlib import resources


def load_queries() -> dict[str, str]:
    text = resources.files("tibot.infrastructure.sql").joinpath("queries.sql").read_text(
        encoding="utf-8"
    )
    queries: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("-- name: "):
            current = line.removeprefix("-- name: ").strip()
            if not current or current in queries:
                raise RuntimeError(f"Invalid or duplicate SQL query name: {current!r}")
            queries[current] = []
        elif current is not None:
            queries[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in queries.items()}

