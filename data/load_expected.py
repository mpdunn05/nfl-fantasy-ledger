"""
Load ffopportunity expected fantasy points into player_week_expected.

Run from the data folder, with nflenv active, AFTER load_nfl.py:
    python load_expected.py --dry-run
    python load_expected.py

Needs ff_opportunity.csv (see export_nfl.py).
Rows for players not in nfl_players are skipped (foreign key).
"""
import csv
import getpass
import sys

DB_NAME = "awrobel"
DB_USER = "awrobel"
DB_HOST = "localhost"

csv.field_size_limit(10_000_000)
MISSING = {"", "NA", "NaN", "nan", "None", "null"}

# our column -> candidate ffopportunity column names (first one found is used)
SOURCES = {
    "player_id":           ["player_id", "gsis_id"],
    "season":              ["season"],
    "week":                ["week"],
    "team":                ["posteam", "team", "recent_team"],
    "expected_points":     ["total_fantasy_points_exp"],
    "actual_points_model": ["total_fantasy_points"],
    "points_diff":         ["total_fantasy_points_diff"],
    "pass_points_exp":     ["pass_fantasy_points_exp"],
    "rush_points_exp":     ["rush_fantasy_points_exp"],
    "rec_points_exp":      ["rec_fantasy_points_exp"],
}
COLS = list(SOURCES)


def val(x):
    if x is None:
        return None
    x = x.strip()
    return None if x in MISSING else x


def num(x, cast=float):
    x = val(x)
    if x is None:
        return None
    try:
        return cast(float(x))
    except ValueError:
        return None


def main():
    with open("ff_opportunity.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        raw = list(reader)

    pick = {}
    for ours, options in SOURCES.items():
        found = next((c for c in options if c in header), None)
        if found is None and ours in ("player_id", "season", "week", "expected_points"):
            sys.exit("ff_opportunity.csv has no column for '{}'. Header is:\n{}".format(
                ours, ", ".join(header)))
        pick[ours] = found

    rows = {}
    for r in raw:
        pid = val(r[pick["player_id"]])
        season, week = num(r[pick["season"]], int), num(r[pick["week"]], int)
        if not pid or season is None or week is None:
            continue
        def g(c, cast=float):
            return num(r[pick[c]], cast) if pick[c] else None
        team = val(r[pick["team"]])[:5] if pick["team"] and val(r[pick["team"]]) else None
        actual, exp = g("actual_points_model"), g("expected_points")
        diff = g("points_diff")
        if diff is None and actual is not None and exp is not None:
            diff = actual - exp
        rows[(pid, season, week)] = (pid, season, week, team, exp, actual, diff,
                                     g("pass_points_exp"), g("rush_points_exp"),
                                     g("rec_points_exp"))
    rows = list(rows.values())
    print("Rows in ff_opportunity.csv ready to load: {:,}".format(len(rows)))

    if "--dry-run" in sys.argv:
        print("Columns used:", {k: v for k, v in pick.items()})
        print("Dry run only: nothing was written to MySQL.")
        return

    import pymysql
    conn = pymysql.connect(host=DB_HOST, user=DB_USER,
                           password=getpass.getpass("MySQL password: "),
                           database=DB_NAME, charset="utf8mb4", autocommit=False)
    cur = conn.cursor()
    cur.execute("SELECT player_id FROM nfl_players")
    known = {r[0] for r in cur.fetchall()}
    keep = [r for r in rows if r[0] in known]
    print("Skipping {:,} rows for players not in nfl_players".format(len(rows) - len(keep)))

    sql = "INSERT IGNORE INTO player_week_expected ({}) VALUES ({})".format(
        ", ".join(COLS), ", ".join(["%s"] * len(COLS)))
    for i in range(0, len(keep), 1000):
        cur.executemany(sql, keep[i:i + 1000])
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM player_week_expected")
    print("player_week_expected now has {:,} rows".format(cur.fetchone()[0]))
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
