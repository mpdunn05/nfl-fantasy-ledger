-- Remembers where each pick fell among players at the same position in the whole league draft
-- (e.g. 5 = the 5th RB taken), so a pick can be graded against the player's positional finish.
-- Run once against an existing database:
--   mysql -u USER -p DBNAME < migrations/003_positional_draft_rank.sql
-- Teams imported before this change need one re-import to fill it in.

ALTER TABLE draft_picks
  ADD COLUMN pos_draft_rank SMALLINT NULL AFTER position;
