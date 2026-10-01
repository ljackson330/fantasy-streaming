"""Yahoo Fantasy Sports API client: league settings, rosters, player status, waivers, transactions.

Auth uses a long-lived OAuth2 refresh token (get one once with scripts/yahoo_auth.py).
Responses are requested as XML, which Yahoo structures far more predictably than its JSON.
"""
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

API = "https://fantasysports.yahooapis.com/fantasy/v2/"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

# Statuses that keep a player out of a lineup. DTD (day-to-day) players still count.
OUT_STATUSES = {"O", "IR", "IR-LT", "IR-NR", "SUSP", "NA", "PUP"}


def _strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _t(el, path, default=""):
    if el is None:
        return default
    found = el.find(path)
    return found.text.strip() if found is not None and found.text else default


def _clean(v):
    """Secrets pasted into GitHub often carry whitespace, newlines or quotes."""
    return (v or "").strip().strip('"').strip("'").strip()


def _describe(v):
    return f"{len(v)} chars, starts {v[:4]!r}" if v else "EMPTY"


class Yahoo:
    def __init__(self, client_id=None, client_secret=None, refresh_token=None, redirect_uri=None):
        self.client_id = _clean(client_id or os.environ.get("YAHOO_CLIENT_ID"))
        self.client_secret = _clean(client_secret or os.environ.get("YAHOO_CLIENT_SECRET"))
        self.refresh_token = _clean(refresh_token or os.environ.get("YAHOO_REFRESH_TOKEN"))
        self.redirect_uri = _clean(redirect_uri or os.environ.get("YAHOO_REDIRECT_URI")) or "oob"
        missing = [n for n, v in [("YAHOO_CLIENT_ID", self.client_id), ("YAHOO_CLIENT_SECRET", self.client_secret),
                                  ("YAHOO_REFRESH_TOKEN", self.refresh_token)] if not v]
        if missing:
            raise RuntimeError(f"Missing GitHub secrets: {', '.join(missing)}")
        self.session = requests.Session()
        self._refresh()

    def _refresh(self):
        # Yahoo can reject a refresh whose redirect_uri differs from the one used at sign-in,
        # so try the configured one first, then the common alternatives.
        tries, errors = [], []
        for ru in [self.redirect_uri, "oob", "https://localhost:8080", "https://localhost:8080/", None]:
            if ru not in tries:
                tries.append(ru)
        for ru in tries:
            data = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
            if ru:
                data["redirect_uri"] = ru
            r = requests.post(TOKEN_URL, auth=(self.client_id, self.client_secret), data=data, timeout=30)
            if r.status_code == 200:
                tok = r.json()
                self.session.headers["Authorization"] = f"Bearer {tok['access_token']}"
                if ru != self.redirect_uri:
                    print(f"Note: token refresh worked with redirect_uri={ru!r}; set the YAHOO_REDIRECT_URI variable to that.")
                return
            errors.append(f"redirect_uri={ru!r} -> {r.status_code} {r.text[:160]}")
            if "invalid_client" in r.text:
                break  # wrong client ID/secret; other redirect URIs won't help
        raise RuntimeError(
            "Yahoo token refresh failed.\n  " + "\n  ".join(errors) +
            f"\nSecrets as received: client_id {_describe(self.client_id)}, client_secret {_describe(self.client_secret)}, "
            f"refresh_token {_describe(self.refresh_token)}.\n"
            "invalid_client = client ID/secret wrong. invalid_grant on every try = the refresh token is wrong or revoked: "
            "re-run scripts/yahoo_auth.py with this same Yahoo app and paste the new refresh token "
            "(Yahoo refresh tokens are long, about 40-60 characters).")

    def get(self, path, retries=3):
        for attempt in range(retries):
            r = self.session.get(API + path, timeout=30)
            if r.status_code == 401 and attempt == 0:
                self._refresh()
                continue
            if r.status_code in (429, 500, 502, 503, 999):
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                hint = ""
                if r.status_code == 403 and "not authorized" in r.text:
                    hint = ("\nThe token works but lacks Fantasy access. Re-run scripts/yahoo_auth.py (it tests Fantasy "
                            "access before printing a token) and replace YAHOO_REFRESH_TOKEN.")
                raise RuntimeError(f"Yahoo GET {path} failed ({r.status_code}): {r.text[:300]}{hint}")
            return _strip_ns(ET.fromstring(r.content))
        raise RuntimeError(f"Yahoo GET {path} kept failing")


