#!/usr/bin/env python3
"""
weekly.py — the full weekly pipeline, one entry point for the scheduler/routine.

Steps:
  1. research-grants.py  — find new grants for all audiences (team/creator/org)
  2. generate-report.py  — render the earthy HTML weekly report (report.html)
  3. deploy              — publish grants.json + report.html to Vercel
  4. notify.py           — post to Telegram group + email the report

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

    # 2. report
    step("Report", ["generate-report.py"])

    # 3. deploy site + report together
    if not no_deploy:
        print("\n=== Deploy ===")
        try:
            gl.deploy()
        except subprocess.CalledProcessError as e:
            print(f"  Deploy failed: {e}")

    # 4. notify
    if not no_notify:
        step("Notify", ["notify.py"])

    print("\nWeekly pipeline complete.")


if __name__ == "__main__":
    main()
