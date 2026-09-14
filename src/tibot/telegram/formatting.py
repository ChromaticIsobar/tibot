"""Shared HTML formatting for Telegram messages."""

from __future__ import annotations

import html
import json
from importlib.resources import files
from typing import cast


def _load_faction_links() -> dict[str, str]:
    resource = files("tibot.assets").joinpath("faction_wiki_links.json")
    return cast(dict[str, str], json.loads(resource.read_text(encoding="utf-8")))


FACTION_WIKI_LINKS = _load_faction_links()
LEGACY_FACTION_NAMES = {
    "The Lizix Mindnet": "The L1Z1X Mindnet",
    "The Mahact Gene-sorcerers": "The Mahact Gene-Sorcerers",
}


def faction_link(name: str) -> str:
    """Render a faction name as a safe Telegram HTML link."""
    canonical_name = LEGACY_FACTION_NAMES.get(name, name)
    try:
        url = FACTION_WIKI_LINKS[canonical_name]
    except KeyError as exc:
        raise ValueError(f"Missing wiki link for faction: {name}") from exc
    return (
        f'<a href="{html.escape(url, quote=True)}">'
        f"{html.escape(canonical_name)}</a>"
    )
