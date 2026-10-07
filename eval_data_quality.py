#!/usr/bin/env python3
"""
eval_data_quality.py — deterministic measuring stick for v1 grants.json.

No LLM, no network. Five checks over every record:

  schema               required fields present and non-empty
  deadline_consistency stored status/type/date agree with a fresh
                       grants_lib.derive_deadline projection; no stale-open
                       (open + past deadlineDate), no future-expired
  url_health           http(s) URL, no placeholder domain, not empty
  dedupe               same URL + same normalised name = FAIL (true dupe);
                       same URL + different name = WARN (hub variants)
  content_quality      eligibility/description meet min length, no TODO/lorem
                       boilerplate, amount present

Unknown deadline status/type is reported as INFO (a backfill opportunity,
not a failure) — the requirements-extractor trials exist to shrink it.

Usage:
  python eval_data_quality.py                # text report, exit 1 on FAIL
  python eval_data_quality.py --json out.json
"""

import argparse
import datetime
import json
import re
import sys
from collections import Counter
from urllib.parse import urlparse

import grants_lib as gl

REQUIRED_FIELDS = ["id", "name", "organization", "category", "amount",
                   "deadline", "eligibility", "description", "url",
                   "viability", "audience", "fundingType", "effort", "domain"]
MIN_ELIGIBILITY_LEN = 8
MIN_DESCRIPTION_LEN = 40
PLACEHOLDER_HOSTS = {"example.com", "example.org", "placeholder.com",
                     "yoursite.com", "todo.com"}
BOILERPLATE_RE = re.compile(r"\b(lorem ipsum|todo|tbd|xxx+|asdf)\b", re.I)
FAIL_LIST_CAP = 20


def norm_name(name):
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def norm_url(url):
    u = str(url or "").strip().rstrip("/")
    try:
        p = urlparse(u)
        if not p.scheme.startswith("http"):
            return ""
        host = p.netloc.lower()
        path = p.path.rstrip("/") or ""
        return f"{p.scheme.lower()}://{host}{path}"
    except ValueError:
        return ""


