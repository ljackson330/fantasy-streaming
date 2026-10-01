# Fantasy hockey streaming dashboard

A self-updating dashboard for a Yahoo NHL points league. Twice a day a GitHub Action pulls every roster, injury and suspension status, the waiver wire, this week's adds and recent transactions from Yahoo, plus the NHL schedule. It combines them with your projections and rebuilds the dashboard:

- **Weekly streaming**: an add plan that fits your weekly add limit to the days your lineup has open slots, the best single pickups, your day-by-day lineup gaps, and the week's NHL schedule with light nights marked.
- **League watch**: status changes since the last update, your injured or suspended players, and the league's latest moves.
- **Replacement level**: the waiver wire against every team's weakest starters, by position.

## One-time setup (about 15 minutes)

1. **Create a Yahoo app.** Go to <https://developer.yahoo.com/apps/create/>. Pick any name, choose *Confidential Client*, check **Fantasy Sports → Read**, and set the redirect URI to `oob` (if Yahoo rejects that, use `https://localhost:8080`). Note the Client ID and Client Secret.
2. **Authorize once.** On your computer, with Python installed: `pip install requests`, then `python scripts/yahoo_auth.py`. Sign in, click Agree, paste the code back. It prints your refresh token.
3. **Add GitHub secrets.** In this repo: Settings → Secrets and variables → Actions → *New repository secret*: `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, `YAHOO_REFRESH_TOKEN`. If you used the localhost redirect, also add a *variable* `YAHOO_REDIRECT_URI` = `https://localhost:8080`.
4. **Set your league.** Edit `config.json` and put your league ID in `league_id`. It's the number in your league's URL: `hockey.fantasysports.yahoo.com/hockey/<league_id>`.
5. **Run it.** Actions tab → *Update dashboard* → *Run workflow*. After that it runs on its own at about 7 am and 4 pm Mountain.

Your team is picked automatically (the one owned by the Yahoo account you authorized).

## If the Yahoo API isn't available: pasted rosters

Without working Yahoo secrets, or if Yahoo refuses the app, the job falls back to `rosters/latest.txt`. To refresh it:

1. In Yahoo, open each team's roster page, select all (Ctrl/Cmd+A), copy, and paste it into the file one team after another. The order and the extra page text don't matter.
2. On GitHub, open `rosters/latest.txt`, click the pencil, replace everything with your paste, and commit. That triggers a rebuild.

Injury and suspension statuses come through from the pasted pages. Waiver flags, transactions and your adds-used count need the Yahoo API, so set adds used on the dashboard yourself. The dashboard warns when pasted rosters are more than 2 days old. Once Yahoo access works, the API is used automatically and this file is ignored.

## Updating projections

Projections come from the Data Driven Hockey rankings exports, which sit behind a Patreon login, so they're uploaded by hand. When you download new ones, open the `projections/` folder on GitHub → *Add file → Upload files*, and drop in both CSVs, keeping names like `skater-rankings_2026-10-14.csv`. The upload triggers a rebuild, and the newest-dated pair is always used. The dashboard warns when projections are more than 10 days old.

## Viewing the dashboard

The built page is `site/index.html`, committed after every run. Two ways to view it:

- **GitHub Pages (public link).** Settings → Pages → Source: *GitHub Actions*, then add a repository variable `PUBLISH_PAGES` = `true`. The link is public on a free GitHub plan, and the page includes values derived from your paid projections, so keep that in mind before sharing it.
- **Private Claude artifact.** Keep Pages off and have a scheduled Claude task republish `site/index.html` to your existing private artifact after each run.

## Running locally

```
pip install -r requirements.txt
python src/build.py --offline fixtures/sample_league.json --schedule-file fixtures/nhl_games_2026-27.json
```

That builds `site/index.html` from the sample league (rosters as of Sept 30) without touching Yahoo or the NHL API. For live data, set the three `YAHOO_*` environment variables and run `python src/build.py`.

## How it decides

- A player's expected points per team game = projected points per game × his projected share of his team's remaining games. Goalies are weighted by projected share of starts.
- Each day, the lineup starts the best healthy players with a game, up to the league's F/D/G slots. Players listed O, IR, IR-LT, IR-NR, SUSP or NA are left out; DTD players still count but are flagged.
- The planner tries every sequence of moves through your 1–2 stream spots within your remaining adds, skips players on waivers or listed out, never re-adds a player it dropped that week, and only spends an add worth at least half a point.
- Postponed games disappear from the schedule automatically.
