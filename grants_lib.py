#!/usr/bin/env python3
"""
grants_lib.py — shared logic for the AI Funding Radar grant database.

Used by:
  - research-grants.py  (autonomous discovery via headless Claude + web search)
  - update-grants.py     (manual merge of a JSON file / object)

Responsibilities:
  - load / save grants.json as proper UTF-8 (ensure_ascii=False)
  - dedup-merge new grants by id and case-insensitive name
  - repair UTF-8-as-CP1252 mojibake (e.g. em dash shown as "â€"")
  - normalise records to the schema index.html expects
  - deploy the static site to Vercel (the dir is gitignored on purpose, so
    we redeploy via the Vercel CLI rather than git-push auto-deploy)
"""

import json
import os
import re
import subprocess
import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
GRANTS_FILE = os.path.join(DIR, "grants.json")
TODAY = datetime.date.today().isoformat()


def _load_dotenv():
    """Load ai-grants/.env into os.environ (KEY=VALUE lines). Keeps secrets
    (Telegram token, SMTP password) out of chat and out of git — the whole dir
    is gitignored. Existing env vars win, so a real cron env can override."""
    path = os.path.join(DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip("'\""))


_load_dotenv()

# Fields index.html reads. category ∈ {Corporate, Foundation, Government, Accelerator}.
# viability ∈ {yes, partial, no}. relevant2026 ∈ {True, False, "upcoming"}.
SCHEMA_DEFAULTS = {
    "organization": "",
    "category": "Corporate",
    "amount": "",
    "deadline": "Rolling",
    "deadlineDate": None,
    "deadlineStatus": "unknown",   # open | rolling | upcoming | expired | unknown (derived)
    "deadlineType": "unknown",     # fixed | rolling | recurring | unknown (derived)
    "eligibility": "",
    "description": "",
    "url": "",
    "tags": [],
    "viability": "partial",
    "viabilityNote": "",
    "relevant2026": True,
    "relevant2026Note": "",
    "audience": ["team"],   # subset of {team, creator, org}
    "fundingType": "cash",  # cash | credits | equity | mixed  (cash is the priority)
    "effort": "medium",     # low | medium | high  (application burden — low effort is preferred)
    "domain": "Startup / General",  # broad field/category (see DOMAINS)
}

DOMAINS = ["AI", "Web3 / Public Goods", "Open Source", "Climate", "Creative",
           "Research", "Civic / Social", "Startup / General"]

# Priority order for display/ranking: real money first, credits last.
FUNDING_RANK = {"cash": 0, "mixed": 1, "equity": 2, "credits": 3}


def classify_domain(grant):
    """Bucket a grant into a broad field for the category filter."""
    text = " ".join([
        str(grant.get("name", "")), str(grant.get("organization", "")),
        str(grant.get("description", "")), " ".join(grant.get("tags", []) or []),
    ]).lower()
    has = lambda *ws: any(w in text for w in ws)
    if has("gitcoin", "giveth", "retropgf", "retro pgf", "quadratic", "protocol guild",
           "onchain", "on-chain", "web3", "crypto", "ethereum", "dao", "blockchain", "public goods"):
        return "Web3 / Public Goods"
    if has("climate", "carbon", "clean energy", "sustainab", "decarbon", "biodiversity", "renewable"):
        return "Climate"
    if has("artist", "music", "film", "creative", "residency", "culture", "gallery", "art "):
        return "Creative"
    if has("open source", "open-source", " oss", "maintainer", "foss"):
        return "Open Source"
    if has("artificial intelligence", "machine learning", "llm", "genai", "generative",
           "ai ", "ai-", "ai/", " ai", "alignment", "inference"):
        return "AI"
    if has("nonprofit", "civic", "community", "social impact", "democracy", "humanitarian", "for good", "for nonprofits"):
        return "Civic / Social"
    if has("research", "fellowship", "phd", "scholar", "scientific", "laboratory"):
        return "Research"
    return "Startup / General"


