import nflreadpy as nfl

seasons = list(range(2006, 2025))

nfl.load_teams().write_csv("teams.csv")
nfl.load_schedules(seasons).write_csv("games.csv")
nfl.load_players().write_csv("players.csv")
nfl.load_rosters(seasons).write_csv("rosters.csv")
nfl.load_player_stats(seasons, summary_level="reg").write_csv("player_season_stats.csv")
nfl.load_player_stats(seasons).write_csv("player_week_stats.csv")
nfl.load_ff_opportunity(seasons).write_csv("ff_opportunity.csv")
nfl.load_ff_playerids().write_csv("ff_playerids.csv")   # ESPN/Yahoo/Sleeper -> gsis_id map
print("done")