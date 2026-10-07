#!/usr/bin/env python3
"""
refresh.py - re-verify grant pages and keep the DB (and grants.json export) current.

Flow: load data/grants.db -> choose grants to refresh -> fetch pages ->
(if the page is new or its content hash changed) extract requirements ->
upsert -> re-derive deadlineStatus against today -> export grants.json.

A grant is refreshed when it is new (candidate or explicitly named), its page
was never fetched, page.lastChecked is older than STALE_DAYS, or its deadline
is within SOON_DAYS. Unchanged pages are NOT re-extracted.

Discovery finds (research-grants.py) arrive as `candidates`: they are scraped
first and only land in the DB if the page is not dead.

Budget: at most --max-extract (default 25) pages are extracted per run. Changed
pages beyond that are deferred: their old contentHash/lastChecked are kept so they
are picked up again next run. The first runs after DB import therefore drain the
~1400-page backlog over several weeks, most overdue first (weekly.py also caps --limit).

Usage:
  python refresh.py                  # refresh everything that is due
  python refresh.py --limit 50       # at most 50 grants
  python refresh.py --ids 12,40      # exactly these grants
  python refresh.py --dry-run        # fetch + report, write nothing
  python refresh.py --max-extract 10 # cap LLM extractions this run
  python refresh.py --no-extract     # fetch and link-health only
"""

import argparse
import datetime
import os

import extract_requirements as er
import grants_db as gdb
import grants_lib as gl
import llm_deepseek as ds
from scrape import content_hash, fetch_many, html_to_text

STALE_DAYS = 14
DEFAULT_MAX_EXTRACT = 25   # LLM calls per run; the rest wait for the next run
SOON_DAYS = 30


def _date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def is_due(grant, today):
    """Why this grant needs a refresh, or None."""
    page = grant.get("page") or {}
    last = _date(page.get("lastChecked"))
    if last is None:
        return "never fetched"
    if (today - last).days > STALE_DAYS:
        return "stale"
    dl = _date(grant.get("deadlineDate"))
    if dl is not None and 0 <= (dl - today).days <= SOON_DAYS:
        return "deadline soon"
    return None


def choose(grants, today, ids=None, limit=None):
    """Grants to refresh, most overdue first (never-fetched, then oldest check)."""
    if ids:
        want = set(ids)
        picked = [g for g in grants if g.get("id") in want and g.get("url")]
    else:
        picked = [g for g in grants if g.get("url") and is_due(g, today)]
    picked.sort(key=lambda g: ((g.get("page") or {}).get("lastChecked") or "", g.get("id") or 0))
    return picked[:limit] if limit else picked


def prepare_candidates(conn, finds, today):
    """Normalise discovery finds; drop nameless/URL-less ones and ones already in the DB."""
    out, seen = [], set()
    for raw in finds:
        rec = gl.normalise(raw)
        rec.setdefault("_updated", today.isoformat())
        if not (rec.get("name") or "").strip() or not rec.get("url"):
            continue
        rec.pop("id", None)
        keys = gdb.keys_for(rec)
        if keys in seen or gdb._find(conn, *keys) is not None:
            print(f"  SKIP (already known): {rec['name']}")
            continue
        seen.add(keys)
        out.append(rec)
    return out


def rederive(conn, today, dry_run=False):
    """Recompute deadlineStatus/Type/Date for every row. Returns names newly expired."""
    expired = []
    for rec in gdb.export_records(conn):
        d = gl.derive_deadline(rec, today)
        if all(rec.get(k) == v for k, v in d.items()):
            continue
        if d["deadlineStatus"] == "expired" and rec.get("deadlineStatus") != "expired":
            expired.append(rec.get("name"))
        if not dry_run:
            conn.execute("UPDATE grants SET deadlineStatus=?, deadlineType=?, deadlineDate=? "
                         "WHERE id=?", (d["deadlineStatus"], d["deadlineType"],
                                        d["deadlineDate"], rec["id"]))
    if not dry_run:
        conn.commit()
    return expired


