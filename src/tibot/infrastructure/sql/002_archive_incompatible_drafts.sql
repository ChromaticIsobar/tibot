UPDATE games
SET status = 'archived', revision = revision + 1, updated_at = CURRENT_TIMESTAMP
WHERE status = 'drafting';

INSERT INTO schema_versions(version) VALUES (2);
