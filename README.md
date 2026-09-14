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

## Google Compute Engine without Docker

The bot can run directly on a small Ubuntu VM through `systemd`. The deployed checkout in the
examples below is `/home/YOUR_USER/tibot`; replace `YOUR_USER` with the VM account name.

Install or update the checked-out application:

```bash
cd ~/tibot
git pull --ff-only
git submodule update --init --recursive
uv sync --locked --no-dev
sudo systemctl restart tibot
```

Useful service operations:

```bash
sudo systemctl status tibot --no-pager  # show current status
sudo systemctl restart tibot            # restart after configuration changes
sudo systemctl stop tibot               # stop the bot
sudo systemctl start tibot              # start the bot
sudo systemctl enable tibot             # start automatically after VM reboots
sudo systemctl disable tibot            # disable automatic startup
journalctl -u tibot -f                   # follow live logs; Ctrl-C only leaves the log viewer
journalctl -u tibot -n 100 --no-pager   # show the latest 100 log lines
```

The service configuration is `/etc/systemd/system/tibot.service`, and its private environment file
is `/etc/tibot/tibot.env`. After changing the service file, reload and restart it:

```bash
sudo systemctl daemon-reload
sudo systemctl restart tibot
```

Back up the SQLite database while the bot is stopped so the database and WAL files remain
consistent:

```bash
sudo systemctl stop tibot
cp ~/tibot/data/tibot.db ~/tibot/data/tibot-backup-$(date +%F).db
sudo systemctl start tibot
```

To permanently delete every saved game on the VM and create a fresh database on next startup:

```bash
sudo systemctl stop tibot
rm -f ~/tibot/data/tibot.db ~/tibot/data/tibot.db-shm ~/tibot/data/tibot.db-wal
sudo systemctl start tibot
```

### Import an external five-player draft

An in-progress whole-board draft from the legacy generator can be continued in TIBot. First use
`/setup` in the target Telegram chat, select **Whole board**, add exactly five players, and leave the
game in the roster phase. The players' display names or Telegram usernames are accepted by the
import command.

Export the legacy board with `random5wholeboard --export-json PATH`, transfer that JSON file to the
VM, then stop TIBot and make a database backup before importing:

```bash
cd ~/tibot
sudo systemctl stop tibot
cp data/tibot.db "data/tibot-before-import-$(date +%F-%H%M%S).db"

uv run tibot-import-draft ~/old-board.json \
  --database data/tibot.db \
  --order @alice @bob @carol @dave @erin \
  --pick '@alice|seat|2' \
  --pick '@bob|faction|Muaat' \
  --pick '@carol|seat|4'

sudo systemctl start tibot
sudo systemctl status tibot --no-pager
```

The order of `--pick` arguments must be chronological. A player may be identified by display name
or `@username`; faction values accept canonical names or an unambiguous short name. If the database
contains more than one eligible roster game, the command prints their game and chat IDs without
changing anything; rerun it with `--game-id ID`. After import, send `/setup` in the group to publish
the current board and draft controls at the bottom of the chat.

To stop the VM itself, use **Compute Engine → VM instances → Stop** in Google Cloud Console. Starting
the VM later also starts TIBot when the service is enabled.

## Telegram usage

In a Telegram group, `/setup` opens the persistent setup wizard. Players join through its inline
buttons; `/addplayer NAME` creates an offline seat and `/addplayer @handle` creates a seat that the
matching user can claim by joining. A joined player can use `/removeplayer NAME` to remove an exact
case-insensitive name while the roster is open. `/claim NAME` explicitly claims a placeholder.
`/randomplayer` chooses a random player from the active roster, while `/result` republishes the latest
setup and board.

For arbitrary choices, send `/choice` followed by one option per line; empty lines are ignored:

```text
/choice
Play this Friday
Play this Saturday
Postpone
```

Use `/die N` to roll a uniformly distributed integer from 1 through `N`, inclusive. Like the other
randomizers, the response includes its seed.

Use the **Start new setup** button or `/setup new` to open a replacement mode chooser while a roster
or draft is active. The current setup remains resumable until a replacement mode is selected; then
it is archived atomically, and any older in-flight generation result is rejected as stale.

During a draft, `/undo` rewinds the latest choice and can be repeated to walk backward through the
persisted choice history. `/undo PLAYER NAME <faction|slice|seat>` instead rewinds the named choice.
If newer choices exist, they are rewound as well so snake order remains valid; every restored option
becomes available again and the recap returns to the affected turn.

Examples for each targeted choice type:

```text
/undo Alice faction
/undo Bob Smith slice
/undo Charlie seat
```

After the final draft choice, the setup waits for confirmation instead of finalizing immediately.
Use **Undo last choice** to reopen the final turn, or **Start** to place faction homes, resolve the
Speaker rule, complete the setup, and publish the final board.

Every setup begins with a randomized snake-draft order. Slice drafts use three passes in which
players choose a faction, slice, and seat in any order; seat 1 becomes Speaker. Whole-board drafts
publish the anonymous board first, then use two passes for faction and seat choices before choosing
Speaker randomly and publishing the finalized faction homes.

Generated slice choices are published as images. During a draft, the bot publishes a refreshed
board as soon as a player claims a seat, showing their name on its home placeholder. Later faction
and slice picks refresh that placement with the newly known content. Each successful choice also
remains in the chat as a lightweight accountability log. Board scores and generator warnings are
hidden behind Telegram spoiler formatting until opened. Seed lines are likewise hidden in full in
setup recaps and standalone randomizer results.

When a current inline control is pressed, the bot removes it immediately before doing any work.
At the start of generation it posts the empty player-count-specific board with numbered seats.
Generated media and the permanent choice log are then posted, followed by the refreshed recap and
controls as the newest message. If the operation fails, its error and a restored control panel are
posted at the bottom instead.

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
