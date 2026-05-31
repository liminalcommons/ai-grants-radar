#!/usr/bin/env python3
"""
verify-deadlines.py — re-derive the deadline status of every grant in
grants.json against TODAY, and report the breakdown.

The deadline status (open | rolling | upcoming | expired | unknown) is a
PROJECTION of the `deadline` / `deadlineDate` fields, computed by
grants_lib.derive_deadline. Running this re-stamps every record so the live
site never shows a year-old opportunity as if you could still apply, and never
buries a live recurring program just because its last window passed.

Usage:
  python verify-deadlines.py            # re-derive + save + report
  python verify-deadlines.py --dry-run  # report only, no write
"""

import sys
import datetime
from collections import Counter

import grants_lib as gl


def main():
    dry = "--dry-run" in sys.argv
    today = datetime.date.today()
    grants = gl.load_existing()

    before = Counter(g.get("deadlineStatus", "unknown") for g in grants)
    changed = []
    for g in grants:
        old = g.get("deadlineStatus")
        d = gl.derive_deadline(g, today)
        if d["deadlineStatus"] != old:
            changed.append((g.get("name", "?"), old, d["deadlineStatus"]))
        g.update(d)
    after = Counter(g.get("deadlineStatus") for g in grants)

    order = ["open", "rolling", "upcoming", "expired", "unknown"]
    print(f"Re-derived {len(grants)} grants against {today.isoformat()}\n")
    print(f"{'status':<10} before  after")
    for s in order:
        print(f"{s:<10} {before.get(s, 0):>6} {after.get(s, 0):>6}")

    expired = [g for g in grants if g.get("deadlineStatus") == "expired"]
    if expired:
        print(f"\n--- EXPIRED ({len(expired)}) — shown last, hidden by default ---")
        for g in sorted(expired, key=lambda x: x.get("deadlineDate") or ""):
            print(f"  {g.get('deadlineDate')}  {g.get('name', '')[:60]}")

    if changed:
        print(f"\n--- status changed ({len(changed)}) ---")
        for name, old, new in changed:
            print(f"  {old} -> {new:<9} {name[:55]}")

    if dry:
        print("\n[dry-run] not saved.")
        return
    gl.save(grants)
    print(f"\nSaved grants.json ({len(grants)} grants).")


if __name__ == "__main__":
    main()
