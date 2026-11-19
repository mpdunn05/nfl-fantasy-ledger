-- Fantasy Tracker schema (MySQL 8+). Run inside your existing database: mysql -u USER -p DBNAME < schema.sql
-- Source data: nflverse (players, weekly player stats) + ffopportunity (expected fantasy points)


-- ---------------------------------------------------------------
-- App tables (created by your users)
-- ---------------------------------------------------------------
CREATE TABLE users (
  user_id       INT AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(50)  NOT NULL UNIQUE,
  email         VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE fantasy_teams (
  team_id        INT AUTO_INCREMENT PRIMARY KEY,
  user_id        INT          NOT NULL,
  season         SMALLINT     NOT NULL,
  team_name      VARCHAR(100) NOT NULL,
  league_name    VARCHAR(100) NULL,
  scoring_format ENUM('standard','half_ppr','ppr') NOT NULL DEFAULT 'ppr',
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- where the team came from; imported teams remember their league/team id so re-imports update them
  platform           ENUM('manual','espn','yahoo','sleeper') NOT NULL DEFAULT 'manual',
  external_league_id VARCHAR(32) NULL,
  external_team_id   VARCHAR(32) NULL,
  CONSTRAINT fk_team_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
  CONSTRAINT uq_team UNIQUE (user_id, season, team_name),
  CONSTRAINT uq_external_team UNIQUE (user_id, platform, season, external_league_id, external_team_id)
);

-- ---------------------------------------------------------------
-- NFL reference + stats tables (loaded from nflverse)
-- ---------------------------------------------------------------
CREATE TABLE nfl_players (
  player_id     VARCHAR(12)  PRIMARY KEY,          -- nflverse gsis_id, e.g. '00-0033873'
  full_name     VARCHAR(100) NOT NULL,
  position      VARCHAR(5)   NULL,
  latest_team   VARCHAR(5)   NULL,
  headshot_url  VARCHAR(255) NULL,
  birth_date    DATE         NULL,
  rookie_season SMALLINT     NULL,
  last_season   SMALLINT     NULL,
  INDEX idx_player_name (full_name),
  INDEX idx_player_pos (position)
);

CREATE TABLE player_week_stats (
  player_id         VARCHAR(12)  NOT NULL,
  season            SMALLINT     NOT NULL,
  week              TINYINT      NOT NULL,
  season_type       ENUM('REG','POST') NOT NULL,
  team              VARCHAR(5)   NULL,
  opponent_team     VARCHAR(5)   NULL,
  completions       SMALLINT NULL,
  attempts          SMALLINT NULL,
  passing_yards     SMALLINT NULL,
  passing_tds       TINYINT  NULL,
  passing_interceptions TINYINT NULL,
  carries           SMALLINT NULL,
  rushing_yards     SMALLINT NULL,
  rushing_tds       TINYINT  NULL,
  targets           SMALLINT NULL,
  receptions        SMALLINT NULL,
  receiving_yards   SMALLINT NULL,
  receiving_tds     TINYINT  NULL,
  fumbles_lost      TINYINT  NULL,
  fg_made           TINYINT  NULL,
  fg_att            TINYINT  NULL,
  pat_made          TINYINT  NULL,
  fantasy_points     DECIMAL(6,2) NULL,              -- standard scoring
  fantasy_points_ppr DECIMAL(6,2) NULL,              -- full PPR scoring
  PRIMARY KEY (player_id, season, week, season_type),
  INDEX idx_stats_season_week (season, week),
  CONSTRAINT fk_stats_player FOREIGN KEY (player_id) REFERENCES nfl_players(player_id)
);

CREATE TABLE player_week_expected (
  player_id              VARCHAR(12)  NOT NULL,
  season                 SMALLINT     NOT NULL,
  week                   TINYINT      NOT NULL,
  team                   VARCHAR(5)   NULL,
  expected_points        DECIMAL(7,3) NULL,          -- total_fantasy_points_exp
  actual_points_model    DECIMAL(7,3) NULL,          -- total_fantasy_points (same scoring as the model)
  points_diff            DECIMAL(7,3) NULL,          -- actual - expected
  pass_points_exp        DECIMAL(7,3) NULL,
  rush_points_exp        DECIMAL(7,3) NULL,
  rec_points_exp         DECIMAL(7,3) NULL,
  PRIMARY KEY (player_id, season, week),
  CONSTRAINT fk_exp_player FOREIGN KEY (player_id) REFERENCES nfl_players(player_id)
);

-- Maps each platform's player IDs to our gsis_id (loaded by data/load_playerids.py)
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

-- Which players a user had on which fantasy team
CREATE TABLE roster_entries (
  roster_entry_id INT AUTO_INCREMENT PRIMARY KEY,
  team_id         INT         NOT NULL,
  player_id       VARCHAR(12) NOT NULL,
  draft_round     TINYINT     NULL,                   -- optional, handy for "did my pick pay off?"
  draft_pick      SMALLINT    NULL,
  CONSTRAINT fk_roster_team   FOREIGN KEY (team_id)   REFERENCES fantasy_teams(team_id) ON DELETE CASCADE,
  CONSTRAINT fk_roster_player FOREIGN KEY (player_id) REFERENCES nfl_players(player_id),
  CONSTRAINT uq_roster UNIQUE (team_id, player_id)
);

-- ---------------------------------------------------------------
-- Views the app reads from
-- ---------------------------------------------------------------

-- One row per rostered player per regular-season week
CREATE OR REPLACE VIEW v_roster_weekly AS
SELECT
  ft.team_id, ft.user_id, ft.season, ft.scoring_format,
  re.player_id, p.full_name, p.position,
  s.week, s.team AS nfl_team, s.opponent_team,
  CASE ft.scoring_format
    WHEN 'ppr'      THEN s.fantasy_points_ppr
    WHEN 'half_ppr' THEN (s.fantasy_points + s.fantasy_points_ppr) / 2
    ELSE s.fantasy_points
  END AS actual_points,
  s.fantasy_points_ppr AS actual_points_ppr,   -- expected points are modelled in full PPR, so compare against this
  e.expected_points
FROM fantasy_teams ft
JOIN roster_entries   re ON re.team_id = ft.team_id
JOIN nfl_players      p  ON p.player_id = re.player_id
JOIN player_week_stats s ON s.player_id = re.player_id
                        AND s.season = ft.season
                        AND s.season_type = 'REG'
LEFT JOIN player_week_expected e ON e.player_id = s.player_id
                                AND e.season = s.season
                                AND e.week = s.week;

-- One row per rostered player per fantasy team (season totals)
CREATE OR REPLACE VIEW v_roster_season AS
SELECT
  team_id, user_id, season, player_id, full_name, position,
  COUNT(*)                                            AS games_played,
  ROUND(SUM(actual_points), 1)                        AS total_points,
  ROUND(AVG(actual_points), 1)                        AS points_per_game,
  ROUND(SUM(expected_points), 1)                      AS expected_points,
  -- expected_points are PPR-based, so compare PPR actuals over weeks that have an expected value
  ROUND(SUM(CASE WHEN expected_points IS NOT NULL THEN actual_points_ppr END)
        - SUM(expected_points), 1)                    AS points_over_expected
FROM v_roster_weekly
GROUP BY team_id, user_id, season, player_id, full_name, position;
