-- Adds support for importing teams from fantasy platforms (ESPN now; Yahoo/Sleeper later).
-- Run once against an existing database:
--   mysql -u USER -p DBNAME < migrations/001_platform_import.sql
-- (schema.sql already includes these changes for fresh installs.)

-- Where a fantasy team came from, so re-importing the same team updates it instead of duplicating it
ALTER TABLE fantasy_teams
  ADD COLUMN platform           ENUM('manual','espn','yahoo','sleeper') NOT NULL DEFAULT 'manual',
  ADD COLUMN external_league_id VARCHAR(32) NULL,
  ADD COLUMN external_team_id   VARCHAR(32) NULL,
  ADD UNIQUE KEY uq_external_team (user_id, platform, season, external_league_id, external_team_id);

-- Maps each platform's player IDs to our nflverse gsis_id (source: nflverse ff_playerids / DynastyProcess)
CREATE TABLE player_id_map (
  gsis_id    VARCHAR(12)  PRIMARY KEY,
  espn_id    INT          NULL,
  yahoo_id   INT          NULL,
  sleeper_id VARCHAR(16)  NULL,
  name       VARCHAR(100) NULL,
  position   VARCHAR(5)   NULL,
  INDEX idx_map_espn (espn_id),
  INDEX idx_map_yahoo (yahoo_id),
  INDEX idx_map_sleeper (sleeper_id)
);
