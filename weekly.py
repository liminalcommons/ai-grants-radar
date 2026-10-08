#!/usr/bin/env python3
"""
weekly.py — the full weekly pipeline, one entry point for the scheduler/routine.

Steps:
  1. research-grants.py  — find new grants for all audiences (team/creator/org)
  2. refresh.py          — scrape grant pages, extract requirements, refresh deadlines
                           (capped: 150 pages / 25 LLM extractions per run, most overdue
                           first, so the initial backlog drains over several weeks)
  2b. verify-deadlines.py — re-derive every deadline status against today
                           (offline, no LLM calls)
  3. generate-report.py  — render the earthy HTML weekly report (report.html)
  4. deploy              — publish grants.json + report.html to GitHub Pages
  4b. seed-worker.py      — push grants.json into the worker D1 (remote), so the
                           radar.liminalcommons.com wall never drifts from Pages
  5. notify.py           — post to Telegram group + email the report

Each step is best-effort and logged; a failure in one does not abort the rest
(e.g. no new grants still produces + delivers a "nothing new this week" report).

Usage:
  python weekly.py               # full pipeline
  python weekly.py --no-deploy   # skip the Vercel deploy step
  python weekly.py --no-notify   # skip Telegram/email
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
    no_notify = "--no-notify" in sys.argv

    # 1. research (saves grants.json; we deploy explicitly in step 3)
    step("Research", ["research-grants.py", "--no-deploy"])

    # 2. refresh: re-verify new/changed/stale pages, re-derive deadlines, export grants.json
    step("Refresh", ["refresh.py", "--limit", "150", "--max-extract", "25"])

    # 2b. verify: re-derive every deadline status against today (offline, no
    # LLM) so the report and site never show a stale opportunity as open.
    step("VerifyDeadlines", ["verify-deadlines.py"])

    # 2c. audit: liveness-check every funder page (no engine), stamp
    # last_checked/check_ok, flag dead + blocked ids into changed.json.
    step("CheckGrants", ["check_grants.py"])

    # 3. report
    step("Report", ["generate-report.py"])

    # 4. deploy: commit, then push to the `pages` remote → GitHub Pages publishes
    #    https://liminalcommons.github.io/ai-grants-radar/ (free, no billing).
    #    Commit before pull so a rebase conflict can abort cleanly without leaving
    #    conflict markers in a committed file.
    if not no_deploy:
        print("\n=== Deploy (GitHub Pages) ===")
        try:
            subprocess.run(["git", "add", "-A"], cwd=gl.DIR, check=True)
            subprocess.run(["git", "commit", "-m", "weekly: new grants + report"], cwd=gl.DIR)
            rebase = subprocess.run(["git", "pull", "--rebase", "pages", "master"], cwd=gl.DIR)
            if rebase.returncode != 0:
                print("  rebase conflicted — aborting; resolve manually.")
                subprocess.run(["git", "rebase", "--abort"], cwd=gl.DIR, check=False)
            else:
                subprocess.run(["git", "push", "pages", "master"], cwd=gl.DIR, check=True)
                print("  Pushed → GitHub Pages publishes in ~1 min.")
        except subprocess.CalledProcessError as e:
            print(f"  git push failed: {e}")

    # 4b. worker re-seed: push the fresh export into the remote D1 (best
    # effort; the wall must never drift from the fallback copy).
    step("SeedWorker", ["seed-worker.py"])

    # 5. notify
    if not no_notify:
        step("Notify", ["notify.py"])

    print("\nWeekly pipeline complete.")


if __name__ == "__main__":
    main()
