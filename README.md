# TIBot

Telegram-native preparation tools for 3-6 player Twilight Imperium games.

Development uses Python 3.12 and [uv](https://docs.astral.sh/uv/).

## Initial setup

```bash
git clone --recurse-submodules <repository-url>
cd TIBot
uv sync
```

If the repository was cloned without its submodule, initialize it separately:

```bash
git submodule update --init --recursive
```

Set `BOT_TOKEN` before starting the bot. Runtime data defaults to `data/tibot.db`; override it with
`DATABASE_PATH`. Set `LOG_LEVEL` to `DEBUG`, `INFO`, `WARNING`, or `ERROR`.

## Local development

Load a token stored in `.token` and run the bot:

```bash
export BOT_TOKEN="$(tr -d '\r\n' < .token)"
uv run tibot
```

Run the quality checks:

```bash
uv run pytest
uv run ruff check .
uv run mypy src tests
uv lock --check
```

## Docker

Build and start in the foreground:

```bash
export BOT_TOKEN="$(tr -d '\r\n' < .token)"
docker compose up --build
```

Start detached instead:

```bash
docker compose up --build -d
```

After detaching, follow output with `docker compose logs -f`. Press `Ctrl-C` to leave the logs
without stopping the container. After changing code, rebuild and recreate the service:

```bash
docker compose up --build -d
docker compose logs -f
```

Other useful operations:

```bash
docker compose ps                 # show service status
docker compose restart tibot      # restart without rebuilding
docker compose stop               # stop but keep container and database
docker compose start              # restart stopped containers
docker compose down               # remove containers, keep database volume
docker compose build --no-cache   # force a clean image rebuild
```

The SQLite database is stored in the `tibot-data` Docker volume. To permanently delete every saved
game and recreate a clean database:

```bash
docker compose down -v
docker compose up --build -d
```

This is destructive. For a local non-Docker run, stop the bot and delete the configured file:

```bash
rm -f data/tibot.db data/tibot.db-shm data/tibot.db-wal
```

## Telegram usage

In a Telegram group, `/setup` opens the persistent setup wizard. Players join through its inline
buttons; `/addplayer NAME` creates an offline seat and `/addplayer @handle` creates a seat that the
matching user can claim by joining. `/claim NAME` explicitly claims a placeholder. `/randomize`
opens the standalone faction, order, speaker, and seating tools, while `/result` republishes the
latest setup and board.

Use the **Start new setup** button or `/setup new` to open a replacement mode chooser while a roster
or draft is active. The current setup remains resumable until a replacement mode is selected; then
it is archived atomically, and any older in-flight generation result is rejected as stale.

Every setup begins with a randomized snake-draft order. Slice drafts use three passes in which
players choose a faction, slice, and seat in any order; seat 1 becomes Speaker. Whole-board drafts
publish the anonymous board first, then use two passes for faction and seat choices before choosing
Speaker randomly and publishing the finalized faction homes.

Generated slice choices are published as images. During a draft, the bot publishes a refreshed
board as soon as a player claims a seat, showing their name on its home placeholder. Later faction
and slice picks refresh that placement with the newly known content. Each successful choice also
remains in the chat as a lightweight accountability log. Board scores and generator warnings are
hidden behind Telegram spoiler formatting until opened.

After every action, generated media and the permanent choice log are posted first. The bot then
reposts the current recap and controls as the newest message, so the active UI stays at the bottom
of the conversation instead of requiring players to scroll upward.

The roster screen's **Advanced commands** panel links to manual player and generation controls.
Use `/generate [SEED] [factions=N] [slices=N]` to reproduce a seed or override pool sizes. `slices=N`
only applies to slice drafts. In whole-board mode, `/board [SEED]` or the **Board only (Twilight's
Fall)** button completes after publishing the anonymous board, with no faction or seating draft.

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
