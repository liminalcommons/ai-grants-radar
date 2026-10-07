#!/usr/bin/env python3
"""seed-worker.py — push the fresh grants.json into the worker's D1 (remote).

Runs after the Pages deploy so the worker and the fallback copy never drift:
  1. node seed-classic.mjs regenerates chunk SQL from grants.json
  2. each chunk applies via `wrangler d1 execute DB --remote`
  3. the row count must equal the export count, else exit 1

Best-effort (weekly.py never aborts on it), but loud on failure.
Needs wrangler logged in with D1 write on grant-radar.
"""

import glob
import json
import os
import shutil
import subprocess
import sys

AI_GRANTS = os.path.dirname(os.path.abspath(__file__))
WORKER = "C:/flur_workspace/radar/packages/worker"
CHUNKS = os.path.join(os.path.dirname(WORKER), ".wrangler", "seed-classic", "chunk-*.sql")


def run(argv, **kw):
    if sys.platform == "win32":
        quoted = " ".join(f'"{a}"' if " " in a else a for a in argv)
        return subprocess.run(quoted, cwd=WORKER, capture_output=True, text=True, shell=True, **kw)
    return subprocess.run(argv, cwd=WORKER, capture_output=True, text=True, **kw)


def main():
    with open(os.path.join(AI_GRANTS, "grants.json"), encoding="utf-8") as f:
        export_count = len(json.load(f))
    node = shutil.which("node")
    if not node:
        print("seed-worker: node not on PATH")
        return 1
    gen = run([node, "scripts/seed-classic.mjs"])
    if gen.returncode != 0:
        print(f"seed-worker: generator failed:\n{gen.stderr[-2000:]}")
        return 1
    print(f"seed-worker: export has {export_count} grants")
    files = sorted(glob.glob(CHUNKS))
    if not files:
        print("seed-worker: no chunk files generated")
        return 1
    for path in files:
        r = run(["npx", "wrangler", "d1", "execute", "DB", "--remote", f"--file={path}"])
        if r.returncode != 0 or "error" in (r.stderr or "").lower():
            print(f"seed-worker: chunk failed: {os.path.basename(path)}\n{(r.stderr or r.stdout)[-2000:]}")
            return 1
    check = run(["npx", "wrangler", "d1", "execute", "DB", "--remote", "--json",
                 "--command", "SELECT COUNT(*) AS n FROM v1_grants"])
    try:
        n = json.loads(check.stdout)[0]["results"][0]["n"]
    except (ValueError, KeyError, IndexError, TypeError):
        print(f"seed-worker: count query failed:\n{(check.stderr or check.stdout)[-1000:]}")
        return 1
    print(f"seed-worker: worker D1 holds {n} classic grants")
    if n != export_count:
        print(f"seed-worker: COUNT MISMATCH (d1={n}, export={export_count})")
        return 1
    print("seed-worker: in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
