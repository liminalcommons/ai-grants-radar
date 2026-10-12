#!/usr/bin/env python3
"""daily.py — cheap daily scout: liveness + deadlines + small refresh + deploy.

Full discovery stays in weekly.py (Spark-heavy). This runs every day:
  1. check_grants.py   — liveness-check funder pages (plain HTTP, $0), stamp
                         last_checked/check_ok, flag dead + blocked
  2. verify-deadlines.py — re-derive deadline statuses against today ($0)
  3. refresh.py --limit 40 --max-extract 8 — re-verify only the most overdue
                         pages (bounded DeepSeek spend, ~40k tokens)
  4. build_site.py + predeploy_check.py — rebuild the wall
  5. deploy — commit + push to `pages` remote (GitHub Pages) + seed D1
  6. report NEW + DYING items to stdout (closing <= 7 days, newly dead)

Usage:
  python daily.py              # full daily run incl. deploy
  python daily.py --no-deploy  # check + rebuild only
"""

import subprocess
import sys

import grants_lib as gl

PY = sys.executable


def step(label, argv):
    print(f"\n=== {label} ===")
    try:
        subprocess.run([PY, *argv], cwd=gl.DIR, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  {label} failed: {e}")
        return False


def main():
    no_deploy = "--no-deploy" in sys.argv
    step("CheckGrants", ["check_grants.py", "--limit", "250"])
    step("VerifyDeadlines", ["verify-deadlines.py"])
    step("RefreshSmall", ["refresh.py", "--limit", "40", "--max-extract", "8"])
    step("Build", ["build_site.py"])
    step("Predeploy", ["predeploy_check.py"])
    if not no_deploy:
        step("SeedWorker", ["seed-worker.py"])
        try:
            subprocess.run(["git", "add", "-A"], cwd=gl.DIR, check=True)
            subprocess.run(["git", "commit", "-m", "daily: liveness + deadlines"],
                           cwd=gl.DIR, check=True)
            subprocess.run(["git", "push", "pages", "master"], cwd=gl.DIR, check=True)
        except subprocess.CalledProcessError as e:
            print(f"  Deploy failed: {e}")
    try:
        import json, datetime
        grants = json.load(open(gl.DIR + "/grants.json"))
        today = datetime.date.today()
        closing, dead = [], []
        for g in grants:
            dd = g.get("deadlineDate")
            if g.get("deadlineStatus") == "open" and dd:
                try:
                    days = (datetime.date.fromisoformat(dd) - today).days
                    if 0 <= days <= 7:
                        closing.append((days, g["name"]))
                except ValueError:
                    pass
            if g.get("deadlineStatus") == "expired" and g.get("last_checked") == str(today):
                dead.append(g["name"])
        print(f"\nCLOSING<=7d ({len(closing)}): " +
              ", ".join(f"{n} ({d}d)" for d, n in sorted(closing)[:10]))
        print(f"NEWLY-DEAD ({len(dead)}): " + ", ".join(dead[:10]))
    except Exception as e:
        print(f"  scout summary failed: {e}")


if __name__ == "__main__":
    main()
