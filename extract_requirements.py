#!/usr/bin/env python3
"""
extract_requirements.py - turn a scraped grant page into contract fields.

    extract(grant, page_text, today) -> {"fields": {...}, "review_items": [...]}

Stage 1 is deterministic: dates (via grants_lib) and amounts are parsed from
the text. Stage 2 asks an injectable LLM (default: the headless `claude -p`
path from research-grants.py) for eligibility, requirements and timeline as
strict JSON with a verbatim quote and confidence per field.

Grounding guard: a field is only kept if its quote is a verbatim substring of
page_text (whitespace-normalised) and confidence >= MIN_CONFIDENCE. Everything
else becomes a review row in review/extraction-review.csv and is never
written as fact.

CLI:
    python extract_requirements.py --id N --text-file page.txt [--dry-run]
"""

import argparse
import csv
import datetime
import importlib.util
import json
import os
import re
import sys

import grants_lib as gl

MIN_CONFIDENCE = 0.7
REVIEW_CSV = os.path.join(gl.DIR, "review", "extraction-review.csv")
REVIEW_HEADER = ["grant_id", "field", "value", "quote", "reason"]

ENTITY_VALUES = {"none", "org", "ngo", "company", "fiscal-sponsor"}
APPLICANT_TYPES = {"individual", "team", "org"}
GEO_RE = re.compile(r"^(global|country:[A-Z]{2}|region:[a-z][a-z-]*|restricted:[A-Z]{2}(,[A-Z]{2})*)$")
CURRENCIES = {"$": "USD", "€": "EUR", "£": "GBP", "usd": "USD", "eur": "EUR",
              "gbp": "GBP", "cad": "CAD", "aud": "AUD", "chf": "CHF", "inr": "INR"}

PROMPT = """You extract grant facts from the page text below. Reply with ONE JSON object only.
Every value needs a `quote`: an exact, verbatim excerpt copied from the page text that
supports it, and a `confidence` between 0 and 1. If the page does not say, omit the field.
Never infer or guess. Put finer applicant detail (startup, nonprofit, university...) in restrictions.
Keep each `quote` under 200 characters — trim to the shortest excerpt that supports the value.
Reply with the JSON object only: no markdown fences, no commentary, no extra keys.

Schema:
{{
 "eligibility": {{
  "geography": {{"value": "global" | "country:XX" (ISO alpha-2) | "region:<name>" | "restricted:XX,YY" (comma-separated ISO alpha-2 list), "quote": "...", "confidence": 0.0}},
  "entityRequired": {{"value": "none" (individuals can apply, no entity needed) | "org" | "ngo" | "company" | "fiscal-sponsor", "quote": "...", "confidence": 0.0}},
  "applicantTypes": {{"value": a subset of ["individual", "team", "org"], "quote": "...", "confidence": 0.0}},
  "restrictions": [{{"item": "...", "quote": "...", "confidence": 0.0}}]
 }},
 "requirements": [{{"item": "...", "quote": "...", "confidence": 0.0}}],
 "timeline": {{
  "opensDate": {{"value": "YYYY-MM-DD", "quote": "...", "confidence": 0.0}},
  "deadlineDate": {{"value": "YYYY-MM-DD", "quote": "...", "confidence": 0.0}},
  "decisionDate": {{"value": "YYYY-MM-DD", "quote": "...", "confidence": 0.0}},
  "durationMonths": {{"value": 12, "quote": "...", "confidence": 0.0}}
 }}
}}

Grant: {name} ({funder})
PAGE TEXT:
{text}
"""


# ---------------------------------------------------------------- helpers
def norm_ws(s):
    return " ".join(str(s).split())


def grounded(quote, norm_text):
    q = norm_ws(quote or "")
    return bool(q) and q in norm_text


def _as_date(today):
    if isinstance(today, datetime.datetime):
        return today.date()
    if isinstance(today, datetime.date):
        return today
    return datetime.date.fromisoformat(str(today))


def _sentences(text):
    for line in text.splitlines():
        for part in re.split(r"(?<=[.!?])\s+", line):
            part = part.strip()
            if part:
                yield part


