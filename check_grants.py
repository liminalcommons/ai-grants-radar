#!/usr/bin/env python3
"""
check_grants.py — liveness audit of every grant in grants.json (Phase 1).

For each grant it fetches the funder URL with the pipeline's polite fetcher
(scrape.fetch.fetch_many: 1 rps/host, retries, transient flags) and stamps:
  last_checked = today (ISO date)
  check_ok     = 1 (page alive) | 0 (dead/blocked) | unset (transient: unknown)

No engine calls, no extraction: alive-or-not only. Changed/dead/blocked ids go
to changed.json, which weekly.py feeds to refresh.py --ids (Phase 2: capped
DeepSeek re-extract of exactly those pages).

Usage:
  python check_grants.py                 # all grants
  python check_grants.py --limit 20      # pilot
  python check_grants.py --ids 4,9,25    # specific rows
  python check_grants.py --dry-run       # report only, no write
"""

import argparse
import datetime
import json
import os
import sys

import grants_lib as gl
from scrape.fetch import fetch_many

DIR = os.path.dirname(os.path.abspath(__file__))
CHANGED_PATH = os.path.join(DIR, "changed.json")


def stamp(grant, result, today):
    """Stamp one grant from a fetch result. Returns 'alive'|'dead'|'blocked'|'unknown'."""
    grant["last_checked"] = today
    status = (result or {}).get("status")
    if status in ("ok", "redirect"):
        grant["check_ok"] = 1
        return "alive"
    if status in ("dead", "blocked"):
        if (result or {}).get("transient"):
            grant.pop("check_ok", None)
            return "unknown"
        grant["check_ok"] = 0
        return status
    grant.pop("check_ok", None)
    return "unknown"


def run(grants, today, fetch_fn=fetch_many, ids=None, limit=None, sync_db=True):
    work = [g for g in grants if ids is None or g.get("id") in ids]
    if limit:
        work = work[:limit]
    urls = [g["url"] for g in work if g.get("url")]
    results = fetch_fn(urls) if urls else {}
    tally = {"alive": 0, "dead": 0, "blocked": 0, "unknown": 0}
    flagged = []
    for g in work:
        outcome = stamp(g, results.get(g.get("url", "")), today)
        tally[outcome] += 1
        if outcome in ("dead", "blocked"):
            flagged.append(g["id"])
    if sync_db and work:
        import grants_db
        conn = grants_db.connect(grants_db.DEFAULT_DB)
        try:
            for g in work:
                grants_db.upsert(conn, g)
            conn.commit()
        finally:
            conn.close()
    return tally, flagged


def main(argv=None):
    ap = argparse.ArgumentParser(description="Liveness audit of grants.json")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="comma-separated grant ids")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    ids = {int(x) for x in args.ids.split(",") if x.strip()} if args.ids else None
    today = datetime.date.today().isoformat()
    grants = gl.load_existing()
    tally, flagged = run(grants, today, ids=ids, limit=args.limit)

    total = sum(tally.values())
    print(f"Checked {total} grants against {today}")
    for k in ("alive", "dead", "blocked", "unknown"):
        print(f"  {k:<8} {tally[k]:>5}")
    if flagged:
        print(f"  flagged {len(flagged)} for re-extract: {flagged[:20]}")

    if args.dry_run:
        print("[dry-run] not saved.")
        return {"tally": tally, "flagged": flagged, "saved": False}
    gl.save(grants)
    with open(CHANGED_PATH, "w", encoding="utf-8") as f:
        json.dump({"date": today, "ids": flagged}, f)
    print(f"Saved grants.json ({len(grants)} grants) + changed.json ({len(flagged)} ids).")
    return {"tally": tally, "flagged": flagged, "saved": True}


if __name__ == "__main__":
    main()
