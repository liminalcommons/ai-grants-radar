#!/usr/bin/env python3
"""
trial_extract.py — requirements-extractor trial on a handful of grants.

READ-ONLY: fetches each grant's program page, runs extract_requirements with
the DeepSeek LLM adapter, and reports fields-kept vs review-queued
(grounding keep-rate). Never writes grants.json — expansion (applying
kept fields) is a separate, reviewed step.

Every DeepSeek call lands in spend-ledger.csv via llm_deepseek.

Usage:
  python trial_extract.py                # default 5 trial grants
  python trial_extract.py --ids 3,132,528
"""

import argparse
import datetime
import html
import re
import sys
import urllib.request

import extract_requirements as er
import grants_lib as gl
import llm_deepseek as ds

TRIAL_IDS = [3, 132, 528, 116, 29]
MAX_CHARS = 12000
FETCH_TIMEOUT = 20


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "grants-bot/1.0"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style|nav|footer)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:MAX_CHARS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=",".join(map(str, TRIAL_IDS)))
    ap.add_argument("--max-tokens", type=int, default=4000)
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip()]
    grants = {g["id"]: g for g in gl.load_existing()}
    today = datetime.date.today()
    llm = ds.make_llm("trial-extract", session_id=f"trial-{today.isoformat()}",
                      max_tokens=args.max_tokens)

    kept_fields, review_rows, calls, fetched = 0, 0, 0, 0
    for gid in ids:
        g = grants.get(gid)
        if not g:
            print(f"#{gid}: not in grants.json — skipped")
            continue
        try:
            text = fetch_text(g["url"])
            fetched += 1
        except Exception as e:  # noqa: BLE001 — trial reports, doesn't stop
            print(f"#{gid} {g['name'][:50]} — FETCH FAILED: {type(e).__name__}")
            continue
        if len(text) < 200:
            print(f"#{gid} {g['name'][:50]} — page too thin ({len(text)} chars) — skipped")
            continue
        try:
            r = er.extract(g, text, today, llm)
            calls += 1
        except RuntimeError as e:
            print(f"#{gid} {g['name'][:50]} — LLM FAILED: {e}")
            continue
        if (any(i.get("field") == "*" and
               str(i.get("reason", "")).startswith("LLM extraction failed")
               for i in r["review_items"]) and len(text) > 4000):
            # Truncation recovery: long pages can push the reply past
            # max_tokens. One retry on the first half (key facts — who can
            # apply, amounts, dates — sit near the top of program pages).
            short = text[:len(text) // 2]
            try:
                r2 = er.extract(g, short, today, llm)
                calls += 1
            except RuntimeError as e:
                print(f"#{gid} {g['name'][:50]} — RETRY LLM FAILED: {e}")
            else:
                if not any(i.get("field") == "*" for i in r2["review_items"]):
                    r = r2
                    print(f"#{gid} {g['name'][:50]} — retry on "
                          f"{len(short)} chars recovered")
        nfields = len(r["fields"]) + len((r["fields"].get("eligibility") or {}))
        kept_fields += nfields
        review_rows += len(r["review_items"])
        print(f"#{gid} {g['name'][:50]} — {len(text)} chars, "
              f"fields kept {nfields}, review {len(r['review_items'])}")
        for item in r["review_items"][:4]:
            print(f"    review: {item['field']} — {item['reason']}")
    total = kept_fields + review_rows
    rate = round(100.0 * kept_fields / total, 1) if total else 0.0
    print(f"\ntrial: {fetched} fetched, {calls} DeepSeek calls, "
          f"kept {kept_fields} / review {review_rows} — keep-rate {rate}%")
    print("spend rows in spend-ledger.csv with tag trial-extract/*")


if __name__ == "__main__":
    sys.exit(main())