# ------------------------------------------------------- stage 1: dates
_DEADLINE_KW = re.compile(r"deadline|due\b|closes?\b|closed|closing|apply by|submit(?:ted)? by|"
                          r"rolling|until", re.I)
_OPENS_KW = re.compile(r"applications? (?:open|opens|opened|will open)|opens?\b|open from|"
                       r"accepting applications from", re.I)
_DECISION_KW = re.compile(r"decisions?|notif(?:y|ied|ication)|announced|awardees|winners", re.I)


def parse_dates(text, today):
    """Deterministic timeline fields. Returns {name: (value, quote, conf)}."""
    out = {}
    for s in _sentences(text):
        is_decision = bool(_DECISION_KW.search(s))
        if "deadlineType" not in out and _DEADLINE_KW.search(s) and not is_decision:
            d = gl.derive_deadline({"deadline": s}, today)
            if d["deadlineType"] != "unknown":
                if d["deadlineDate"]:
                    out["deadlineDate"] = (d["deadlineDate"], s, 0.9)
                out["deadlineType"] = (d["deadlineType"], s, 0.9)
        if "opensDate" not in out and _OPENS_KW.search(s) and not is_decision:
            dates = gl._all_dates(s)
            if dates:
                out["opensDate"] = (dates[0].isoformat(), s, 0.85)
        if "decisionDate" not in out and is_decision:
            dates = gl._all_dates(s)
            if dates:
                out["decisionDate"] = (dates[0].isoformat(), s, 0.85)
    return out


