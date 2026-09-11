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

## Content and assets

Game data and system tile images come from the `modules/ti4` submodule, pinned to the
`ChromaticIsobar/ti4` Thunder's Edge branch. Renderer resources and initial slice data under
`src/tibot/assets` were copied from the neighboring `TwilightImperiumGM` project when this clean
rewrite was created. Twilight Imperium is property of Fantasy Flight Games; this is an unofficial
fan project.

