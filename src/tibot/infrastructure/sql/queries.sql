-- name: archive_active_games
UPDATE games SET status='archived', revision=revision+1
WHERE chat_id=? AND status IN ('roster','drafting');

-- name: create_game
INSERT INTO games(chat_id, mode, status, created_by) VALUES (?, ?, ?, ?);

-- name: get_active_game_id
SELECT id FROM games WHERE chat_id=? AND status IN ('roster','drafting')
ORDER BY id DESC LIMIT 1;

-- name: get_latest_game_id
SELECT id FROM games WHERE chat_id=? ORDER BY id DESC LIMIT 1;

-- name: get_game
SELECT * FROM games WHERE id=?;

-- name: get_players
SELECT * FROM players WHERE game_id=? ORDER BY id;

-- name: get_game_status
SELECT status FROM games WHERE id=?;

-- name: count_players
SELECT COUNT(*) AS count FROM players WHERE game_id=?;

-- name: add_player
INSERT INTO players(game_id, display_name, telegram_user_id, telegram_username)
VALUES (?, ?, ?, ?);

-- name: remove_user
DELETE FROM players WHERE game_id=? AND telegram_user_id=?
AND EXISTS(SELECT 1 FROM games WHERE id=? AND status='roster');

-- name: claim_player
UPDATE players SET telegram_user_id=?, telegram_username=?
WHERE game_id=? AND display_name=? COLLATE NOCASE AND telegram_user_id IS NULL;

-- name: save_generation
UPDATE games
SET previous_setup_json=setup_json, setup_json=?, seed=?, status=?, draft_order_json=?,
    draft_pick_index=?, revision=revision+1, updated_at=CURRENT_TIMESTAMP
WHERE id=? AND revision=?;

-- name: retire_results
UPDATE results SET is_current=0 WHERE game_id=?;

-- name: add_result
INSERT INTO results(game_id, seed, payload_json) VALUES (?, ?, ?);

-- name: clear_options
DELETE FROM generated_options WHERE game_id=?;

-- name: add_faction_option
INSERT INTO generated_options VALUES (?, 'faction', ?, ?, 1);

-- name: add_slice_option
INSERT INTO generated_options VALUES (?, 'slice', ?, ?, 1);

-- name: add_seat_option
INSERT INTO generated_options VALUES (?, 'seat', ?, '{}', 1);

-- name: get_draft
SELECT draft_order_json, draft_pick_index, mode FROM games WHERE id=?;

-- name: finalize_setup
UPDATE games SET setup_json=?, revision=revision+1, updated_at=CURRENT_TIMESTAMP
WHERE id=? AND revision=?;

-- name: update_current_result
UPDATE results SET payload_json=? WHERE game_id=? AND is_current=1;

-- name: get_available_options
SELECT option_key FROM generated_options WHERE game_id=? AND kind=? AND available=1
ORDER BY option_key COLLATE NOCASE;

-- name: consume_option
UPDATE generated_options SET available=0
WHERE game_id=? AND kind=? AND option_key=? AND available=1;

-- name: set_player_faction
UPDATE players SET faction=? WHERE id=?;

-- name: set_player_slice
UPDATE players SET slice_id=? WHERE id=?;

-- name: set_player_seat
UPDATE players SET seat=? WHERE id=?;

-- name: add_draft_pick
INSERT INTO draft_picks(game_id, player_id, kind, option_key, picked_by)
VALUES (?, ?, ?, ?, ?);

-- name: advance_draft
UPDATE games SET draft_pick_index=?, status=?, revision=revision+1,
updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?;

-- name: cancel_game
UPDATE games SET status='cancelled', revision=revision+1 WHERE id=? AND revision=?;

-- name: bump_game
UPDATE games SET revision=revision+1, updated_at=CURRENT_TIMESTAMP WHERE id=?;

-- name: reset_player_picks
UPDATE players SET faction=NULL, slice_id=NULL, seat=NULL WHERE game_id=?;

-- name: clear_draft_picks
DELETE FROM draft_picks WHERE game_id=?;

-- name: reset_completed_game
UPDATE games SET status='roster', revision=revision+1, draft_order_json=NULL,
draft_pick_index=0 WHERE id=? AND revision=? AND status='complete';

-- name: healthcheck
SELECT version FROM schema_versions ORDER BY version DESC LIMIT 1;