def parse_player(p):
    """Flatten one <player> element."""
    elig = [e.text for e in p.findall("eligible_positions/position") if e.text]
    return {
        "player_key": _t(p, "player_key"),
        "name": _t(p, "name/full"),
        "nhl": _t(p, "editorial_team_abbr").upper(),
        "pos": _t(p, "display_position"),
        "eligible": elig,
        "status": _t(p, "status"),
        "status_full": _t(p, "status_full"),
        "injury_note": _t(p, "injury_note"),
        "selected": _t(p, "selected_position/position"),
        "ownership": _t(p, "ownership/ownership_type"),
        "owner_team": _t(p, "ownership/owner_team_name"),
    }


def fetch_league(y, league_id, today=None):
    """Everything the dashboard needs from Yahoo, as plain dicts."""
    today = today or datetime.now().date().isoformat()
    # Find the league through the signed-in user's own leagues; some apps can't call the game-wide endpoint.
    lk = None
    try:
        root = y.get("users;use_login=1/games;game_codes=nhl/leagues")
        keys = [_t(lg, "league_key") for lg in root.iter("league")]
        keys = [k for k in keys if k.endswith(f".l.{league_id}") and k.split(".")[0].isdigit()]
        if keys:
            lk = max(keys, key=lambda k: int(k.split(".")[0]))  # newest season
    except RuntimeError as e:
        print(f"User leagues lookup failed, falling back to game/nhl: {e}")
    if not lk:
        game_key = _t(y.get("game/nhl"), "game/game_key")
        lk = f"{game_key}.l.{league_id}"

    settings = y.get(f"league/{lk}/settings").find("league")
    slots = {}
    for rp in settings.findall("settings/roster_positions/roster_position"):
        slots[_t(rp, "position")] = int(_t(rp, "count", "0") or 0)
    max_adds = _t(settings, "settings/max_weekly_adds")
    league = {
        "key": lk,
        "name": _t(settings, "name"),
        "current_week": _t(settings, "current_week"),
        "slots": slots,
        "max_weekly_adds": int(max_adds) if max_adds.isdigit() else None,
    }

    sb = y.get(f"league/{lk}/scoreboard").find("league/scoreboard")
    m = sb.find("matchups/matchup") if sb is not None else None
    league["week_start"] = _t(m, "week_start")
    league["week_end"] = _t(m, "week_end")

    teams = []
    for t in y.get(f"league/{lk}/teams").findall("league/teams/team"):
        teams.append({
            "key": _t(t, "team_key"),
            "name": _t(t, "name"),
            "mine": _t(t, "is_owned_by_current_login") == "1",
            "manager": _t(t, "managers/manager/nickname"),
        })

    rosters = []
    for t in teams:
        root = y.get(f"team/{t['key']}/roster;date={today}")
        for p in root.findall("team/roster/players/player"):
            d = parse_player(p)
            d["owner"] = t["name"]
            rosters.append(d)

    # Unrostered players with their waiver/free-agent status and injury status.
    available = []
    for start in range(0, 500, 25):
        root = y.get(f"league/{lk}/players;status=A;sort=AR;start={start};count=25;out=ownership")
        page = root.findall("league/players/player")
        available += [parse_player(p) for p in page]
        if len(page) < 25:
            break

    transactions = []
    root = y.get(f"league/{lk}/transactions;types=add,drop,trade;count=40")
    for tr in root.findall("league/transactions/transaction"):
        ts = int(_t(tr, "timestamp", "0") or 0)
        moves = []
        for p in tr.findall("players/player"):
            td = p.find("transaction_data")
            moves.append({
                "name": _t(p, "name/full"),
                "pos": _t(p, "display_position"),
                "nhl": _t(p, "editorial_team_abbr").upper(),
                "type": _t(td, "type"),
                "to": _t(td, "destination_team_name"),
                "to_key": _t(td, "destination_team_key"),
                "from": _t(td, "source_team_name"),
                "source": _t(td, "source_type"),
            })
        transactions.append({
            "type": _t(tr, "type"),
            "status": _t(tr, "status"),
            "time": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else "",
            "ts": ts,
            "moves": moves,
        })

    return {"league": league, "teams": teams, "rosters": rosters, "available": available, "transactions": transactions}


def adds_this_week(yd):
    """Adds per team since the start of the current fantasy week (from transactions)."""
    ws = yd["league"].get("week_start")
    if not ws:
        return {}
    start_ts = datetime.fromisoformat(ws).replace(tzinfo=timezone.utc).timestamp() + 5 * 3600  # Yahoo weeks roll over overnight US Eastern
    counts = {}
    for tr in yd["transactions"]:
        if tr["ts"] < start_ts or tr["status"] not in ("successful", ""):
            continue
        for mv in tr["moves"]:
            if mv["type"] == "add":
                counts[mv["to"]] = counts.get(mv["to"], 0) + 1
    return counts