# ----------------------------------------------------- stage 1: amounts
_AMT_RE = re.compile(
    r"(?P<cur>[$€£]|\b(?:USD|EUR|GBP|CAD|AUD|CHF|INR)\b)\s?(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"\s?(?P<mult>k\b|m\b|million\b|thousand\b)?", re.I)
_AMT_CTX = re.compile(r"grant|award|fund|up to|receive|credit|prize|stipend|per |between|range", re.I)


def parse_amounts(text):
    """Return ({amountMin, amountMax, currency}, quote) or (None, None)."""
    vals, curs, quote = [], set(), None
    for s in _sentences(text):
        if not _AMT_CTX.search(s):
            continue
        found = False
        for m in _AMT_RE.finditer(s):
            n = float(m.group("num").replace(",", ""))
            mult = (m.group("mult") or "").lower()
            n *= {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}.get(mult, 1)
            vals.append(int(n))
            curs.add(CURRENCIES[m.group("cur").lower()])
            found = True
        if found and quote is None:
            quote = s
    if not vals or len(curs) != 1:
        return None, None
    lo, hi = min(vals), max(vals)
    single_up_to = len(vals) == 1 and re.search(r"up to|maximum|max\b", quote, re.I)
    return ({"amountMin": None if single_up_to else lo, "amountMax": hi,
             "currency": curs.pop()}, quote)


# ------------------------------------------------------------- stage 2
def _default_llm(prompt):
    spec = importlib.util.spec_from_file_location(
        "research_grants", os.path.join(gl.DIR, "research-grants.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_claude(prompt)


def parse_llm_json(raw):
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in LLM response: {raw[:200]!r}")
    return json.loads(raw[start:end + 1])


def _conf(entry):
    try:
        return float(entry.get("confidence", 0))
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------- main
def extract(grant, page_text, today, llm=None):
    """Return {"fields": {...}, "review_items": [...]} for one grant page."""
    today = _as_date(today)
    llm = llm or _default_llm
    norm_text = norm_ws(page_text)
    gid = grant.get("id")
    fields, review, confs = {}, [], []

    def flag(field, value, quote, reason):
        review.append({"grant_id": gid, "field": field,
                       "value": value if isinstance(value, str)
                       else json.dumps(value, ensure_ascii=False),
                       "quote": quote or "", "reason": reason})

    def accept(entry, field, validate=None):
        """Return the value if entry passes all guards, else queue for review."""
        if not isinstance(entry, dict) or "value" not in entry:
            return None
        value, quote = entry["value"], entry.get("quote")
        if not grounded(quote, norm_text):
            flag(field, value, quote, "quote not found in page text")
        elif _conf(entry) < MIN_CONFIDENCE:
            flag(field, value, quote, f"low confidence {_conf(entry):.2f}")
        elif validate and not validate(value):
            flag(field, value, quote, "invalid value")
        else:
            confs.append(_conf(entry))
            return value
        return None

    # stage 1 - deterministic
    timeline = {}
    for k, (v, _q, c) in parse_dates(page_text, today).items():
        timeline[k] = v
        confs.append(c)
    amounts, _aq = parse_amounts(page_text)
    if amounts:
        fields.update(amounts)
        confs.append(0.8)

    # stage 2 - LLM
    prompt = PROMPT.format(name=grant.get("name", ""), funder=grant.get("organization", ""),
                           text=page_text)
    try:
        data = parse_llm_json(llm(prompt))
    except (ValueError, RuntimeError) as e:
        flag("*", "", "", f"LLM extraction failed: {e}")
        data = {}

    elig_in = data.get("eligibility") or {}
    elig = {}
    geo = accept(elig_in.get("geography"), "eligibility.geography",
                 lambda v: isinstance(v, str) and GEO_RE.match(v))
    if geo:
        elig["geography"] = geo
    ent = accept(elig_in.get("entityRequired"), "eligibility.entityRequired",
                 lambda v: v in ENTITY_VALUES)
    if ent:
        elig["entityRequired"] = ent
    types = accept(elig_in.get("applicantTypes"), "eligibility.applicantTypes",
                   lambda v: isinstance(v, list) and bool(v) and set(v) <= APPLICANT_TYPES)
    if types:
        elig["applicantTypes"] = types
    restr = []
    for r in elig_in.get("restrictions") or []:
        item = accept({"value": r.get("item"), "quote": r.get("quote"),
                       "confidence": r.get("confidence")}, "eligibility.restrictions")
        if item:
            restr.append(item)
    if restr:
        elig["restrictions"] = restr
    if elig:
        fields["eligibility"] = elig

    reqs = []
    for r in data.get("requirements") or []:
        item = accept({"value": r.get("item"), "quote": r.get("quote"),
                       "confidence": r.get("confidence")}, "requirements")
        if item:
            reqs.append({"item": item, "quote": r["quote"]})
    if reqs:
        fields["requirements"] = reqs

    # LLM timeline fills only what the deterministic pass did not find
    tl_in = data.get("timeline") or {}
    for key in ("opensDate", "deadlineDate", "decisionDate"):
        if key in timeline or (key == "deadlineDate"
                               and timeline.get("deadlineType") == "rolling"):
            continue
        v = accept(tl_in.get(key), f"timeline.{key}",
                   lambda v: bool(gl._all_dates(str(v))))
        if v:
            timeline[key] = gl._all_dates(str(v))[0].isoformat()
    if "durationMonths" in tl_in:
        v = accept(tl_in["durationMonths"], "timeline.durationMonths",
                   lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0)
        if v:
            timeline["durationMonths"] = v
    if "deadlineDate" in timeline and "deadlineType" not in timeline:
        timeline["deadlineType"] = "fixed"
    if timeline:
        fields["timeline"] = timeline

    fields["_derived"] = {"by": "auto", "checked": today.isoformat(),
                          "confidence": round(min(confs), 2) if confs else 0.0}
    return {"fields": fields, "review_items": review}


def write_review(items, path=REVIEW_CSV):
    if not items:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_HEADER)
        if new:
            w.writeheader()
        w.writerows(items)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract grant requirements from page text")
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    grants = gl.load_existing()
    grant = next((g for g in grants if g.get("id") == args.id), None)
    if grant is None:
        sys.exit(f"no grant with id {args.id}")
    with open(args.text_file, encoding="utf-8") as f:
        text = f.read()
    result = extract(grant, text, datetime.date.today())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.dry_run:
        return
    write_review(result["review_items"])
    grant.update(result["fields"])
    gl.save(grants)


if __name__ == "__main__":
    main()
