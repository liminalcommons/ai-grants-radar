#!/usr/bin/env python3
"""
research-grants.py — autonomous AI-grant discovery for the AI Funding Radar.

Drives headless Claude Code (`claude -p`) with web search to find AI grants,
accelerators, and compute-credit programs relevant to a small for-profit AI
product team, then merges new finds into grants.json and redeploys to Vercel.

Backend: the `claude` CLI already authenticated in this environment (web search
enabled). No separate API key or local LLM endpoint needed — this replaces the
old DuckDuckGo + MiniMax/LiteLLM pipeline that broke (HTTP 400, 2026-04-02).

Usage:
  python research-grants.py                      # research all audiences, merge, deploy
  python research-grants.py --audience creator   # one audience: team|creator|org
  python research-grants.py --dry-run            # research + print finds, no save/deploy
  python research-grants.py --no-deploy          # research + save, skip Vercel deploy
"""

import datetime
import json
import re
import sys
import subprocess

import grants_lib as gl

TODAY = datetime.date.today().isoformat()

CLAUDE_TIMEOUT_S = 600
MAX_TURNS = 40

# Each audience defines who we're hunting funding for. The `audience` tag is
# written onto every grant so the site + report can group by it.
AUDIENCE_PROFILES = {
    "team": """\
We are Liminal Commons: a small (2-10 person) FOR-PROFIT team that ships
production AI-integrated collaboration platforms (Castalia, Vox). We run a
self-hosted local AI stack. Product builders, not academics, not a nonprofit.

Find funding for a team like this:
  "yes"     -> no equity, rolling/simple application, open to for-profit startups,
               OR cloud/compute credits (Google Cloud, MS for Startups, NVIDIA
               Inception, AWS Activate, accelerators without equity).
  "partial" -> viable with the right framing: US SBIR (if US-inc), EU grants (if
               EU entity), foundation grants needing a nonprofit/gov partner,
               AI-safety grants needing a safety angle.
  "no"      -> requires academic affiliation, defense/DARPA, age/gender/geo limits,
               health/LMIC-only, or a large established nonprofit.""",
    "creator": """\
We serve a COMMUNITY of individual creators and builders: indie developers,
students, researchers, artists, and solo founders using AI in their work.

Find funding an INDIVIDUAL can apply for:
  "yes"     -> open to individuals, simple application, no institution required
               (fellowships, creator funds, residencies, individual research
               grants, hackathon prizes, free compute/credits for individuals,
               microgrants, open-source maintainer funds).
  "partial" -> individual-eligible but competitive or needing a sponsor/mentor.
  "no"      -> requires a registered company, team, or institutional affiliation.""",
    "org": """\
We serve a COMMUNITY of small organizations: nonprofits, community groups,
civic and educational organizations doing mission-driven work, often with AI.

Find funding a SMALL ORG / NONPROFIT can apply for:
  "yes"     -> open to small nonprofits/community groups, manageable application
               (capacity grants, foundation/impact funding, AI-for-good programs,
               tech-for-nonprofits credits like Google for Nonprofits, Microsoft
               nonprofit grants, community/operating grants).
  "partial" -> needs 501(c)(3) or fiscal sponsor, or a competitive RFP.
  "no"      -> for-profit only, individuals only, or requires a large established
               institution / academic affiliation.""",
}