def evaluate(grants, today=None):
    """Return {score, checks: {name: {passed, failed, warned, issues}}, totals}."""
    today = today or datetime.date.today()
    issues = []  # (check, level, grant_id, name, detail)

    def add(check, level, g, detail):
        issues.append({"check": check, "level": level,
                       "id": g.get("id"), "name": (g.get("name") or "")[:60],
                       "detail": detail})

    schema_ok = 0
    for g in grants:
        missing = [f for f in REQUIRED_FIELDS if not g.get(f)]
        if missing:
            add("schema", "FAIL", g, f"missing/empty: {', '.join(missing)}")
        else:
            schema_ok += 1

    dl_ok = 0
    for g in grants:
        want = gl.derive_deadline(g, today)
        got = {k: g.get(k) for k in ("deadlineStatus", "deadlineType", "deadlineDate")}
        if got != want:
            add("deadline_consistency", "FAIL", g,
                f"stored {got['deadlineStatus']}/{got['deadlineType']}/"
                f"{got['deadlineDate']} != derived "
                f"{want['deadlineStatus']}/{want['deadlineType']}/{want['deadlineDate']}")
            continue
        dl_ok += 1
        dd = g.get("deadlineDate")
        if dd and g.get("deadlineStatus") == "expired" and dd >= today.isoformat():
            add("deadline_consistency", "WARN", g,
                f"expired but deadlineDate {dd} is in the future")
        if g.get("deadlineStatus") in ("unknown",):
            add("deadline_consistency", "INFO", g, "unknown status — backfill candidate")

    url_ok = 0
    seen = {}
    for g in grants:
        u = norm_url(g.get("url"))
        if not u:
            add("url_health", "FAIL", g, f"bad URL: {g.get('url')!r}")
            continue
        if urlparse(u).netloc in PLACEHOLDER_HOSTS:
            add("url_health", "FAIL", g, f"placeholder host in URL: {u}")
            continue
        url_ok += 1
        seen.setdefault(u, []).append(g)

    dedupe_fail = dedupe_warn = 0
    for u, group in seen.items():
        if len(group) < 2:
            continue
        names = {norm_name(g.get("name")) for g in group}
        if len(names) == 1:
            dedupe_fail += 1
            for g in group:
                add("dedupe", "FAIL", g, f"true dupe: {len(group)}x same URL+name {u[:70]}")
        else:
            dedupe_warn += 1
            ids = ",".join(str(g.get("id")) for g in group)
            add("dedupe", "WARN", group[0],
                f"hub variants: {len(group)}x same URL, ids {ids} {u[:70]}")

    content_ok = 0
    for g in grants:
        bad = []
        if len(str(g.get("eligibility") or "")) < MIN_ELIGIBILITY_LEN:
            bad.append("eligibility too short")
        if len(str(g.get("description") or "")) < MIN_DESCRIPTION_LEN:
            bad.append("description too short")
        blob = f"{g.get('eligibility','')} {g.get('description','')} {g.get('name','')}"
        if BOILERPLATE_RE.search(blob):
            bad.append("boilerplate marker")
        if bad:
            add("content_quality", "FAIL", g, "; ".join(bad))
        else:
            content_ok += 1

    n = len(grants)
    fails = sum(1 for i in issues if i["level"] == "FAIL")

    def pct(x):
        return round(100.0 * x / n, 1) if n else 0.0

    checks = {
        "schema": {"passed": schema_ok, "rate": pct(schema_ok)},
        "deadline_consistency": {"passed": dl_ok, "rate": pct(dl_ok)},
        "url_health": {"passed": url_ok, "rate": pct(url_ok)},
        "dedupe": {"passed": n - sum(1 for i in issues
                                     if i["check"] == "dedupe"
                                     and i["level"] == "FAIL"),
                   "true_dupe_groups": dedupe_fail, "hub_variant_groups": dedupe_warn,
                   "rate": round(100.0 * (n - sum(1 for i in issues
                                                 if i["check"] == "dedupe"
                                                 and i["level"] == "FAIL")) / n, 1) if n else 0.0},
        "content_quality": {"passed": content_ok, "rate": pct(content_ok)},
    }
    score = round(sum(c["rate"] for c in checks.values()) / len(checks), 1) if n else 0.0
    levels = Counter(i["level"] for i in issues)
    return {"score": score, "grants": n, "date": today.isoformat(),
            "checks": checks,
            "totals": {"FAIL": levels.get("FAIL", 0), "WARN": levels.get("WARN", 0),
                       "INFO": levels.get("INFO", 0)},
            "issues": issues}


def report(result, out=sys.stdout):
    r = result
    p = lambda s: print(s, file=out)
    p(f"data-quality eval — {r['grants']} grants @ {r['date']} — SCORE {r['score']}")
    for name, c in r["checks"].items():
        extra = ""
        if name == "dedupe":
            extra = (f" (true dupes: {c['true_dupe_groups']}, "
                     f"hub variants: {c['hub_variant_groups']})")
        passed = c.get("passed", "?")
        p(f"  {name:<22} {c['rate']:>5}%  passed {passed}{extra}")
    t = r["totals"]
    p(f"issues: {t['FAIL']} FAIL / {t['WARN']} WARN / {t['INFO']} INFO")
    shown = 0
    for i in r["issues"]:
        if i["level"] != "FAIL" or shown >= FAIL_LIST_CAP:
            continue
        p(f"  FAIL [{i['check']}] #{i['id']} {i['name']} — {i['detail']}")
        shown += 1
    rest = t["FAIL"] - shown
    if rest:
        p(f"  ... +{rest} more FAIL (see --json)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="write full result JSON here")
    ap.add_argument("--lenient", action="store_true",
                    help="exit 0 even with FAILs (measuring stick mode)")
    args = ap.parse_args()
    grants = gl.load_existing()
    result = evaluate(grants)
    report(result)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"wrote {args.json}")
    return 0 if (args.lenient or result["totals"]["FAIL"] == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
