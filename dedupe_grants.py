#!/usr/bin/env python3
"""dedupe_grants.py — collapse duplicate grants in grants.json by normalized URL.

Two grants are the same when their URLs match after normalization: lowercase
scheme+host, default ports dropped, trailing slash trimmed (except root),
tracking params (utm_*, fbclid, gclid, msclkid, mc_*) removed, remaining query
sorted. Within a group the keeper is the row with the most evidence, by:
  1. has a real deadlineDate (not empty/unknown)
  2. longer description
  3. more non-empty fields
  4. lowest id (stable, deterministic)

Usage:
  python dedupe_grants.py              # dry run: report only, no writes
  python dedupe_grants.py --write      # apply to grants.json (backup first)

Exit 0 always on success; prints a short report either way.
"""

import copy
import json
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "msclkid", "mc_", "_hs", "vero_")
TRACKING_EXACT = {"fbclid", "gclid", "msclkid", "ref", "ref_src", "source", "utm"}

NAME_ALIASES = {
    "programme": "program",
    "programmes": "program",
    "programs": "program",
    "fellowship": "fellow",
    "fellowships": "fellow",
    "grants": "grant",
}

NAME_STOPWORDS = {"a", "an", "the", "of", "for", "and", "to", "in", "on"}

#: Minimum name-token Jaccard similarity, kept for reporting only. Merging
#: uses the stricter subset rule below: shared funder words ("Arbitrum …")
#: inflate Jaccard and would fuse distinct programs on one hub page.
NAME_JACCARD_THRESHOLD = 0.5


def same_grant(a, b):
    """Two names on one URL are the same grant only when one token set
    contains the other ("The Freed Fellowship Grant" vs "Freed Fellowship
    Grant"; "Rapid Response Grants" vs "Meyer Foundation — Rapid Response
    Grants"). Distinct programs sharing a hub URL never satisfy this."""
    ta, tb = name_tokens(a), name_tokens(b)
    return bool(ta and tb) and (ta <= tb or tb <= ta)

FILLED = (
    "name",
    "organization",
    "amount",
    "deadline",
    "deadlineDate",
    "description",
    "eligibility",
    "domain",
    "effort",
    "tags",
)


def normalize_url(url):
    """Canonical form of a grant URL for duplicate detection."""
    if not url:
        return ""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.lower()
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = host + (f":{port}" if port else "")
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (
            k.lower() in TRACKING_EXACT
            or k.lower().startswith(TRACKING_PREFIXES)
        )
    ]
    query.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def filled_count(row):
    return sum(1 for k in FILLED if row.get(k))


def keeper_key(row):
    """Higher sorts first: deadlineDate, description length, filled fields, then lowest id."""
    has_deadline = 1 if (row.get("deadlineDate") or "").strip() else 0
    desc_len = len(row.get("description") or "")
    try:
        tiebreak = -int(str(row.get("id", "0")).lstrip("g") or 0)
    except ValueError:
        tiebreak = 0
    return (has_deadline, desc_len, filled_count(row), tiebreak)


def name_tokens(name):
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return {NAME_ALIASES.get(w, w) for w in words if len(w) > 1} - NAME_STOPWORDS


def name_jaccard(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def dedupe(rows):
    """Return (kept, dropped) where dropped maps kept_id -> [dropped ids].

    Rows group by normalized URL; within a group, a row merges into a kept
    row only when one name contains the other's tokens. Distinct programs
    that share a funder hub URL are all kept.
    """
    groups = {}
    order = []
    for row in rows:
        key = normalize_url(row.get("url", "")) or f"\0id:{row.get('id')}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    kept = []
    dropped = {}
    for key in order:
        group = groups[key]
        if len(group) == 1:
            kept.append(group[0])
            continue
        # Cluster by name containment: a row merges into the best-scoring
        # kept row whose tokens contain (or are contained in) its own,
        # otherwise it starts its own cluster.
        clusters = []  # list of (keeper_row, [merged rows])
        for row in sorted(group, key=keeper_key, reverse=True):
            placed = False
            for keeper, members in clusters:
                if same_grant(keeper.get("name"), row.get("name")):
                    members.append(row)
                    placed = True
                    break
            if not placed:
                clusters.append((row, []))
        for keeper, members in clusters:
            kept.append(keeper)
            if members:
                dropped[keeper.get("id")] = [r.get("id") for r in members]
    return kept, dropped


def main():
    write = "--write" in sys.argv
    with open("grants.json", encoding="utf-8") as f:
        rows = json.load(f)
    before = len(rows)
    kept, dropped = dedupe(copy.deepcopy(rows))
    n_dropped = before - len(kept)
    print(f"rows: {before} -> {len(kept)} (dropped {n_dropped})")
    print(f"duplicate groups: {len(dropped)}")
    for keep_id, ids in sorted(dropped.items(), key=lambda kv: str(kv[0])):
        print(f"  keep {keep_id}: drop {', '.join(str(i) for i in ids)}")
    if not write:
        print("dry run — pass --write to apply")
        return
    with open("grants.pre-dedupe.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    with open("grants.json", "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=1)
    print("wrote grants.json (backup: grants.pre-dedupe.json)")


if __name__ == "__main__":
    main()
