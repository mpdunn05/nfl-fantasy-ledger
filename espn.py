"""
Read an ESPN fantasy football league from a pasted link.

ESPN has no official public API; this uses the same JSON endpoint the ESPN
fantasy website uses (the one community projects like cwendt94/espn-api call).
Public leagues work with just the link. Private leagues also need the
espn_s2 and SWID cookies from the user's browser.

Only the standard library is used, so it runs on the server's Python 3.6.
"""
import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request

API = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
VIEWS = ["mTeam", "mRoster", "mSettings", "mDraftDetail"]

# ESPN defaultPositionId -> position abbreviation
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
RECEPTION_STAT_ID = 53   # points per reception in scoringSettings

# ESPN proTeamId -> team abbreviation. Team defenses have playerId = -16000 - proTeamId.
PRO_TEAMS = {1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET",
             9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN",
             17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
             25: "SF", 26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"}


class EspnError(Exception):
    """A problem the user can fix (bad link, private league, ...). The message is shown to them."""


def current_season(today=None):
    """NFL season year: the season that started in September (Jan-Jul belong to last year's season)."""
    today = today or datetime.date.today()
    return today.year if today.month >= 8 else today.year - 1


def parse_league_link(text):
    """
    Pull leagueId / seasonId / teamId out of anything a user might paste:
      https://fantasy.espn.com/football/league?leagueId=123456&seasonId=2025
      https://fantasy.espn.com/football/team?leagueId=123456&teamId=3&seasonId=2025
      123456
    Returns (league_id, season, team_id_or_None).
    """
    text = (text or "").strip()
    if not text:
        raise EspnError("Paste your ESPN league link (or league ID).")
    if text.isdigit():
        return text, current_season(), None

    parsed = urllib.parse.urlparse(text if "://" in text else "https://" + text)
    if parsed.netloc and "espn.com" not in parsed.netloc.lower():
        raise EspnError("That doesn't look like an ESPN link. It should start with https://fantasy.espn.com/football/...")
    params = urllib.parse.parse_qs(parsed.query)

    def first(*names):
        for n in names:
            for k, v in params.items():
                if k.lower() == n.lower() and v and v[0].strip().isdigit():
                    return v[0].strip()
        return None

    league_id = first("leagueId")
    if not league_id:
        raise EspnError("Couldn't find a league ID in that link. Open your league on ESPN and copy the "
                        "address bar. It should contain 'leagueId='.")
    season = first("seasonId")
    return league_id, int(season) if season else current_season(), first("teamId")


def clean_swid(swid):
    swid = (swid or "").strip().strip("{}")
    return "{" + swid + "}" if swid else ""


def _get_json(url, espn_s2=None, swid=None, timeout=15):
    headers = {"User-Agent": "Mozilla/5.0 (NFL Fantasy Ledger class project)",
               "Accept": "application/json"}
    cookies = []
    if espn_s2:
        cookies.append("espn_s2=" + espn_s2.strip())
    if swid:
        cookies.append("SWID=" + clean_swid(swid))
    if cookies:
        headers["Cookie"] = "; ".join(cookies)

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            if espn_s2 or swid:
                raise EspnError("ESPN rejected those cookies. Copy espn_s2 and SWID again while signed in "
                                "to ESPN (they expire when you sign out).")
            raise EspnError("This league is private. Ask your league manager to turn on "
                            "'Make league viewable to public' in ESPN league settings, or use the "
                            "private league option below.")
        if e.code == 404:
            raise EspnError("ESPN couldn't find that league for that season. Check the link and the season.")
        raise EspnError("ESPN returned an error ({}). Try again in a minute.".format(e.code))
    except (urllib.error.URLError, OSError):
        raise EspnError("Couldn't reach ESPN. Try again in a minute.")
    except ValueError:
        raise EspnError("ESPN sent back something unexpected. Try again in a minute.")


def fetch_league(league_id, season, espn_s2=None, swid=None):
    """Download a league and return it in the simplified form produced by parse_league()."""
    if not str(league_id).isdigit():
        raise EspnError("League ID must be a number.")
    season = int(season)
    view = "&".join("view=" + v for v in VIEWS)
    if season >= 2018:
        url = "{}/seasons/{}/segments/0/leagues/{}?{}".format(API, season, league_id, view)
        data = _get_json(url, espn_s2, swid)
    else:   # ESPN keeps pre-2018 seasons under leagueHistory, returned as a list
        url = "{}/leagueHistory/{}?seasonId={}&{}".format(API, league_id, season, view)
        data = _get_json(url, espn_s2, swid)
        data = data[0] if isinstance(data, list) and data else data
    if not isinstance(data, dict) or not data.get("teams"):
        raise EspnError("That league has no teams for {} yet. Try a different season.".format(season))
    return parse_league(data, league_id, season)


def scoring_format(settings):
    """Map ESPN points-per-reception to our formats."""
    items = ((settings or {}).get("scoringSettings") or {}).get("scoringItems") or []
    ppr = next((i.get("points", 0) for i in items if i.get("statId") == RECEPTION_STAT_ID), 0) or 0
    if ppr >= 0.75:
        return "ppr"
    if ppr >= 0.25:
        return "half_ppr"
    return "standard"


def parse_league(data, league_id, season):
    """
    Turn ESPN's JSON into:
      {"league_id", "season", "league_name", "scoring_format",
       "teams": [{"team_id", "name", "abbrev", "owners",
                  "players": [{"espn_id", "name", "position", "draft_round", "draft_pick"}],
                  "draft":   [{"espn_id", "name", "position", "overall", "round", "round_pick",
                               "bid", "keeper"}]}]}
    """
    settings = data.get("settings") or {}
    members = {m.get("id"): (m.get("displayName") or
                             " ".join(x for x in (m.get("firstName"), m.get("lastName")) if x) or "")
               for m in data.get("members") or []}

    # Names/positions of every rostered player in the league, so draft picks that were
    # traded or dropped still get a name when they now sit on another team
    league_players = {}
    for t in data.get("teams") or []:
        for e in ((t.get("roster") or {}).get("entries") or []):
            pl = ((e.get("playerPoolEntry") or {}).get("player")) or {}
            pid = e.get("playerId") or pl.get("id")
            if pid is not None:
                league_players[int(pid)] = (pl.get("fullName"), POSITIONS.get(pl.get("defaultPositionId"), ""))

    picks = {}        # (team_id, espn player id) -> (round, overall pick)
    team_drafts = {}  # team_id -> [pick dicts]
    for p in ((data.get("draftDetail") or {}).get("picks") or []):
        pid, overall = p.get("playerId"), p.get("overallPickNumber")
        if pid is None or overall is None or int(pid) == -1:
            continue
        pid = int(pid)
        picks[(p.get("teamId"), pid)] = (p.get("roundId"), overall)
        name, pos = league_players.get(pid, (None, ""))
        if pid < 0 and not name:            # team defense, e.g. -16003 = Chicago
            abbr = PRO_TEAMS.get(-16000 - pid)
            name, pos = ("{} D/ST".format(abbr) if abbr else "D/ST"), "D/ST"
        team_drafts.setdefault(p.get("teamId"), []).append({
            "espn_id": pid,
            "name": name,                   # None = look it up later (player not on any roster now)
            "position": pos,
            "overall": int(overall),
            "round": p.get("roundId"),
            "round_pick": p.get("roundPickNumber"),
            "bid": p.get("bidAmount") or None,
            "keeper": bool(p.get("keeper")),
        })

    teams = []
    for t in data.get("teams") or []:
        name = (t.get("name") or
                " ".join(x for x in (t.get("location"), t.get("nickname")) if x).strip() or
                t.get("abbrev") or "Team {}".format(t.get("id")))
        players = []
        for e in ((t.get("roster") or {}).get("entries") or []):
            pl = ((e.get("playerPoolEntry") or {}).get("player")) or {}
            pid = e.get("playerId") or pl.get("id")
            if pid is None:
                continue
            rnd, pick = picks.get((t.get("id"), pid), (None, None))
            players.append({
                "espn_id": int(pid),
                "name": pl.get("fullName") or "Player {}".format(pid),
                "position": POSITIONS.get(pl.get("defaultPositionId"), ""),
                "draft_round": rnd,
                "draft_pick": pick,
            })
        teams.append({
            "team_id": str(t.get("id")),
            "name": name[:100],
            "abbrev": t.get("abbrev") or "",
            "owners": ", ".join(members.get(o, "") for o in (t.get("owners") or []) if members.get(o)),
            "players": players,
            "draft": sorted(team_drafts.get(t.get("id"), []), key=lambda d: d["overall"]),
        })
    teams.sort(key=lambda t: t["name"].lower())

    return {
        "league_id": str(league_id),
        "season": int(season),
        "league_name": (settings.get("name") or "ESPN League {}".format(league_id))[:100],
        "scoring_format": scoring_format(settings),
        "teams": teams,
    }


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def name_key(name):
    """Loose name match: 'D.J. Moore Jr.' -> 'djmoore'."""
    n = _SUFFIX.sub("", (name or "").lower().replace(".", "").replace("'", ""))
    return re.sub(r"[^a-z]", "", n)
