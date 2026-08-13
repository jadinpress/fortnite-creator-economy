#!/usr/bin/env python3
"""
Pull a single timestamped snapshot of the three pages this project needs from fortnite.gg.

SOURCE
------
fortnite.gg is an unofficial, fan-run site (not affiliated with Epic). It publishes data Epic
never exposes officially: a full population breakdown of UEFN creator earnings, plus ranked
leaderboards for creator engagement and map player counts. See docs/data-source-audit.md for the
full check this script's design is based on - in short: no ToS page, robots.txt disallows only
query-string pagination on these paths (not the base pages), and the values needed are present in
server-rendered HTML (confirmed with a plain curl request), so no headless-browser rendering is
required here.

DEPTH, PER PAGE (see the audit for the full reasoning)
--------------------------------------------------------
  /player-count   Creator-earnings buckets: FULL population (8 bins, sums to the site's own
                  live creator-count total).
  /creators       Creator engagement, ranked by Players Now: TOP 30 ONLY. Further rows sit
                  behind ?page=N, which robots.txt explicitly disallows - this script does not
                  request it.
  /creative       Map attention, ranked by Players Now: TOP 28 ONLY. Same pagination rule,
                  same reason it stops at the first page.

ON SCRAPING POLITELY
---------------------
No ToS page exists, which is not the same as explicit permission. This script is deliberately
conservative, same posture as the sibling steam-retention project's steamcharts scraper:

  - one request at a time, never concurrent
  - >=1.5s between requests (this project only ever needs 3), with jitter
  - every response cached to disk with a manifest recording exactly when and what
  - a User-Agent that says who this is and why
  - no pagination - the three base pages only, ever

This is a SNAPSHOT, not a scrape to resume. Re-running does not "continue" a previous pull; it
takes a brand new snapshot and will not reproduce the same numbers (the site's counters move
constantly). The raw HTML saved here IS the reproducibility record for whatever numbers end up
in the analysis - that's why data/raw/ is committed instead of gitignored.

Usage:
    python scripts/scrape_fortnitegg.py
"""

import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

PAGES = {
    "player_count": "https://fortnite.gg/player-count",
    "creators": "https://fortnite.gg/creators",
    "creative": "https://fortnite.gg/creative",
}

# Identify the scraper honestly.
USER_AGENT = (
    "FortniteCreatorEconomyResearch/1.0 (portfolio data analysis project; "
    "contact: spore-croon-subpar@duck.com)"
)

DELAY = 1.5  # seconds between requests, plus jitter


def fetch(session, name, url):
    """Return (html_or_None, status_code_or_None, error_or_None) for one page."""
    try:
        resp = session.get(url, timeout=30)
    except requests.RequestException as exc:
        return None, None, str(exc)

    if resp.status_code != 200:
        return None, resp.status_code, f"HTTP {resp.status_code}"

    return resp.text, resp.status_code, None


def main():
    raw_dir = Path(__file__).resolve().parent.parent / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest = []
    failures = []

    print(f"Snapshot: {snapshot_id}")
    for i, (name, url) in enumerate(PAGES.items()):
        if i > 0:
            time.sleep(DELAY + random.uniform(0, 0.4))

        fetched_at = datetime.now(timezone.utc).isoformat()
        html, status, error = fetch(session, name, url)

        if html is None:
            print(f"  [{name}] FAILED: {error}", flush=True)
            failures.append((name, url, status, error))
            continue

        out_path = raw_dir / f"{name}_{snapshot_id}.html"
        out_path.write_text(html, encoding="utf-8")
        manifest.append({
            "page": name,
            "url": url,
            "fetched_at": fetched_at,
            "status": status,
            "bytes": len(html),
            "file": out_path.name,
        })
        print(f"  [{name}] OK - {len(html):,} bytes -> {out_path.name}", flush=True)

    if failures:
        print()
        print(f"{len(failures)} of {len(PAGES)} pages failed. Not writing a manifest for a "
              "partial snapshot - fix the failure and re-run.", flush=True)
        for name, url, status, error in failures:
            print(f"  {name}: {url} - status={status} error={error}")
        sys.exit(1)

    # Manifest lives alongside the raw files it describes - it's what run_analysis.py reads
    # to find "the latest snapshot" and it's what makes "when was this pulled" answerable
    # without guessing from file mtimes.
    import json
    manifest_path = raw_dir / f"manifest_{snapshot_id}.json"
    manifest_path.write_text(json.dumps({
        "snapshot_id": snapshot_id,
        "pages": manifest,
    }, indent=2), encoding="utf-8")

    print()
    print(f"Snapshot {snapshot_id} complete: {len(manifest)}/{len(PAGES)} pages.")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