def run(conn, today=None, ids=None, limit=None, dry_run=False, no_extract=False,
        candidates=(), fetch_fn=fetch_many, llm=None, review_path=er.REVIEW_CSV,
        json_path=gdb.DEFAULT_JSON, export=True, max_extract=DEFAULT_MAX_EXTRACT,
        candidates_only=False):
    today = today or datetime.date.today()
    if llm is None and not no_extract:
        # Default extractor: DeepSeek via OpenCode Go (owner-authorized;
        # every call spend-logged by llm_deepseek, max 25/run via max_extract).
        # extract_requirements keeps its headless `claude -p` fallback only
        # for direct extract() callers that pass llm=None; weekly runs always
        # arrive here with a real DeepSeek llm instead.
        llm = ds.make_llm("refresh-extract",
                          session_id=f"refresh-{today.isoformat()}")
    s = dict.fromkeys(("selected", "fetched", "changed", "unchanged", "dead", "blocked",
                       "extracted", "sent_to_review", "expired", "rejected", "transient",
                       "added", "deferred"), 0)

    grants = [] if candidates_only else choose(gdb.export_records(conn), today, ids, limit)
    # candidates go first so they get the extraction budget before the backlog does
    work = [(c, True) for c in candidates] + [(g, False) for g in grants]
    s["selected"] = len(work)
    results = fetch_fn([g["url"] for g, _ in work]) if work else {}

    for grant, is_new in work:
        r = results.get(grant["url"]) or {"status": "dead", "transient": True}
        if r.get("transient"):
            s["transient"] += 1      # timeout / crash: unknown, leave the row alone
            continue
        status = r["status"]
        if status == "dead":
            s["dead"] += 1
            if is_new:               # a find whose page is gone is not worth storing
                s["rejected"] += 1
                continue
        elif status == "blocked":
            s["blocked"] += 1
        else:
            s["fetched"] += 1

        old_hash = (grant.get("page") or {}).get("contentHash")
        page = {"status": status, "lastChecked": today.isoformat()}
        text = ""
        if status in ("ok", "redirect"):
            text = html_to_text(r.get("html", ""))
            if text:
                page["contentHash"] = content_hash(text)
            elif old_hash:
                page["contentHash"] = old_hash
            if status == "redirect":
                page["finalUrl"] = r.get("final_url")
        elif old_hash:
            page["contentHash"] = old_hash

        changed = bool(text) and page.get("contentHash") != old_hash
        s["changed"] += changed
        s["unchanged"] += status in ("ok", "redirect") and not changed

        deferred = (changed and not no_extract and max_extract is not None
                    and s["extracted"] + s["deferred"] >= max_extract)
        if deferred:
            # Over budget: record link health but keep the old hash AND old lastChecked,
            # so the page still looks changed/due and is extracted next run.
            s["deferred"] += 1
            page.pop("contentHash", None)
            if old_hash:
                page["contentHash"] = old_hash
            last = (grant.get("page") or {}).get("lastChecked")
            if last:
                page["lastChecked"] = last
            else:
                page.pop("lastChecked")

        update = dict(grant, page=page) if is_new else \
            {"name": grant["name"], "url": grant["url"], "page": page}
        if changed and not no_extract and not deferred:
            result = er.extract(grant, text, today, llm=llm)
            fields = dict(result["fields"])
            tl = fields.get("timeline") or {}
            if tl.get("deadlineDate"):
                fields["deadlineDate"] = tl["deadlineDate"]
            update.update(fields)
            s["extracted"] += 1
            s["sent_to_review"] += len(result["review_items"])
            if not dry_run:
                er.write_review(result["review_items"], review_path)

        s["added"] += is_new
        if not dry_run:
            if is_new:
                update.update(gl.derive_deadline(update, today))
            gdb.upsert(conn, update)

    s["expired"] = len(rederive(conn, today, dry_run))
    if export and not dry_run:
        gdb.export_json(json_path, conn)
    return s


def summary_line(s):
    return ("fetched {fetched} / changed {changed} / dead {dead} / blocked {blocked} / "
            "extracted {extracted} / sent-to-review {sent_to_review} / expired {expired} / "
            "deferred {deferred}"
            ).format(**s)


def open_db(db_path=gdb.DEFAULT_DB, json_path=gdb.DEFAULT_JSON):
    """Open the DB and fold in any hand edits made to grants.json since the last export."""
    conn = gdb.connect(db_path)
    if os.path.exists(json_path):
        gdb.import_json(json_path, conn=conn)
    return conn


def main(argv=None):
    ap = argparse.ArgumentParser(description="Refresh grant pages, extraction and deadlines")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-extract", type=int, default=DEFAULT_MAX_EXTRACT,
                    help="cap on LLM extractions per run; extra changed pages are deferred")
    ap.add_argument("--ids", help="comma-separated grant ids")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-extract", action="store_true")
    ap.add_argument("--db", default=gdb.DEFAULT_DB)
    args = ap.parse_args(argv)
    ids = [int(x) for x in args.ids.split(",") if x.strip()] if args.ids else None

    conn = open_db(args.db)
    s = run(conn, ids=ids, limit=args.limit, dry_run=args.dry_run, no_extract=args.no_extract,
            max_extract=args.max_extract)
    print(("[dry-run] " if args.dry_run else "") + summary_line(s))
    return s


if __name__ == "__main__":
    main()
