"""
Load the nflverse fantasy player ID map into player_id_map.
It links ESPN / Yahoo / Sleeper player IDs to our gsis_id (nfl_players.player_id),
which is what the ESPN team import uses to match players.

Run from the data folder, with nflenv active, AFTER migrations/001_platform_import.sql:
    python load_playerids.py --dry-run
    python load_playerids.py

Needs ff_playerids.csv (see export_nfl.py). The MySQL password is read from the
DB_PASSWORD environment variable if set, otherwise you are prompted for it.
Safe to re-run: the table is replaced with the latest copy of the CSV.
"""
import csv
import getpass
import os
import sys

DB_NAME = "awrobel"
DB_USER = "awrobel"
DB_HOST = "localhost"

MISSING = {"", "NA", "NaN", "nan", "None", "null"}


def val(x):
    if x is None:
        return None
    x = x.strip()
    return None if x in MISSING else x


def as_int(x):
    x = val(x)
    try:
        return int(float(x)) if x is not None else None
    except ValueError:
        return None


def main():
    with open("ff_playerids.csv", newline="", encoding="utf-8") as f:
        raw = list(csv.DictReader(f))

    rows = {}
    for r in raw:
        gsis = val(r.get("gsis_id"))
        if not gsis or gsis in rows:          # need a gsis_id; keep the first row per player
            continue
        espn, yahoo, sleeper = as_int(r.get("espn_id")), as_int(r.get("yahoo_id")), val(r.get("sleeper_id"))
        if espn is None and yahoo is None and sleeper is None:
            continue
        rows[gsis] = (gsis, espn, yahoo, sleeper,
                      (val(r.get("name")) or "")[:100] or None,
                      (val(r.get("position")) or "")[:5] or None)
    rows = list(rows.values())
    print("Players with a gsis_id and at least one platform ID: {:,}".format(len(rows)))
    print("  with an ESPN id: {:,}".format(sum(1 for r in rows if r[1] is not None)))

    if "--dry-run" in sys.argv:
        print("Dry run only: nothing was written to MySQL.")
        return

    import pymysql
    password = os.environ.get("DB_PASSWORD") or getpass.getpass("MySQL password: ")
    conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=password,
                           database=DB_NAME, charset="utf8mb4", autocommit=False)
    cur = conn.cursor()
    cur.execute("DELETE FROM player_id_map")
    sql = """INSERT INTO player_id_map (gsis_id, espn_id, yahoo_id, sleeper_id, name, position)
             VALUES (%s, %s, %s, %s, %s, %s)"""
    for i in range(0, len(rows), 1000):
        cur.executemany(sql, rows[i:i + 1000])
    conn.commit()

    cur.execute("""SELECT COUNT(*), SUM(p.player_id IS NOT NULL)
                   FROM player_id_map m LEFT JOIN nfl_players p ON p.player_id = m.gsis_id""")
    total, in_db = cur.fetchone()
    print("player_id_map now has {:,} rows ({:,} match a player in nfl_players)".format(total, int(in_db or 0)))
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