PROMPT_TEMPLATE = """\
You are a grant-research agent. Use web search to find CURRENT (open now or
opening/closing in 2026) funding opportunities relevant to the audience below.
Scope is BROAD — list ANYTHING with real cash a small team / individual / small
org could realistically win, across ALL fields: AI, open-source, web3/public
goods, climate, creative/arts, research, civic/social, and general startup.
If it gives cash, it belongs on the radar.

ALSO MONITOR web3 / public-goods funding explicitly: Gitcoin Grants rounds,
Giveth, Optimism RetroPGF, quadratic-funding rounds, Protocol Guild, Drips,
Octant, Funding the Commons, and similar mechanisms.

{audience_context}

PRIORITY: we need REAL MONEY, not credits. Lead with non-dilutive cash — grants,
fellowships with stipends, prize money, QF/retro payouts, foundation/government
cash. Cloud/compute credits come later: include at most 1-2.
ALSO favor LOW-EFFORT applications (rolling, simple forms) — flag effort honestly.

Find {n} opportunities NOT already in our database. Prefer ones with
viability "yes" or "partial". Do not invent programs or URLs.

DEADLINE VERIFICATION (mandatory for every opportunity before including it):
Today's date is {today}. Anchor all "is this still open?" reasoning to this date.

For EACH opportunity you consider:
1. Open the actual program or application page and CONFIRM the current deadline.
   Never infer or carry over a deadline from memory or a third-party listing.
2. Determine HOW the deadline works and classify it as one of:
   - "fixed"     — a specific future calendar date (set deadlineDate to that ISO date)
   - "rolling"   — truly always-open / accept applications continuously
   - "recurring" — a periodic program; the last window may have closed but the next
                   cycle is expected or already announced
   - "unknown"   — deadline mechanics are genuinely unclear from the program page
3. SKIP any opportunity whose ONLY known deadline has already passed and that has
   NO announced next window or cycle — that program is dead for our purposes.
4. For recurring programs where the last window closed but a next cycle is expected,
   the "deadline" string MUST describe the next window (e.g. "Next cohort expected
   late 2026") and deadlineDate stays null UNLESS a firm future date is confirmed.
5. When a concrete future date exists, deadlineDate MUST be the ISO "YYYY-MM-DD"
   of that date — do NOT leave it null if you have a real date.
6. Prefer opportunities that are open right now or have a clear upcoming window over
   ones that are vague or whose timeline is entirely uncertain.

ALREADY IN DATABASE (do not return these names):
{existing_names}

Return ONLY a JSON array (no prose, no markdown fences) where each element is:
{{
  "name": str,
  "organization": str,
  "category": "Corporate" | "Foundation" | "Government" | "Accelerator",
  "amount": str,                 // e.g. "Up to $350,000 in cloud credits"
  "deadline": str,               // "Rolling" or a human date
  "deadlineDate": str | null,    // ISO "YYYY-MM-DD" of the NEXT actionable date, else null
  "deadlineType": "fixed" | "rolling" | "recurring" | "unknown",  // how the deadline works
  "eligibility": str,
  "description": str,            // 1-3 sentences, concrete
  "url": str,                    // the real program/application page
  "tags": [str],
  "viability": "yes" | "partial" | "no",
  "viabilityNote": str,          // why, and what action to take
  "fundingType": "cash" | "credits" | "equity" | "mixed",  // cash = real money (prioritize)
  "effort": "low" | "medium" | "high",   // application burden — low = rolling/simple, high = SBIR/accelerator/RFP
  "domain": "AI" | "Web3 / Public Goods" | "Open Source" | "Climate" | "Creative" | "Research" | "Civic / Social" | "Startup / General",
  "relevant2026": true | false | "upcoming",
  "relevant2026Note": str
}}
Output the JSON array and nothing else.
"""


def build_prompt(existing, n, audience):
    names = "\n".join(f"  - {g.get('name', '')}" for g in existing)
    return PROMPT_TEMPLATE.format(
        audience_context=AUDIENCE_PROFILES[audience],
        n=n,
        existing_names=names,
        today=TODAY,
    )


def run_claude(prompt):
    """Invoke headless Claude with web search; return its text result."""
    proc = subprocess.run(
        f'claude -p --output-format json --allowedTools WebSearch WebFetch '
        f"--max-turns {MAX_TURNS}",
        input=prompt,
        capture_output=True,
        shell=True,
        cwd=gl.DIR,
        timeout=CLAUDE_TIMEOUT_S,
        encoding="utf-8",
        errors="replace",  # claude output can carry bytes cp1252 can't decode on Windows
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[:500]}")
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude error: {envelope.get('result')!r}")
    return envelope.get("result", "")


def extract_json_array(text):
    """Pull the first top-level JSON array out of Claude's text response."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON array found in response: {text[:300]!r}")
    return json.loads(text[start : end + 1])


def research_audience(existing, audience, n=8):
    """Research one audience; tag finds with it. Returns list of new records."""
    prompt = build_prompt(existing, n=n, audience=audience)
    print(f"[{audience}] researching via headless Claude (web search)...")
    finds = extract_json_array(run_claude(prompt))
    for f in finds:
        f["audience"] = [audience]
    print(f"[{audience}] returned {len(finds)} candidates.")
    return finds


def main():
    dry_run = "--dry-run" in sys.argv
    no_deploy = "--no-deploy" in sys.argv or dry_run

    audiences = list(AUDIENCE_PROFILES)
    if "--audience" in sys.argv:
        audiences = [sys.argv[sys.argv.index("--audience") + 1]]

    existing = gl.load_existing()
    print(f"Loaded {len(existing)} existing grants. Audiences: {', '.join(audiences)}")

    all_finds = []
    for audience in audiences:
        # Pass existing + already-found names so each pass avoids duplicates.
        all_finds += research_audience(existing + all_finds, audience)

    if dry_run:
        print(json.dumps([gl.normalise(f) for f in all_finds], indent=2, ensure_ascii=False))
        return

    added = gl.merge(existing, all_finds)
    if not added:
        print("No new grants to add.")
        return

    gl.save(existing)
    print(f"Added {len(added)} grants: {', '.join(added)}")
    print(f"Total: {len(existing)} grants.")

    if no_deploy:
        print("Skipping deploy (--no-deploy).")
        return
    try:
        gl.deploy()
    except subprocess.CalledProcessError as e:
        print(f"  Deploy failed: {e}. Run `npx vercel --prod` in {gl.DIR} manually.")


if __name__ == "__main__":
    main()