def classify_effort(grant):
    """Estimate application burden: low | medium | high. Low effort is preferred
    (one of the user's two apply criteria, alongside cash size)."""
    text = " ".join([
        str(grant.get("amount", "")), str(grant.get("eligibility", "")),
        str(grant.get("viabilityNote", "")), str(grant.get("deadline", "")),
        " ".join(grant.get("tags", []) or []),
    ]).lower()
    cat = grant.get("category", "")
    ft = grant.get("fundingType", "")
    if cat == "Government" or ft == "equity" or any(w in text for w in (
        "sbir", "consortium", "accelerator", "cohort", "pitch", "interview",
        "phase", "milestone", "matched", "co-funding", "rfp", "proposal",
    )):
        return "high"
    if (not grant.get("deadlineDate")) or any(w in text for w in (
        "rolling", "simple", "easy", "self-serve", "no equity",
        "apply anytime", "quick", "micro",
    )):
        return "low"
    return "medium"


# ---- deadline derivation -------------------------------------------------
# The single most important honesty check: is this opportunity actually OPEN?
# A free-text deadline conflates two very different things — "this window has
# passed" vs "recurring program, next cycle later". We split them apart so a
# live recurring program is never buried as if it were dead, and a genuinely
# expired one-shot is never shown as if you could still apply.

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# "always open" — no deadline to miss.
_ROLLING_RE = re.compile(
    r"\b(rolling|ongoing|anytime|continuous|year[\s-]?round|always open|no deadline)\b", re.I)
# recurring program whose NEXT window isn't a firm date yet — watch / prepare,
# don't treat as expired even if the last window's date has passed.
_RECUR_RE = re.compile(
    r"(next (cohort|cycle|round|competition|call|window|intake|batch|cohorts)"
    r"|reopen|re-open|expected|upcoming|watch |applications? open|opens? "
    r"|later this year|later 20\d\d|late 20\d\d|mid[\s-]?20\d\d|early 20\d\d"
    r"|annual|recurring|quarterly|rounds run|periodic|tbd|tba|~"
    r"|q[1-4]\s*20\d\d|(fall|spring|summer|winter)\s+20\d\d)", re.I)


