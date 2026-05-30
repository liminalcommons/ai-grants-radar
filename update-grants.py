#!/usr/bin/env python3
"""
update-grants.py — manually merge new grants into grants.json and redeploy.

Usage:
  python update-grants.py new_grants.json     # merge a JSON file (array or object)
  python update-grants.py '{"name":"...", ...}' # merge a single JSON object
  python update-grants.py new_grants.json --no-deploy

Merge/dedup/deploy logic lives in grants_lib. Deploy is via the Vercel CLI
(the ai-grants/ dir is gitignored on purpose, so git-push auto-deploy is not used).
For autonomous discovery, see research-grants.py.
"""

import json
import subprocess
import sys

import grants_lib as gl


def main():
    args = [a for a in sys.argv[1:] if a != "--no-deploy"]
    no_deploy = "--no-deploy" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(1)

    arg = args[0]
    try:
        new_data = json.loads(arg)
    except json.JSONDecodeError:
        with open(arg, encoding="utf-8") as f:
            new_data = json.load(f)
    if isinstance(new_data, dict):
        new_data = [new_data]

    existing = gl.load_existing()
    added = gl.merge(existing, new_data)
    if not added:
        print("No new grants to add.")
        sys.exit(0)

    gl.save(existing)
    print(f"Added {len(added)} grants: {', '.join(added)}")
    print(f"Total: {len(existing)} grants in grants.json")

    if no_deploy:
        print("Skipping deploy (--no-deploy).")
        return
    try:
        gl.deploy()
    except subprocess.CalledProcessError as e:
        print(f"  Deploy failed: {e}. Run `npx vercel --prod` manually.")


if __name__ == "__main__":
    main()
