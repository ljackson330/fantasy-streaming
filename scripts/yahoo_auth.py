"""One-time Yahoo login: prints the refresh token to store as the YAHOO_REFRESH_TOKEN GitHub secret.

Run on your own computer:  python scripts/yahoo_auth.py
It tests the new token against the Fantasy API before printing it, so a token it prints is known to work.
"""
import getpass
import json
import os
import sys
import urllib.parse
import webbrowser

import requests

TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API = "https://fantasysports.yahooapis.com/fantasy/v2/"

print("Yahoo Fantasy API one-time authorization\n")
print("Client ID is the LONG value (about 90-100 characters, often ending in '--').")
print("Client Secret is the SHORT one (about 40 characters).\n")
client_id = input("Client ID: ").strip()
client_secret = getpass.getpass("Client secret (hidden): ").strip()
redirect = input("Redirect URI from your Yahoo app [https://localhost:8080]: ").strip() or "https://localhost:8080"
if len(client_id) < len(client_secret):
    print("\nWarning: the client ID is shorter than the secret. They may be swapped.\n")


def authorize(scope):
    params = {"client_id": client_id, "redirect_uri": redirect, "response_type": "code"}
    if scope:
        params["scope"] = scope
    url = "https://api.login.yahoo.com/oauth2/request_auth?" + urllib.parse.urlencode(params)
    print("\nOpening Yahoo in your browser. Sign in and click Agree.")
    print("If it doesn't open, visit:\n" + url)
    webbrowser.open(url)
    print("\nYou'll land on a blank localhost page (that's expected). Click its address bar,")
    print("copy the whole address, and paste it here right away. Codes expire in minutes.\n")
    code = input("Paste address or code: ").strip()
    if "code=" in code:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query).get("code", [code])[0]
    r = requests.post(TOKEN_URL, auth=(client_id, client_secret),
                      data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"\nToken exchange failed ({r.status_code}): {r.text}\n"
                 "invalid_client: ID/secret wrong or swapped. invalid_grant: code expired or already used; run again.")
    return r.json()


def fantasy_check(access_token):
    """Try several endpoints: some apps are blocked from game-wide lookups but can read the user's own leagues."""
    h = {"Authorization": f"Bearer {access_token}"}
    ok, report = False, []
    for path in ["users;use_login=1/games;game_codes=nhl/leagues?format=json", "game/nhl?format=json"]:
        r = requests.get(API + path, headers=h, timeout=30)
        report.append(f"  {path.split('?')[0]}: {r.status_code}")
        if r.status_code == 200 and path.startswith("users"):
            ok = True
            keys = sorted(set(__import__('re').findall(r'"league_key":"([^"]+)"', r.text)))
            report.append(f"    leagues found: {', '.join(keys) or 'none'}")
    print("\nEndpoint check:\n" + "\n".join(report))
    return (200, "") if ok else (403, "\n".join(report))


# First try with the Fantasy read scope stated explicitly; fall back to the app's default scopes.
tok = None
for scope in ("fspt-r", None):
    print(f"\n--- Authorizing{' with scope ' + scope if scope else ' with the app default scopes'} ---")
    try:
        t = authorize(scope)
    except SystemExit as e:
        if scope:
            print(e, "\nTrying again without an explicit scope.")
            continue
        raise
    status, body = fantasy_check(t["access_token"])
    if status == 200:
        tok = t
        print("\nFantasy API check: OK")
        break
    print(f"\nFantasy API check FAILED ({status}): {body}")
    if scope:
        print("Trying again with the app's default scopes.")

if not tok:
    sys.exit("\nThe token signs in but can't read Fantasy data. In your Yahoo app, uncheck any 'OpenID Connect' "
             "permissions so only 'Fantasy Sports - Read' is selected, click Update, wait a few minutes, and run this again.\n"
             "If you have more than one Yahoo app, make sure this client ID belongs to the one with Fantasy Sports enabled.")

print("\nSuccess. Add these as GitHub repository secrets (Settings → Secrets and variables → Actions):\n")
print(f"  YAHOO_CLIENT_ID      = {client_id}")
print("  YAHOO_CLIENT_SECRET  = (the secret you just entered)")
print(f"  YAHOO_REFRESH_TOKEN  = {tok['refresh_token']}")
print(f"\n  (refresh token is {len(tok['refresh_token'])} characters; copy all of it, nothing else)")
print(f"\nAnd a repository variable (Variables tab): YAHOO_REDIRECT_URI = {redirect}")
