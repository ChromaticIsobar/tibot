# TIBot

Telegram-native preparation tools for 3-6 player Twilight Imperium games.

Development uses Python 3.12 and [uv](https://docs.astral.sh/uv/):

```console
git clone --recurse-submodules <repository-url>
uv sync
uv run tibot
```

Set `BOT_TOKEN` before starting the bot. Runtime data defaults to `data/tibot.db` and can be
relocated with `DATABASE_PATH`; logging is configured with `LOG_LEVEL`.

## Usage

Run locally:

```bash
export BOT_TOKEN="123:telegram-token"
uv run tibot
```

Or run the long-polling service in Docker:

```console
git submodule update --init --recursive
docker compose up --build -d
```

In a Telegram group, `/setup` opens the persistent setup wizard. Players join through its inline
buttons; `/addplayer NAME` creates an offline seat and `/addplayer @handle` creates a seat that the
matching user can claim by joining. `/claim NAME` explicitly claims a placeholder. `/randomize`
opens the standalone faction, order, speaker, and seating tools, while `/result` republishes the
latest setup and board.

## Content and assets

Game data and system tile images come from the `modules/ti4` submodule, pinned to the
`ChromaticIsobar/ti4` Thunder's Edge branch. Renderer resources and initial slice data under
`src/tibot/assets` were copied from the neighboring `TwilightImperiumGM` project when this clean
rewrite was created. Twilight Imperium is property of Fantasy Flight Games; this is an unofficial
fan project.

The submodule is intentionally pinned to commit
`cb9f0be801e6e706a31a9165acf5575a32c89e3c`. Updating content is a reviewed dependency change,
not an automatic runtime operation. The copied asset files retain their original bytes so their
history can be compared directly with `TwilightImperiumGM`.
