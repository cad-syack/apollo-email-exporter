"""
Export emails of your saved Apollo contacts to a text file, page by page,
using Apollo's official API (no web scraping).

Setup:
    pip install requests
    Set your API key as an environment variable, e.g.
    PowerShell:  $env:APOLLO_API_KEY = "your_key")

Run:
    python apollo_emails.py
Output:
    apollo_emails.txt (one email per line; opens in Notepad)
"""

import os
import sys
import time

import requests

API_URL = "https://api.apollo.io/api/v1/contacts/search"
OUTPUT_FILE = "apollo_emails.txt"
PER_PAGE = 100          # max Apollo allows per page
DELAY_SECONDS = 1.0     # stay well under Apollo's rate limits

# Optional fallback when APOLLO_API_KEY isn't set. Never commit a real key.
DEFAULT_API_KEY = ""


def fetch_page(session, page):
    for attempt in range(5):
        resp = session.post(API_URL, json={"page": page, "per_page": PER_PAGE}, timeout=30)
        if resp.status_code == 429:  # rate limited: back off and retry
            wait = 2 ** attempt * 5
            print(f"Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Too many rate-limit retries")


def main():
    api_key = os.environ.get("APOLLO_API_KEY") or DEFAULT_API_KEY
    if not api_key:
        sys.exit("Set APOLLO_API_KEY or DEFAULT_API_KEY first.")

    session = requests.Session()
    session.headers.update({
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    })

    seen = set()
    page = 1
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        while True:
            data = fetch_page(session, page)
            contacts = data.get("contacts", [])
            total_pages = data.get("pagination", {}).get("total_pages", page)

            new = 0
            for c in contacts:
                email = (c.get("email") or "").strip().lower()
                if email and email not in seen:
                    seen.add(email)
                    out.write(email + "\n")
                    new += 1
            out.flush()
            print(f"Page {page}/{total_pages}: {new} new emails (total {len(seen)})")

            if not contacts or page >= total_pages:
                break
            page += 1
            time.sleep(DELAY_SECONDS)

    print(f"Done. {len(seen)} emails saved to {os.path.abspath(OUTPUT_FILE)}")


if __name__ == "__main__":
    main()