def _all_dates(text):
    """Every calendar date mentioned in a messy deadline string, as date objs.

    Handles "Closes May 17, 2026", "June 20-21, 2026" (takes first day),
    ISO "2026-07-15", and bare "May 2026" (treated as end-of-month).
    """
    out = []
    for m in re.finditer(
            r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:\s*[-–]\s*\d{1,2})?,?\s+(\d{4})", text):
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            try:
                out.append(datetime.date(int(m.group(3)), mon, int(m.group(2))))
            except ValueError:
                pass
    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", text):
        try:
            out.append(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+(\d{4})\b", text):
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon and not any(d.year == int(m.group(2)) and d.month == mon for d in out):
            try:
                out.append(datetime.date(int(m.group(2)), mon, 28))
            except ValueError:
                pass
    return out


def derive_deadline(grant, today=None):
    """Classify a grant's deadline into a status the UI can trust.

    Returns {deadlineStatus, deadlineType, deadlineDate}:
      open     — a fixed date in the future; you can apply now/soon (deadlineDate set)
      rolling  — always open, no deadline (deadlineDate None)
      upcoming — recurring program, next window announced but not firmly dated;
                 watch/prepare — NOT expired (deadlineDate None)
      expired  — a fixed date has passed and no next window is announced
                 (deadlineDate = the passed date, for reference)
      unknown  — nothing parseable; check the program page (deadlineDate None)
    """
    today = today or datetime.date.today()
    text = (grant.get("deadline") or "").strip()
    raw = " ".join(str(grant.get(k, "")) for k in ("deadline", "deadlineDate"))
    dates = _all_dates(raw)
    future = sorted(d for d in dates if d >= today)
    past = sorted((d for d in dates if d < today), reverse=True)
    rolling = bool(_ROLLING_RE.search(text))
    recurring = bool(_RECUR_RE.search(text))

    if future:
        # a concrete upcoming date wins — that's the actionable deadline
        return {"deadlineStatus": "open", "deadlineType": "fixed",
                "deadlineDate": future[0].isoformat()}
    if rolling:
        return {"deadlineStatus": "rolling", "deadlineType": "rolling", "deadlineDate": None}
    if recurring:
        # last window may have passed, but the program lives on — don't bury it
        return {"deadlineStatus": "upcoming", "deadlineType": "recurring", "deadlineDate": None}
    if past:
        return {"deadlineStatus": "expired", "deadlineType": "fixed",
                "deadlineDate": past[0].isoformat()}
    return {"deadlineStatus": "unknown", "deadlineType": "unknown", "deadlineDate": None}


def classify_funding_type(grant):
    """Heuristically label a grant cash / credits / equity / mixed from its
    amount + tags. Cash (real money) is what we prioritize; credits come later."""
    text = " ".join([
        str(grant.get("amount", "")),
        " ".join(grant.get("tags", []) or []),
    ]).lower()
    has_credits = any(w in text for w in ("credit", "compute", "cloud", "gpu", "azure", "tpu"))
    has_equity = any(w in text for w in ("safe", "equity", "convertible", "stake", "dilut"))
    # explicit real-money words (NOT the bare "$" — credit amounts use "$" too)
    has_cash = any(w in text for w in (
        "cash", "stipend", "fellowship", "prize", "award", "non-dilutive",
        "non dilutive", "monthly", "salary", "honorarium",
    ))
    if has_credits and has_cash:
        return "mixed"
    if has_credits:
        return "credits"
    if has_equity and not has_cash:
        return "equity"
    return "cash"


def fix_mojibake(value):
    """Repair text mangled by a UTF-8 -> CP1252 round-trip (â€", Ã©, Â , …).

    Only touches strings that carry mojibake markers, so clean text is left
    untouched. Applied recursively to dicts/lists.
    """
    if isinstance(value, str):
        if any(marker in value for marker in ("Ã", "â", "Â")):
            try:
                return value.encode("cp1252").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                return value
        return value
    if isinstance(value, list):
        return [fix_mojibake(v) for v in value]
    if isinstance(value, dict):
        return {k: fix_mojibake(v) for k, v in value.items()}
    return value


def load_existing():
    with open(GRANTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save(grants):
    with open(GRANTS_FILE, "w", encoding="utf-8") as f:
        json.dump(grants, f, indent=2, ensure_ascii=False)
        f.write("\n")


def next_id(grants):
    return max((g.get("id", 0) for g in grants), default=0) + 1


def normalise(item):
    """Fill missing schema fields with defaults and repair text."""
    record = dict(SCHEMA_DEFAULTS)
    record.update(item)
    if not item.get("fundingType"):
        record["fundingType"] = classify_funding_type(record)
    if not item.get("effort"):
        record["effort"] = classify_effort(record)
    if not item.get("domain"):
        record["domain"] = classify_domain(record)
    # deadline status is always DERIVED (a projection of deadline/deadlineDate),
    # never authored — recompute every time so the data can't drift stale.
    record.update(derive_deadline(record))
    return fix_mojibake(record)


def merge(existing, new_items):
    """Append new grants, skipping duplicates by id or case-insensitive name.

    Returns the list of names actually added. Mutates `existing`.
    """
    existing_ids = {g.get("id") for g in existing}
    existing_names = {g.get("name", "").lower() for g in existing}
    added = []
    for raw in new_items:
        item = normalise(raw)
        name = item.get("name", "").strip()
        if not name:
            continue
        if name.lower() in existing_names:
            print(f"  SKIP (duplicate name): {name}")
            continue
        if "id" not in item or item["id"] in existing_ids:
            item["id"] = next_id(existing)
        item.setdefault("_updated", TODAY)
        existing.append(item)
        existing_ids.add(item["id"])
        existing_names.add(name.lower())
        added.append(name)
    return added


def deploy():
    """Push the static site live via the linked Vercel project (`ai-grants`)."""
    print("  Deploying to Vercel (--prod)...")
    subprocess.run(
        "npx --yes vercel --prod --yes",
        cwd=DIR,
        shell=True,
        check=True,
    )
    print("  Deployed.")
