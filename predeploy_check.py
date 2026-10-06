"""Safety gate run before any prod deploy: inspects the built public/ dir."""

import json
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWED_EXT = {".html", ".css", ".js", ".json", ".ics", ".png", ".svg", ".ico"}
BINARY_EXT = {".png", ".ico"}
BAD_EXT = {".env", ".db", ".py", ".sqlite", ".sqlite3", ".log", ".bat"}
SECRETS = ("TELEGRAM_BOT_TOKEN", "SMTP_PASS", "sk-ant-", "BEGIN PRIVATE KEY")
REQUIRED = ("index.html", "app.js", "grants.json")
MOJIBAKE = "â€"  # "â€"
MOJIBAKE_MAX = 5


def _files(root):
    for r, _d, names in os.walk(root):
        for n in names:
            p = os.path.join(r, n)
            yield p, os.path.relpath(p, root).replace(os.sep, "/")


def list_files(root="public"):
    return sorted((rel, os.path.getsize(p)) for p, rel in _files(root))


def check(dir="public"):
    """Return a list of problem strings (empty = safe to deploy)."""
    root = dir if os.path.isabs(dir) else os.path.join(DIR, dir)
    if not os.path.isdir(root):
        return [f"{dir}: directory does not exist"]
    problems = []
    for p, rel in _files(root):
        name = os.path.basename(rel).lower()
        ext = os.path.splitext(name)[1]
        if rel != ".vercel/project.json" and (
                ext not in ALLOWED_EXT or name == ".env" or name.startswith(".env.")
                or ext in BAD_EXT):
            problems.append(f"{rel}: file type not allowed")
            continue
        if ext in BINARY_EXT:
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            problems.append(f"{rel}: unreadable ({e})")
            continue
        for s in SECRETS:
            if s in text:
                problems.append(f"{rel}: contains secret-looking text {s!r}")
    for r in REQUIRED:
        if not os.path.isfile(os.path.join(root, r)):
            problems.append(f"missing required file {r}")
    gp = os.path.join(root, "grants.json")
    if os.path.isfile(gp):
        try:
            with open(gp, encoding="utf-8") as f:
                rows = json.load(f)
        except (ValueError, OSError) as e:
            problems.append(f"grants.json: not valid JSON ({e})")
        else:
            if not isinstance(rows, list) or not rows:
                problems.append("grants.json: must be a non-empty JSON list")
            else:
                bad = [i for i, r in enumerate(rows)
                       if not isinstance(r, dict) or not r.get("name") or not r.get("url")]
                if bad:
                    problems.append(
                        f"grants.json: {len(bad)} row(s) missing name or url (first: #{bad[0]})")
                moj = sum(MOJIBAKE in json.dumps(r, ensure_ascii=False) for r in rows)
                if moj > MOJIBAKE_MAX:
                    problems.append(f"grants.json: {moj} rows with mojibake (>{MOJIBAKE_MAX})")
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    d = argv[0] if argv else "public"
    root = d if os.path.isabs(d) else os.path.join(DIR, d)
    if os.path.isdir(root):
        files = list_files(root)
        for rel, size in files:
            print(f"  {size:>9}  {rel}")
        print(f"  {len(files)} files, {sum(s for _, s in files)} bytes total")
    problems = check(d)
    for p in problems:
        print("PROBLEM:", p)
    print("FAILED" if problems else "OK: safe to deploy")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
