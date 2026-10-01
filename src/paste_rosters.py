"""Parse Yahoo team roster pages copied from the browser (select all, copy, paste) into the league structure.

Paste each team's roster page one after another into rosters/latest.txt. Team names are read from the
"<Team>'s Goaltenders roster for <date>" line on each page. Statuses (DTD, IR, IR-NR, NA, O, SUSP) are read
from the player rows. Waiver status and transactions aren't on these pages, so they're left empty.
"""
import re

SLOTS = {"F", "D", "G", "BN", "IR", "IR+", "NA", "C", "LW", "RW", "W", "Util"}
STATUSES = ["IR-LT", "IR-NR", "IR", "DTD", "SUSP", "NA", "PUP", "O"]
MARKERS = ["No new player Notes", "New Player Note", "Player Note"]
DETAIL = re.compile(r"\s+([A-Z]{2,4})\s+-\s+([A-Z,]+)\s*$")
GOALIE_HDR = re.compile(r"^(.*?)(?:'s|’s)\s+Goaltenders roster for\s+(\d{4}-\d{2}-\d{2})")


def parse(text, slots=None, max_adds=None):
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    pending, teams, rosters, asof = [], [], [], None
    i = 0
    while i < len(lines):
        line = lines[i]
        m = GOALIE_HDR.match(line)
        if m:
            name = m.group(1).strip()
            asof = asof or m.group(2)
            # goalie rows follow the header, up to the next team's first skater row or header
            j, goalies = i + 1, []
            while j < len(lines) and not GOALIE_HDR.match(lines[j]):
                p, nj = _player_at(lines, j)
                if p and p["pos"] == "G":
                    goalies.append(p); j = nj
                elif p:
                    break
                else:
                    j += 1
            for p in pending + goalies:
                p["owner"] = name
                rosters.append(p)
            teams.append({"key": f"paste.{len(teams) + 1}", "name": name, "mine": False, "manager": ""})
            pending, i = [], j
            continue
        p, nj = _player_at(lines, i)
        if p:
            pending.append(p); i = nj
        else:
            i += 1
    if pending:
        raise ValueError(f"{len(pending)} players at the end have no team (missing a 'Goaltenders roster for' line): "
                         + ", ".join(p['name'] for p in pending[:5]))
    return {
        "league": {"key": "pasted", "name": "", "slots": slots or {"F": 6, "D": 4, "G": 2},
                   "max_weekly_adds": max_adds, "week_start": "", "week_end": "", "asof": asof},
        "teams": teams, "rosters": rosters, "available": [], "transactions": [],
    }


def _player_at(lines, i):
    """Slot line, plain-name line, then '<name><status?><marker> TEAM - POS'. Returns (player, next index)."""
    if i + 2 >= len(lines) or lines[i] not in SLOTS:
        return None, i
    slot, name, detail = lines[i], lines[i + 1], lines[i + 2]
    if not detail.startswith(name):
        return None, i
    rest = detail[len(name):]
    d = DETAIL.search(rest)
    if not d:
        return None, i
    head = rest[:d.start()]
    for mk in MARKERS:
        if head.endswith(mk):
            head = head[: -len(mk)]
            break
    status = head if head in STATUSES else ""
    return {"name": name, "nhl": d.group(1), "pos": d.group(2), "selected": slot, "status": status,
            "status_full": "", "injury_note": "", "ownership": "team", "eligible": d.group(2).split(",")}, i + 3
