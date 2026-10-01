"""Build the streaming dashboard: Yahoo league state + NHL schedule + projections -> site/index.html.

Usage:
  python src/build.py                       # live: Yahoo + NHL APIs (needs YAHOO_* env vars)
  python src/build.py --offline FIXTURE.json --schedule-file game.json   # no network
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import nhl  # noqa: E402
import paste_rosters  # noqa: E402
import projections  # noqa: E402
import yahoo  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAHOO_TEAM_FIX = {"TB": "TBL", "NJ": "NJD", "LA": "LAK", "SJ": "SJS", "UTAH": "UTA", "WAS": "WSH", "MON": "MTL", "CLS": "CBJ"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def pos_group(p):
    parts = set((p or "").replace(" ", "").split(","))
    if "G" in parts:
        return "G"
    if parts & {"C", "LW", "RW", "W", "F"}:
        return "F"
    if "D" in parts:
        return "D"
    return "F"


def slot_counts(slots):
    out = {"F": slots.get("F", 0) + slots.get("C", 0) + slots.get("LW", 0) + slots.get("RW", 0) + slots.get("W", 0),
           "D": slots.get("D", 0), "G": slots.get("G", 0)}
    return out if sum(out.values()) else {"F": 6, "D": 4, "G": 2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", help="Yahoo fixture JSON instead of the live API")
    ap.add_argument("--schedule-file", help="NHL stats-API game JSON instead of fetching it")
    ap.add_argument("--today", help="Override today's date (YYYY-MM-DD)")
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    today = args.today or date.today().isoformat()

    proj, pmeta = projections.load(os.path.join(ROOT, "projections"))
    games = nhl.load_games(args.schedule_file) if args.schedule_file else nhl.fetch_games(nhl.season_id(date.fromisoformat(today)))
    sched, scheck = nhl.schedule(games)

    paste_path = os.path.join(ROOT, "rosters", "latest.txt")
    source = "yahoo"
    if args.offline:
        yd, source = json.load(open(args.offline)), "sample"
    else:
        yd, err = None, None
        if os.environ.get("YAHOO_REFRESH_TOKEN", "").strip():
            try:
                yd = yahoo.fetch_league(yahoo.Yahoo(), cfg["league_id"], today)
            except Exception as e:  # noqa: BLE001
                err = e
                print(f"Yahoo API unavailable, using pasted rosters instead:\n{e}")
        if yd is None:
            if not os.path.exists(paste_path):
                raise SystemExit(f"No Yahoo access and no {paste_path}. Paste your league's roster pages there.") from err
            yd = paste_rosters.parse(open(paste_path, encoding="utf-8").read(),
                                     max_adds=cfg.get("max_weekly_adds", 4))
            source = "paste"
            print(f"Pasted rosters: {len(yd['teams'])} teams, {len(yd['rosters'])} players, as of {yd['league'].get('asof')}")
    adds = yahoo.adds_this_week(yd)

    # ---- match Yahoo players to projections ----
    proj = proj.reset_index(drop=True)
    proj["key"] = proj.name.map(norm)
    proj["last"] = proj.name.map(lambda n: norm(n.split()[-1]))
    by_key = {}
    for i, r in proj.iterrows():
        by_key.setdefault((r.key, r.pos), []).append(i)

    def match(p):
        nhl_t = YAHOO_TEAM_FIX.get(p["nhl"], p["nhl"])
        g = pos_group(p["pos"])
        c = by_key.get((norm(p["name"]), g), [])
        if len(c) > 1:
            c = [i for i in c if proj.at[i, "nhl"] == nhl_t] or c[:1]
        if not c:  # nickname differences: same last name, team and position
            c = proj.index[(proj["last"] == norm(p["name"].split()[-1])) & (proj.nhl == nhl_t) & (proj.pos == g)].tolist()
            if len(c) != 1:
                return None
        return c[0]

    proj["owner"] = None; proj["status"] = ""; proj["out"] = False; proj["waiver"] = False; proj["note"] = ""
    unmatched = []
    for p in yd["rosters"]:
        i = match(p)
        if i is None:
            unmatched.append({"name": p["name"], "owner": p["owner"], "pos": p["pos"]})
            continue
        proj.at[i, "owner"] = p["owner"]
        proj.at[i, "status"] = p.get("status", "")
        proj.at[i, "note"] = p.get("injury_note", "")
        proj.at[i, "out"] = p.get("status", "") in yahoo.OUT_STATUSES or p.get("selected", "") in ("IR", "IR+", "NA")
        proj.at[i, "nhl"] = YAHOO_TEAM_FIX.get(p["nhl"], p["nhl"]) or proj.at[i, "nhl"]  # follow trades
    for p in yd.get("available", []):
        i = match(p)
        if i is None or proj.at[i, "owner"]:
            continue
        proj.at[i, "status"] = p.get("status", "")
        proj.at[i, "note"] = p.get("injury_note", "")
        proj.at[i, "out"] = p.get("status", "") in yahoo.OUT_STATUSES
        proj.at[i, "waiver"] = p.get("ownership") == "waivers"
        proj.at[i, "nhl"] = YAHOO_TEAM_FIX.get(p["nhl"], p["nhl"]) or proj.at[i, "nhl"]

    # share of team games each player is projected to play, from the projection date on
    pdate = pmeta["date"] or today
    remaining = {}
    for d, teams in sched.items():
        if d >= pdate:
            for t in teams:
                remaining[t] = remaining.get(t, 0) + 1
    proj["avail"] = [min(1.0, gp / max(1, remaining.get(t, 82))) for gp, t in zip(proj.gp, proj.nhl)]

    slots = slot_counts(yd["league"].get("slots", {}))
    proj["role"] = "FA"
    team_names = [t["name"] for t in yd["teams"]]
    for team in team_names:
        for pos, n in slots.items():
            r = proj[(proj.owner == team) & (proj.pos == pos)]
            proj.loc[r[r.out].index, "role"] = "IR"
            healthy = r[~r.out].sort_values("ppg", ascending=False)
            proj.loc[healthy.index[:n], "role"] = "Starter"
            proj.loc[healthy.index[n:], "role"] = "Bench"

    players = []
    for r in proj.itertuples():
        players.append({"name": r.name, "nhl": r.nhl, "pos": r.pos, "fp": round(r.fp, 1), "gp": round(r.gp, 1),
                        "ppg": round(r.ppg, 3), "avail": round(r.avail, 3), "owner": r.owner, "role": r.role,
                        "status": r.status or "", "note": r.note or "", "waiver": bool(r.waiver)})

    # ---- changes since the previous run ----
    prev_path = os.path.join(ROOT, "data", "latest.json")
    changes = []
    if os.path.exists(prev_path):
        prev = {(p["name"], p["nhl"]): p for p in json.load(open(prev_path)).get("players", [])}
        for p in players:
            q = prev.get((p["name"], p["nhl"]))
            if not q or not (p["owner"] or q.get("owner")):
                continue
            if q.get("status", "") != p["status"]:
                changes.append({"name": p["name"], "owner": p["owner"] or q.get("owner"), "from": q.get("status", "") or "Healthy", "to": p["status"] or "Healthy"})
            elif q.get("owner") != p["owner"]:
                changes.append({"name": p["name"], "owner": p["owner"] or "Free agent", "from": q.get("owner") or "Free agent", "to": p["owner"] or "Free agent", "kind": "move"})

    tx = []
    for t in sorted(yd.get("transactions", []), key=lambda t: -t.get("ts", 0))[:20]:
        tx.append({"time": t["time"], "type": t["type"], "moves": t["moves"]})

    mine = next((t["name"] for t in yd["teams"] if t.get("mine")), None) or cfg.get("default_team") or team_names[0]
    data = {
        "players": players, "teams": team_names, "slots": slots, "sched": sched, "myTeam": mine,
        "maxAdds": yd["league"].get("max_weekly_adds") or cfg.get("max_weekly_adds", 4),
        "addsUsed": adds, "weekStart": yd["league"].get("week_start"), "weekEnd": yd["league"].get("week_end"),
        "transactions": tx, "changes": changes, "unmatched": unmatched,
        "meta": {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "projections": pmeta,
                 "schedule": scheck, "league": yd["league"].get("name", ""), "offline": bool(args.offline),
                 "rosterSource": source, "rostersAsOf": yd["league"].get("asof")},
    }

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "site"), exist_ok=True)
    json.dump(data, open(prev_path, "w"), separators=(",", ":"))
    tpl = open(os.path.join(ROOT, "src", "template.html")).read()
    html = tpl.replace("__DATA__", json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/"))
    open(os.path.join(ROOT, "site", "index.html"), "w").write(html)

    print(f"schedule: {scheck}")
    print(f"projections: {pmeta}")
    print(f"rostered matched: {len(yd['rosters']) - len(unmatched)}/{len(yd['rosters'])}; unmatched: {unmatched}")
    print(f"status changes: {len(changes)}; transactions: {len(tx)}; my team: {mine}; adds used: {adds}")


if __name__ == "__main__":
    main()
