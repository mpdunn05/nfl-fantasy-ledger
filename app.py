#!/var/www/html/cse30246/nfl_fantasy_ledger/.venv/bin/python3

import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import pymysql
import pymysql.cursors

import espn


# Load KEY=VALUE pairs from .env (next to this file) into os.environ.
# Secrets live in .env, which is gitignored -- see .env.example.
def load_env(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_env()

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]   # needed for flash() messages

SEASONS = list(range(2024, 2006, -1))
POSITIONS = ["QB", "RB", "WR", "TE", "K"]
FORMATS = ["standard", "half_ppr", "ppr"]

# returns conn object for accesssing the database
def get_conn():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False)

# wrapper for cursor.execute() sql is sequel query returns array
def query(sql, args=()):
    """Run a SELECT and return a list of dict rows."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()
    finally:
        conn.close()

# another wrapper for cursor.execute() this one returns lastrowid that is the primary key of the row just inserted
def modify(sql, args=()):
    """Run an INSERT/UPDATE/DELETE and commit. Returns lastrowid."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            new_id = cur.lastrowid
        conn.commit()
        return new_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------- existing pages
TABLES = [
    ("player_week_stats",    "Weekly fantasy stats per player"),
    ("player_week_expected", "Expected fantasy points per player-week"),
    ("nfl_players",          "Every NFL player"),
    ("nfl_games",            "Game results and schedules"),
    ("nfl_teams",            "NFL teams"),
    ("users",                "App users"),
    ("fantasy_teams",        "Fantasy teams created in the app"),
    ("roster_entries",       "Players on fantasy rosters"),
]

# Main Page
@app.route("/cse30246/nfl_fantasy_ledger")
def index():
    counts = []
    for name, desc in TABLES:
        try:
            # getting count of rows in each table
            n = query("SELECT COUNT(*) AS n FROM " + name)[0]["n"]
        except pymysql.err.ProgrammingError:   # table missing
            continue
        # creating a list of sets where each set is a table and the number of rows in that table
        counts.append({"name": name, "desc": desc, "n": n})
    # returning total number of rows;
    total = sum(c["n"] for c in counts)
    return render_template("home.html", counts=counts, total=total)


# Project Pages
@app.route("/cse30246/nfl_fantasy_ledger/project")
def project():
    return render_template("project.html")


@app.route("/cse30246/nfl_fantasy_ledger/devplan")
def devplan():
    return render_template("devplan.html")


@app.route("/cse30246/nfl_fantasy_ledger/demo")
def demo():
    return render_template("demo.html")



