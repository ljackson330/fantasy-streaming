"""NHL regular-season schedule from the NHL's public stats API (no login)."""
import json
from datetime import date

import requests

TEAM_IDS = {1: 'NJD', 2: 'NYI', 3: 'NYR', 4: 'PHI', 5: 'PIT', 6: 'BOS', 7: 'BUF', 8: 'MTL', 9: 'OTT', 10: 'TOR',
            12: 'CAR', 13: 'FLA', 14: 'TBL', 15: 'WSH', 16: 'CHI', 17: 'DET', 18: 'NSH', 19: 'STL', 20: 'CGY',
            21: 'COL', 22: 'EDM', 23: 'VAN', 24: 'ANA', 25: 'DAL', 26: 'LAK', 28: 'SJS', 29: 'CBJ', 30: 'MIN',
            52: 'WPG', 54: 'VGK', 55: 'SEA', 68: 'UTA'}

FINAL_STATES = {6, 7}  # official / final


def season_id(today=None):
    d = today or date.today()
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}{y + 1}"


def fetch_games(season=None):
    season = season or season_id()
    url = f"https://api.nhle.com/stats/rest/en/game?cayenneExp=season={season}%20and%20gameType=2"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()["data"]


def load_games(path):
    with open(path) as f:
        return json.load(f)["data"]


def schedule(games):
    """{date: [team abbrevs playing]} plus checks. Postponed future games are dropped."""
    sched, dropped = {}, 0
    for g in sorted(games, key=lambda g: g["gameDate"]):
        if g.get("gameScheduleStateId", 1) != 1 and g.get("gameStateId") not in FINAL_STATES:
            dropped += 1
            continue
        home, away = TEAM_IDS.get(g["homeTeamId"]), TEAM_IDS.get(g["visitingTeamId"])
        if not home or not away:
            continue
        sched.setdefault(g["gameDate"], []).extend([away, home])
    per_team = {}
    for teams in sched.values():
        for t in teams:
            per_team[t] = per_team.get(t, 0) + 1
    return sched, {"games": sum(len(v) for v in sched.values()) // 2, "postponed_dropped": dropped,
                   "teams": len(per_team), "min_per_team": min(per_team.values()), "max_per_team": max(per_team.values())}
