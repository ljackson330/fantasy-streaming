"""One-time Yahoo login: prints the refresh token to store as the YAHOO_REFRESH_TOKEN GitHub secret.

Run on your own computer:  python scripts/yahoo_auth.py
"""
import getpass
import sys
import urllib.parse
import webbrowser

import requests

print("Yahoo Fantasy API one-time authorization\n")
client_id = input("Client ID: ").strip()
client_secret = getpass.getpass("Client secret (hidden): ").strip()
redirect = input("Redirect URI from your Yahoo app [oob]: ").strip() or "oob"

url = "https://api.login.yahoo.com/oauth2/request_auth?" + urllib.parse.urlencode(
    {"client_id": client_id, "redirect_uri": redirect, "response_type": "code"})
print("\nOpening Yahoo in your browser. Sign in and click Agree.")
print("If it doesn't open, visit:\n" + url)
webbrowser.open(url)
print("\nYahoo then shows a code, or (with a localhost redirect) sends you to a page that won't load:")
print("copy the value after 'code=' in that page's address bar.\n")
code = input("Code: ").strip()
if "code=" in code:
    code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query).get("code", [code])[0]

r = requests.post("https://api.login.yahoo.com/oauth2/get_token", auth=(client_id, client_secret),
                  data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}, timeout=30)
if r.status_code != 200:
    sys.exit(f"\nToken exchange failed ({r.status_code}): {r.text}")
tok = r.json()
print("\nSuccess. Add these as GitHub repository secrets (Settings → Secrets and variables → Actions):\n")
print(f"  YAHOO_CLIENT_ID      = {client_id}")
print("  YAHOO_CLIENT_SECRET  = (the secret you just entered)")
print(f"  YAHOO_REFRESH_TOKEN  = {tok['refresh_token']}")
print(f"\n  (refresh token is {len(tok['refresh_token'])} characters; copy all of it, nothing else)")

# Prove the refresh token works before you store it.
chk = requests.post("https://api.login.yahoo.com/oauth2/get_token", auth=(client_id, client_secret),
                    data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "redirect_uri": redirect}, timeout=30)
print("\nRefresh check:", "OK, this token will work in GitHub." if chk.status_code == 200 else f"FAILED ({chk.status_code}): {chk.text}")
if redirect != "oob":
    print(f"\nAlso add a repository variable YAHOO_REDIRECT_URI = {redirect}")
