"""
Load nflverse CSVs into the team database (awrobel).

Fills the existing tables:   nfl_players, player_week_stats
Creates + fills new tables:  nfl_teams, nfl_games

Run from the data folder, with the nflenv environment active:
    pip install pymysql              (first time only)
    python load_nfl.py --dry-run     (reads the CSVs, prints counts, touches nothing)
    python load_nfl.py               (loads into MySQL)

Re-running is safe: INSERT IGNORE skips rows that already exist.
"""
import csv
import getpass
import sys

DB_NAME = "awrobel"
DB_USER = "awrobel"
DB_HOST = "localhost"

csv.field_size_limit(10_000_000)
MISSING = {"", "NA", "NaN", "nan", "None", "null"}


def val(x, maxlen=None):
    if x is None:
        return None
    x = x.strip()
    if x in MISSING:
        return None
    return x[:maxlen] if maxlen else x


def num(x, cast=int):
    x = val(x)
    if x is None:
        return None
    try:
        return cast(float(x))
    except ValueError:
        return None


def read(name):
    with open(name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


CREATE_TEAMS = """
CREATE TABLE IF NOT EXISTS nfl_teams (
    team_abbr      VARCHAR(5)   PRIMARY KEY,
    team_name      VARCHAR(50),
    team_nick      VARCHAR(30),
    conference     VARCHAR(5),
    division       VARCHAR(20),
    primary_color  VARCHAR(10),
    logo_url       VARCHAR(255)
)"""

CREATE_GAMES = """
CREATE TABLE IF NOT EXISTS nfl_games (
    game_id     VARCHAR(20) PRIMARY KEY,
    season      SMALLINT    NOT NULL,
    game_type   VARCHAR(5),
    week        TINYINT,
    gameday     DATE,
    away_team   VARCHAR(5)  NOT NULL,
    home_team   VARCHAR(5)  NOT NULL,
    away_score  SMALLINT,
    home_score  SMALLINT,
    overtime    TINYINT,
    stadium     VARCHAR(80),
    roof        VARCHAR(15),
    surface     VARCHAR(20),
    FOREIGN KEY (away_team) REFERENCES nfl_teams(team_abbr) ON UPDATE CASCADE,
    FOREIGN KEY (home_team) REFERENCES nfl_teams(team_abbr) ON UPDATE CASCADE
)"""


def build_rows():
    print("Reading CSVs...")
    teams_csv = read("teams.csv")
    games_csv = read("games.csv")
    players_csv = read("players.csv")
    weekly_csv = read("player_week_stats.csv")

    # ---- nfl_teams: official list + any older abbreviations used in games/stats (OAK, SD, STL...)
    teams = {
        t["team_abbr"]: (t["team_abbr"], val(t["team_name"], 50), val(t["team_nick"], 30),
                         val(t["team_conf"], 5), val(t["team_division"], 20),
                         val(t["team_color"], 10), val(t["team_logo_espn"], 255))
        for t in teams_csv
    }
    used = {g["away_team"] for g in games_csv} | {g["home_team"] for g in games_csv}
    for w in weekly_csv:
        used.add(w.get("team") or w.get("recent_team") or "")
        used.add(w.get("opponent_team") or "")
    for abbr in used:
        abbr = val(abbr, 5)
        if abbr and abbr not in teams:
            teams[abbr] = (abbr, abbr, None, None, None, None, None)

    # ---- nfl_games
    games = [
        (g["game_id"], num(g["season"]), val(g["game_type"], 5), num(g["week"]),
         val(g["gameday"]), val(g["away_team"], 5), val(g["home_team"], 5),
         num(g["away_score"]), num(g["home_score"]), num(g["overtime"]),
         val(g["stadium"], 80), val(g["roof"], 15), val(g["surface"], 20))
        for g in games_csv
    ]

    # ---- nfl_players: full list, plus anyone who only shows up in weekly stats
    players = {}
    for p in players_csv:
        pid = val(p["gsis_id"])
        if not pid:
            continue
        players[pid] = (pid, val(p["display_name"], 100) or pid, val(p["position"], 5),
                        val(p["latest_team"], 5), val(p["headshot"], 255),
                        val(p["birth_date"]), num(p["rookie_season"]), num(p["last_season"]))
    for w in weekly_csv:
        pid = val(w["player_id"])
        if pid and pid not in players:
            players[pid] = (pid, val(w.get("player_display_name"), 100) or pid,
                            val(w.get("position"), 5),
                            val(w.get("team") or w.get("recent_team"), 5),
                            val(w.get("headshot_url"), 255), None, None, None)

    # ---- player_week_stats
    def fumbles_lost(w):
        if w.get("fumbles_lost_total") not in (None, ""):
            return num(w["fumbles_lost_total"])
        parts = [num(w.get(k)) for k in
                 ("sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost")]
        parts = [x for x in parts if x is not None]
        return sum(parts) if parts else None

    weekly = []
    for w in weekly_csv:
        pid = val(w["player_id"])
        stype = val(w.get("season_type"))
        if not pid or stype not in ("REG", "POST") or num(w.get("week")) is None:
            continue
        weekly.append((
            pid, num(w["season"]), num(w["week"]), stype,
            val(w.get("team") or w.get("recent_team"), 5), val(w.get("opponent_team"), 5),
            num(w.get("completions")), num(w.get("attempts")), num(w.get("passing_yards")),
            num(w.get("passing_tds")), num(w.get("passing_interceptions")),
            num(w.get("carries")), num(w.get("rushing_yards")), num(w.get("rushing_tds")),
            num(w.get("targets")), num(w.get("receptions")), num(w.get("receiving_yards")),
            num(w.get("receiving_tds")), fumbles_lost(w),
            num(w.get("fg_made")), num(w.get("fg_att")), num(w.get("pat_made")),
            num(w.get("fantasy_points"), float), num(w.get("fantasy_points_ppr"), float),
        ))

    return {
        "nfl_teams": (["team_abbr", "team_name", "team_nick", "conference", "division",
                       "primary_color", "logo_url"], list(teams.values())),
        "nfl_players": (["player_id", "full_name", "position", "latest_team", "headshot_url",
                         "birth_date", "rookie_season", "last_season"], list(players.values())),
        "nfl_games": (["game_id", "season", "game_type", "week", "gameday", "away_team",
                       "home_team", "away_score", "home_score", "overtime", "stadium",
                       "roof", "surface"], games),
        "player_week_stats": (["player_id", "season", "week", "season_type", "team",
                               "opponent_team", "completions", "attempts", "passing_yards",
                               "passing_tds", "passing_interceptions", "carries",
                               "rushing_yards", "rushing_tds", "targets", "receptions",
                               "receiving_yards", "receiving_tds", "fumbles_lost", "fg_made",
                               "fg_att", "pat_made", "fantasy_points",
                               "fantasy_points_ppr"], weekly),
    }


ORDER = ["nfl_teams", "nfl_players", "nfl_games", "player_week_stats"]


def main():
    data = build_rows()
    print("\nRows ready to load:")
    for t in ORDER:
        print(f"  {t:<18} {len(data[t][1]):>8,}")

    if "--dry-run" in sys.argv:
        print("\nDry run only: nothing was written to MySQL.")
        return

    import pymysql
    conn = pymysql.connect(host=DB_HOST, user=DB_USER,
                           password=getpass.getpass("\nMySQL password: "),
                           database=DB_NAME, charset="utf8mb4", autocommit=False)
    cur = conn.cursor()
    cur.execute(CREATE_TEAMS)
    cur.execute(CREATE_GAMES)
    conn.commit()

    print("Inserting...")
    for t in ORDER:
        cols, rows = data[t]
        sql = "INSERT IGNORE INTO {} ({}) VALUES ({})".format(
            t, ", ".join(cols), ", ".join(["%s"] * len(cols)))
        for i in range(0, len(rows), 1000):
            cur.executemany(sql, rows[i:i + 1000])
        conn.commit()
        print(f"  {t}: done")

    print("\nRows now in each table:")
    total = 0
    for t in ORDER:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        n = cur.fetchone()[0]
        total += n
        print(f"  {t:<18} {n:>8,}")
    print(f"  {'TOTAL':<18} {total:>8,}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
