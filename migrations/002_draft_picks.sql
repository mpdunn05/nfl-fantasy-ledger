-- Stores a fantasy team's full draft (including players later traded or dropped),
-- so the team page can show a draft recap with each pick's end-of-season finish.
-- Run once against an existing database:
--   mysql -u USER -p DBNAME < migrations/002_draft_picks.sql
-- (schema.sql already includes this table for fresh installs.)

CREATE TABLE draft_picks (
  team_id       INT          NOT NULL,
  overall_pick  SMALLINT     NOT NULL,             -- 1 = first pick of the draft
  draft_round   TINYINT      NULL,
  round_pick    TINYINT      NULL,                 -- pick number within the round
  bid_amount    SMALLINT     NULL,                 -- auction drafts only
  keeper        BOOLEAN      NOT NULL DEFAULT FALSE,
  player_id     VARCHAR(12)  NULL,                 -- NULL when the player isn't in nfl_players (e.g. D/ST)
  player_name   VARCHAR(100) NOT NULL,
  position      VARCHAR(5)   NULL,
  PRIMARY KEY (team_id, overall_pick),
  CONSTRAINT fk_draft_team   FOREIGN KEY (team_id)   REFERENCES fantasy_teams(team_id) ON DELETE CASCADE,
  CONSTRAINT fk_draft_player FOREIGN KEY (player_id) REFERENCES nfl_players(player_id)
);
