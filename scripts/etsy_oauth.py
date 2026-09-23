#!/usr/bin/env python3
"""Mint an ETSY_OAUTH_TOKEN for the Earl Biggers shop.

Etsy's v3 API needs three things: the app keystring, the shared secret, and a
per-user OAuth bearer token. The first two live in /app/tee-empire/.env already;
this script walks the authorization-code + PKCE exchange that produces the third.

It cannot be automated away — Etsy requires *you* to sign in and press Allow in a
browser. Nothing here is written back to .env; the script prints the values and
you paste them in.

    python3 scripts/etsy_oauth.py                  # step 1: print the consent URL
    python3 scripts/etsy_oauth.py --code <code> --verifier <verifier>

Step 1 prints a URL and a code_verifier. Open the URL, sign in as the shop owner,
press Allow, and Etsy redirects to the redirect URI with ?code=...&state=... in
the address bar (the page itself will fail to load unless you happen to be running
a server there — that is fine, the code is in the URL). Feed that code plus the
verifier back in as step 2.

The redirect URI must match one registered on the app exactly. Register
http://localhost/ on the Etsy app page if nothing is registered yet.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.etsy import EtsyClient  # noqa: E402

DEFAULT_REDIRECT = "http://localhost/"
# listings_w/r are what create_draft_listing + upload_listing_image need;
# shops_r resolves the shop; transactions_r is for get_shop_receipts.
SCOPES = ["listings_w", "listings_r", "shops_r", "transactions_r"]


def _load_env(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if v and k not in os.environ:
            os.environ[k] = v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--redirect", default=DEFAULT_REDIRECT,
                    help=f"redirect URI registered on the Etsy app (default: {DEFAULT_REDIRECT})")
    ap.add_argument("--code", help="authorization code from the redirect URL (step 2)")
    ap.add_argument("--verifier", help="code_verifier printed in step 1 (step 2)")
    args = ap.parse_args()

    _load_env(Path(__file__).resolve().parents[1] / ".env")
    keystring = os.environ.get("ETSY_API_KEY", "")
    if not keystring:
        print("ETSY_API_KEY is not set in /app/tee-empire/.env", file=sys.stderr)
        return 2

    if not args.code:
        info = EtsyClient.build_authorize_url(client_id=keystring,
                                              redirect_uri=args.redirect,
                                              scopes=SCOPES)
        print("1. Open this URL as the shop owner and press Allow:\n")
        print(info["url"])
        print("\n2. Etsy redirects to %s?code=...&state=%s" % (args.redirect, info["state"]))
        print("   Copy the code out of the address bar, then run:\n")
        print("   python3 scripts/etsy_oauth.py --code <code> --verifier %s" % info["code_verifier"])
        return 0

    if not args.verifier:
        print("--code needs the matching --verifier from step 1", file=sys.stderr)
        return 2
    tokens = EtsyClient.exchange_code(client_id=keystring, redirect_uri=args.redirect,
                                      code=args.code, code_verifier=args.verifier)
    access = tokens.get("access_token", "")
    refresh = tokens.get("refresh_token", "")
    print("Paste into /app/tee-empire/.env (chmod 600, gitignored):\n")
    print("ETSY_OAUTH_TOKEN=%s" % access)
    if refresh:
        print("\nKeep the refresh token somewhere safe; access tokens expire in ~1h.")
        print("Refresh with EtsyClient.refresh(client_id, refresh_token):")
        print("ETSY_REFRESH_TOKEN=%s" % refresh)
    print("\nfull response keys: %s" % ", ".join(sorted(tokens)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