# ---------------------------------------------------------------- accounts
def current_user_id():
    return session.get("user_id")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user_id():
            flash("Please sign in first.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def owns_team(team_id):
    """True if the signed-in user owns this team (checked in SQL every time)."""
    return bool(query("SELECT team_id FROM fantasy_teams WHERE team_id = %s AND user_id = %s",
                      (team_id, current_user_id())))


@app.route("/cse30246/nfl_fantasy_ledger/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        f = request.form
        username = f.get("username", "").strip()
        email = f.get("email", "").strip()
        password = f.get("password", "")
        if not (username and email and password):
            flash("Username, email and password are required.", "error")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
        elif password != f.get("confirm", ""):
            flash("Passwords do not match.", "error")
        else:
            try:
                user_id = modify(
                    "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
                    (username, email, generate_password_hash(password)))
            except pymysql.err.IntegrityError:
                flash("That username or email is already taken.", "error")
            else:
                session["user_id"], session["username"] = user_id, username
                flash("Welcome, {}! Your account is ready.".format(username), "ok")
                return redirect(url_for("account"))
    return render_template("signup.html")


@app.route("/cse30246/nfl_fantasy_ledger/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        rows = query("SELECT user_id, username, password_hash FROM users WHERE username = %s",
                     (username,))
        if rows and check_password_hash(rows[0]["password_hash"], request.form.get("password", "")):
            session["user_id"], session["username"] = rows[0]["user_id"], rows[0]["username"]
            flash("Signed in as {}.".format(rows[0]["username"]), "ok")
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/cse30246/") else url_for("account"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/cse30246/nfl_fantasy_ledger/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out.", "ok")
    return redirect(url_for("index"))


@app.route("/cse30246/nfl_fantasy_ledger/account")
@login_required
def account():
    me = query("SELECT username, email, created_at FROM users WHERE user_id = %s",
               (current_user_id(),))
    if not me:                       # account was deleted out from under the session
        session.clear()
        return redirect(url_for("login"))
    rows = query("""
        SELECT ft.team_id, ft.team_name, ft.league_name, ft.season, ft.scoring_format,
               COUNT(re.roster_entry_id) AS num_players
        FROM fantasy_teams ft
        LEFT JOIN roster_entries re ON re.team_id = ft.team_id
        WHERE ft.user_id = %s
        GROUP BY ft.team_id, ft.team_name, ft.league_name, ft.season,
                 ft.scoring_format, ft.created_at
        ORDER BY ft.created_at DESC""", (current_user_id(),))
    return render_template("account.html", me=me[0], rows=rows,
                           seasons=SEASONS, formats=FORMATS)


# ---------------------------------------------------------------- SEARCH (players)
@app.route("/cse30246/nfl_fantasy_ledger/players")
def players():
    q = request.args.get("q", "").strip()
    position = request.args.get("position", "")
    season = request.args.get("season", "2024")
    if not season.isdigit():
        season = "2024"

    sql = """
        SELECT p.player_id, p.full_name, p.position,
               GROUP_CONCAT(DISTINCT s.team SEPARATOR '/') AS team,
               COUNT(s.week)                       AS games,
               ROUND(SUM(s.fantasy_points), 1)     AS std_pts,
               ROUND(SUM(s.fantasy_points_ppr), 1) AS ppr_pts,
               ROUND(AVG(s.fantasy_points_ppr), 1) AS ppr_per_game
        FROM nfl_players p
        JOIN player_week_stats s ON s.player_id = p.player_id
        WHERE s.season = %s AND s.season_type = 'REG'
          AND p.full_name LIKE %s
    """
    args = [int(season), "%" + q + "%"]
    if position in POSITIONS:
        sql += " AND p.position = %s"
        args.append(position)
    sql += """
        GROUP BY p.player_id, p.full_name, p.position
        ORDER BY ppr_pts DESC
        LIMIT 100"""

    rows = query(sql, args)
    return render_template("players.html", rows=rows, q=q, position=position,
                           season=int(season), seasons=SEASONS, positions=POSITIONS)


# ---------------------------------------------------------------- fantasy teams list
@app.route("/cse30246/nfl_fantasy_ledger/teams")
def teams():
    rows = query("""
        SELECT ft.team_id, ft.user_id, ft.team_name, ft.league_name, ft.season,
               ft.scoring_format, u.username, COUNT(re.roster_entry_id) AS num_players
        FROM fantasy_teams ft
        JOIN users u ON u.user_id = ft.user_id
        LEFT JOIN roster_entries re ON re.team_id = ft.team_id
        GROUP BY ft.team_id, ft.user_id, ft.team_name, ft.league_name, ft.season,
                 ft.scoring_format, u.username, ft.created_at
        ORDER BY ft.created_at DESC""")
    return render_template("teams.html", rows=rows)


# ---------------------------------------------------------------- INSERT (create team)
@app.route("/cse30246/nfl_fantasy_ledger/teams/create", methods=["POST"])
@login_required
def create_team():
    f = request.form
    team_name = f.get("team_name", "").strip()
    if not team_name:
        flash("Team name is required.", "error")
        return redirect(url_for("account"))
    try:
        team_id = modify(
            """INSERT INTO fantasy_teams (user_id, season, team_name, league_name, scoring_format)
               VALUES (%s, %s, %s, %s, %s)""",
            (current_user_id(), int(f.get("season", 2024)), team_name,
             f.get("league_name", "").strip() or None,
             f.get("scoring_format") if f.get("scoring_format") in FORMATS else "ppr"))
    except pymysql.err.IntegrityError:
        flash("You already have a team called '{}' that season.".format(team_name), "error")
        return redirect(url_for("account"))
    flash("Created team '{}'.".format(team_name), "ok")
    return redirect(url_for("team_detail", team_id=team_id))


# ---------------------------------------------------------------- end-of-season ranks
RANK_POSITIONS = ("QB", "RB", "WR", "TE", "K")


def season_ranks(season, scoring_format):
    """
    End-of-regular-season finish for every QB/RB/WR/TE/K in a season, in the team's scoring format.
    Returns {player_id: {"pts", "pos_rank", "overall_rank", "position"}}.
    pos_rank:     rank among players at the same position (WR3 = 3rd-best WR)
    overall_rank: rank among all QB/RB/WR/TE (kickers excluded, as fantasy sites usually do)
    nflverse doesn't score kicking, so kickers are ranked by 3 x FG made + 1 x PAT made.
    """
    rows = query("""
        WITH totals AS (
            SELECT s.player_id, p.position,
                   SUM(CASE WHEN p.position = 'K' THEN 3 * COALESCE(s.fg_made, 0) + COALESCE(s.pat_made, 0)
                            WHEN %s = 'ppr'      THEN s.fantasy_points_ppr
                            WHEN %s = 'half_ppr' THEN (s.fantasy_points + s.fantasy_points_ppr) / 2
                            ELSE s.fantasy_points END) AS pts
            FROM player_week_stats s
            JOIN nfl_players p ON p.player_id = s.player_id
            WHERE s.season = %s AND s.season_type = 'REG' AND p.position IN ('QB','RB','WR','TE','K')
            GROUP BY s.player_id, p.position
        ),
        pos_ranked AS (
            SELECT player_id, position, pts,
                   RANK() OVER (PARTITION BY position ORDER BY pts DESC) AS pos_rank
            FROM totals
        ),
        skill_ranked AS (
            SELECT player_id, RANK() OVER (ORDER BY pts DESC) AS overall_rank
            FROM totals WHERE position <> 'K'
        )
        SELECT pr.player_id, pr.position, ROUND(pr.pts, 1) AS pts, pr.pos_rank, sr.overall_rank
        FROM pos_ranked pr
        LEFT JOIN skill_ranked sr ON sr.player_id = pr.player_id""",
        (scoring_format, scoring_format, season))
    return {r["player_id"]: r for r in rows}


# ---------------------------------------------------------------- team page
@app.route("/cse30246/nfl_fantasy_ledger/teams/<int:team_id>")
def team_detail(team_id):
    found = query("""
        SELECT ft.*, u.username FROM fantasy_teams ft
        JOIN users u ON u.user_id = ft.user_id
        WHERE ft.team_id = %s""", (team_id,))
    if not found:
        flash("That team no longer exists.", "error")
        return redirect(url_for("teams"))
    team = found[0]

    roster = query("""
        SELECT re.roster_entry_id, p.player_id, p.full_name, p.position,
               re.draft_round, re.draft_pick,
               GROUP_CONCAT(DISTINCT s.team SEPARATOR '/') AS season_team,
               COUNT(s.week) AS games,
               ROUND(SUM(CASE ft.scoring_format
                           WHEN 'ppr'      THEN s.fantasy_points_ppr
                           WHEN 'half_ppr' THEN (s.fantasy_points + s.fantasy_points_ppr) / 2
                           ELSE s.fantasy_points END), 1) AS pts
        FROM roster_entries re
        JOIN fantasy_teams ft ON ft.team_id = re.team_id
        JOIN nfl_players p    ON p.player_id = re.player_id
        LEFT JOIN player_week_stats s
               ON s.player_id = re.player_id AND s.season = ft.season
              AND s.season_type = 'REG'
        WHERE re.team_id = %s
        GROUP BY re.roster_entry_id, p.player_id, p.full_name, p.position,
                 re.draft_round, re.draft_pick
        ORDER BY pts DESC""", (team_id,))

    # End-of-season finish (e.g. WR3, #12 overall) for rostered and drafted players
    ranks = season_ranks(team["season"], team["scoring_format"])
    for r in roster:
        r["finish"] = ranks.get(r["player_id"])

    draft = query("""SELECT overall_pick, draft_round, round_pick, bid_amount, keeper,
                            player_id, player_name, position
                     FROM draft_picks WHERE team_id = %s ORDER BY overall_pick""", (team_id,))
    on_roster = {r["player_id"] for r in roster}
    for d in draft:
        d["finish"] = ranks.get(d["player_id"])
        d["on_roster"] = d["player_id"] in on_roster
    has_stats = bool(ranks)

    is_owner = team["user_id"] == current_user_id()
    q = request.args.get("q", "").strip()
    matches = []
    if q and is_owner:
        matches = query("""
            SELECT p.player_id, p.full_name, p.position, p.latest_team, p.last_season
            FROM nfl_players p
            WHERE p.full_name LIKE %s
              AND p.player_id NOT IN (SELECT player_id FROM roster_entries WHERE team_id = %s)
            ORDER BY p.last_season IS NULL, p.last_season DESC, p.full_name
            LIMIT 15""", ("%" + q + "%", team_id))

    total = sum(r["pts"] or 0 for r in roster)
    return render_template("team.html", team=team, roster=roster, matches=matches,
                           q=q, total=total, formats=FORMATS, is_owner=is_owner,
                           draft=draft, has_stats=has_stats)


# ---------------------------------------------------------------- INSERT (add player)
@app.route("/cse30246/nfl_fantasy_ledger/teams/<int:team_id>/add", methods=["POST"])
@login_required
def add_player(team_id):
    if not owns_team(team_id):
        flash("You can only change your own teams.", "error")
        return redirect(url_for("team_detail", team_id=team_id))
    player_id = request.form.get("player_id", "")
    try:
        modify("INSERT INTO roster_entries (team_id, player_id) VALUES (%s, %s)",
               (team_id, player_id))
        flash("Player added to roster.", "ok")
    except pymysql.err.IntegrityError as e:
        flash("Could not add player: " + str(e.args[1]), "error")
    return redirect(url_for("team_detail", team_id=team_id))


# ---------------------------------------------------------------- UPDATE (team settings)
@app.route("/cse30246/nfl_fantasy_ledger/teams/<int:team_id>/update", methods=["POST"])
@login_required
def update_team(team_id):
    if not owns_team(team_id):
        flash("You can only change your own teams.", "error")
        return redirect(url_for("team_detail", team_id=team_id))
    name = request.form.get("team_name", "").strip()
    fmt = request.form.get("scoring_format", "ppr")
    if not name or fmt not in FORMATS:
        flash("Team name and a valid scoring format are required.", "error")
    else:
        try:
            modify("""UPDATE fantasy_teams SET team_name = %s, scoring_format = %s
                      WHERE team_id = %s AND user_id = %s""",
                   (name, fmt, team_id, current_user_id()))
            flash("Team updated.", "ok")
        except pymysql.err.IntegrityError:
            flash("You already have a team called '{}' that season.".format(name), "error")
    return redirect(url_for("team_detail", team_id=team_id))


# ---------------------------------------------------------------- DELETE (drop player)
@app.route("/cse30246/nfl_fantasy_ledger/teams/<int:team_id>/remove/<int:entry_id>", methods=["POST"])
@login_required
def remove_player(team_id, entry_id):
    if not owns_team(team_id):
        flash("You can only change your own teams.", "error")
        return redirect(url_for("team_detail", team_id=team_id))
    modify("DELETE FROM roster_entries WHERE roster_entry_id = %s AND team_id = %s",
           (entry_id, team_id))
    flash("Player removed from roster.", "ok")
    return redirect(url_for("team_detail", team_id=team_id))


# ---------------------------------------------------------------- DELETE (whole team)
@app.route("/cse30246/nfl_fantasy_ledger/teams/<int:team_id>/delete", methods=["POST"])
@login_required
def delete_team(team_id):
    if not owns_team(team_id):
        flash("You can only delete your own teams.", "error")
        return redirect(url_for("team_detail", team_id=team_id))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM roster_entries WHERE team_id = %s", (team_id,))
            cur.execute("DELETE FROM fantasy_teams WHERE team_id = %s AND user_id = %s",
                        (team_id, current_user_id()))
        conn.commit()
    finally:
        conn.close()
    flash("Team deleted.", "ok")
    return redirect(url_for("account"))


# ---------------------------------------------------------------- IMPORT (ESPN league link)
def match_espn_players(players):
    """
    Map ESPN players to our nfl_players ids.
    1) by ESPN id through player_id_map, 2) by name + position for anyone left over.
    Returns ({espn_id: gsis_id}, [players that couldn't be matched]).
    """
    found = {}
    ids = [p["espn_id"] for p in players]
    if ids:
        rows = query("""
            SELECT m.espn_id, m.gsis_id FROM player_id_map m
            JOIN nfl_players p ON p.player_id = m.gsis_id
            WHERE m.espn_id IN ({})""".format(", ".join(["%s"] * len(ids))), ids)
        found = {r["espn_id"]: r["gsis_id"] for r in rows}

    left = [p for p in players if p["espn_id"] not in found and p["position"] != "D/ST"]
    if left:
        rows = query("""
            SELECT player_id, full_name, position FROM nfl_players
            WHERE full_name IN ({})
            ORDER BY last_season IS NULL, last_season DESC""".format(", ".join(["%s"] * len(left))),
            [p["name"] for p in left])
        by_name = {}
        for r in rows:
            by_name.setdefault((espn.name_key(r["full_name"]), r["position"]), []).append(r["player_id"])
        for p in left:
            cands = by_name.get((espn.name_key(p["name"]), p["position"]), [])
            if cands:                  # most recent player with that name and position
                found[p["espn_id"]] = cands[0]

    missing = [p for p in players if p["espn_id"] not in found]
    return found, missing


def name_draft_picks(draft):
    """Draft picks for players no longer on any roster come without a name; fill from player_id_map."""
    unnamed = [d["espn_id"] for d in draft if not d["name"]]
    if unnamed:
        rows = query("SELECT espn_id, name, position FROM player_id_map WHERE espn_id IN ({})".format(
            ", ".join(["%s"] * len(unnamed))), unnamed)
        known = {r["espn_id"]: r for r in rows}
        for d in draft:
            if not d["name"]:
                r = known.get(d["espn_id"])
                d["name"] = (r["name"] if r else None) or "ESPN player #{}".format(d["espn_id"])
                if r and not d["position"]:
                    d["position"] = (r["position"] or "").replace("PK", "K")
    return draft


def espn_form_args(f):
    return (f.get("espn_s2", "").strip() or None, f.get("swid", "").strip() or None)


@app.route("/cse30246/nfl_fantasy_ledger/teams/import", methods=["GET", "POST"])
@login_required
def import_espn():
    """Step 1: paste a link -> show the league's teams so the user can pick theirs."""
    if request.method == "GET":
        return render_template("import.html", league=None, link="", season=None)

    f = request.form
    link = f.get("link", "").strip()
    espn_s2, swid = espn_form_args(f)
    try:
        league_id, season, team_id = espn.parse_league_link(link)
        if f.get("season", "").isdigit():
            season = int(f["season"])
        league = espn.fetch_league(league_id, season, espn_s2, swid)
    except espn.EspnError as e:
        flash(str(e), "error")
        return render_template("import.html", league=None, link=link, season=f.get("season", ""),
                               espn_s2=espn_s2 or "", swid=swid or "")

    return render_template("import.html", league=league, link=link, season=league["season"],
                           selected=team_id, espn_s2=espn_s2 or "", swid=swid or "")


@app.route("/cse30246/nfl_fantasy_ledger/teams/import/save", methods=["POST"])
@login_required
def import_espn_save():
    """Step 2: re-download the league (don't trust the browser) and save the chosen team's roster."""
    f = request.form
    espn_s2, swid = espn_form_args(f)
    try:
        league = espn.fetch_league(f.get("league_id", ""), int(f.get("season", 0) or 0), espn_s2, swid)
    except (espn.EspnError, ValueError) as e:
        flash(str(e) if isinstance(e, espn.EspnError) else "Bad season.", "error")
        return redirect(url_for("import_espn"))

    team = next((t for t in league["teams"] if t["team_id"] == f.get("team_id")), None)
    if team is None:
        flash("Pick your team from the list.", "error")
        return redirect(url_for("import_espn"))

    found, missing = match_espn_players(team["players"])
    draft = name_draft_picks(team["draft"])
    draft_found, _ = match_espn_players(draft)
    uid = current_user_id()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Same ESPN team imported before? Update it instead of making a duplicate.
            cur.execute("""SELECT team_id FROM fantasy_teams
                           WHERE user_id = %s AND platform = 'espn' AND season = %s
                             AND external_league_id = %s AND external_team_id = %s""",
                        (uid, league["season"], league["league_id"], team["team_id"]))
            existing = cur.fetchone()

            # Team names must be unique per user+season; avoid clashing with a different team
            name = team["name"]
            cur.execute("""SELECT team_id FROM fantasy_teams
                           WHERE user_id = %s AND season = %s AND team_name = %s""",
                        (uid, league["season"], name))
            clash = cur.fetchone()
            if clash and (not existing or clash["team_id"] != existing["team_id"]):
                name = (name[:93] + " (ESPN)")

            if existing:
                team_id = existing["team_id"]
                cur.execute("""UPDATE fantasy_teams SET team_name = %s, league_name = %s, scoring_format = %s
                               WHERE team_id = %s""",
                            (name, league["league_name"], league["scoring_format"], team_id))
                cur.execute("DELETE FROM roster_entries WHERE team_id = %s", (team_id,))
            else:
                cur.execute("""INSERT INTO fantasy_teams
                                 (user_id, season, team_name, league_name, scoring_format,
                                  platform, external_league_id, external_team_id)
                               VALUES (%s, %s, %s, %s, %s, 'espn', %s, %s)""",
                            (uid, league["season"], name, league["league_name"],
                             league["scoring_format"], league["league_id"], team["team_id"]))
                team_id = cur.lastrowid

            seen = set()
            for p in team["players"]:
                gsis = found.get(p["espn_id"])
                if gsis and gsis not in seen:
                    seen.add(gsis)
                    cur.execute("""INSERT INTO roster_entries (team_id, player_id, draft_round, draft_pick)
                                   VALUES (%s, %s, %s, %s)""",
                                (team_id, gsis, p["draft_round"], p["draft_pick"]))

            # Full draft, including players since traded or dropped
            cur.execute("DELETE FROM draft_picks WHERE team_id = %s", (team_id,))
            for d in draft:
                cur.execute("""INSERT INTO draft_picks
                                 (team_id, overall_pick, draft_round, round_pick, bid_amount, keeper,
                                  player_id, player_name, position)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (team_id, d["overall"], d["round"], d["round_pick"], d["bid"], d["keeper"],
                             draft_found.get(d["espn_id"]), d["name"][:100], (d["position"] or None)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    msg = "{} '{}' from {}: {} players{}.".format(
        "Updated" if existing else "Imported", name, league["league_name"], len(seen),
        " and {} draft picks".format(len(draft)) if draft else "")
    if missing:
        msg += " Not imported: {}.".format(", ".join(
            "{} ({})".format(p["name"], p["position"] or "?") for p in missing))
    flash(msg, "ok")

    newest = query("SELECT MAX(season) AS s FROM player_week_stats")[0]["s"]
    if newest and league["season"] > newest:
        flash("Heads up: our stats database currently goes through the {} season, so points for "
              "{} will show once that data is loaded.".format(newest, league["season"]), "ok")
    return redirect(url_for("team_detail", team_id=team_id))


if __name__ == "__main__":
    app.run("0.0.0.0", port=int(os.environ.get("PORT", 5015)),
            debug=os.environ.get("FLASK_DEBUG", "0") == "1")
