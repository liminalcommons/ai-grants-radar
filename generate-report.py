#!/usr/bin/env python3
"""
generate-report.py — render the weekly AI Funding Radar report as HTML.

Produces ONE HTML string that doubles as:
  - a published web page (report.html, deployed to Vercel at /report)
  - the body of the weekly email
  - the source of a short Telegram summary (see telegram_summary())

Design: warm, earthy, "smooth like Claude" — cream paper, clay accent, serif
headings. Email-safe: inline styles + web-safe fonts + table layout, so it
renders the same in Gmail as on the web.

Usage:
  python generate-report.py            # write report.html for the last 7 days
  python generate-report.py --days 14  # custom window
  python generate-report.py --stdout   # print HTML to stdout instead of writing
"""

import datetime
import html
import os
import sys

import grants_lib as gl

REPORT_FILE = os.path.join(gl.DIR, "report.html")
LIVE_URL = "https://ai-grants-xi.vercel.app"

# ── earthy / Claude palette ───────────────────────────────────────────────
PAPER = "#F4F1EA"      # warm cream background
CARD = "#FBFAF6"       # card surface
INK = "#39352C"        # warm near-black
MUTED = "#8C8676"      # warm grey
CLAY = "#C2613F"       # Claude clay / terracotta accent
SAGE = "#6F7F5F"       # viable / positive
OCHRE = "#C09142"      # partial
DUST = "#9A8F7E"       # limited
LINE = "#E6E0D3"       # hairline border
SERIF = "'Spectral','Newsreader',Georgia,'Times New Roman',serif"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"

AUDIENCE_LABELS = {
    "team": "For AI Product Teams",
    "creator": "For Individual Creators & Builders",
    "org": "For Small Orgs & Nonprofits",
}
AUDIENCE_BLURB = {
    "team": "Compute credits, accelerators, and startup funding for small AI product teams.",
    "creator": "Fellowships, residencies, creator funds, and individual grants.",
    "org": "Capacity grants, impact funding, and tech-for-nonprofit programs.",
}
VIABILITY = {
    "yes": (SAGE, "VIABLE"),
    "partial": (OCHRE, "PARTIAL"),
    "no": (DUST, "LIMITED"),
}
# Funding-type chip — real money is the priority; credits come later.
FUNDING_CHIP = {
    "cash": (CLAY, "💵 CASH"),
    "mixed": (OCHRE, "◐ CASH + CREDITS"),
    "equity": ("#7E6BA8", "📈 EQUITY"),
    "credits": (MUTED, "☁ CREDITS"),
}
VIABILITY_ORDER = {"yes": 0, "partial": 1, "no": 2}


def sort_key(g):
    return (gl.FUNDING_RANK.get(g.get("fundingType", "cash"), 9),
            VIABILITY_ORDER.get(g.get("viability", "partial"), 9))


def esc(s):
    return html.escape(str(s or ""))


def recent(grants, cutoff_iso):
    return [g for g in grants if (g.get("_updated") or "") >= cutoff_iso]


def audiences_of(grant):
    aud = grant.get("audience") or ["team"]
    return aud if isinstance(aud, list) else [aud]


def card_html(g):
    color, label = VIABILITY.get(g.get("viability", "partial"), VIABILITY["partial"])
    fcolor, flabel = FUNDING_CHIP.get(g.get("fundingType", "cash"), FUNDING_CHIP["cash"])
    url = esc(g.get("url", "#"))
    tags = " · ".join(esc(t) for t in (g.get("tags") or [])[:5])
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 14px 0;background:{CARD};border:1px solid {LINE};border-left:3px solid {color};border-radius:8px;">
      <tr><td style="padding:18px 20px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="font-family:{SERIF};font-size:18px;font-weight:600;color:{INK};line-height:1.3;">
            <a href="{url}" style="color:{INK};text-decoration:none;">{esc(g.get('name'))}</a>
          </td>
          <td align="right" style="white-space:nowrap;vertical-align:top;">
            <span style="font-family:{SANS};font-size:10px;font-weight:700;letter-spacing:0.04em;color:{fcolor};border:1px solid {fcolor};border-radius:4px;padding:2px 7px;">{flabel}</span>
            &nbsp;<span style="font-family:{SANS};font-size:10px;font-weight:700;letter-spacing:0.08em;color:{color};border:1px solid {color};border-radius:4px;padding:2px 7px;">{label}</span>
          </td>
        </tr></table>
        <div style="font-family:{SANS};font-size:12px;color:{MUTED};margin:4px 0 10px 0;">
          {esc(g.get('organization'))} &nbsp;•&nbsp; <span style="color:{CLAY};font-weight:600;">{esc(g.get('amount'))}</span> &nbsp;•&nbsp; {esc(g.get('deadline'))}
        </div>
        <div style="font-family:{SANS};font-size:13.5px;color:{INK};line-height:1.55;opacity:0.92;">
          {esc(g.get('description'))}
        </div>
        <div style="font-family:{SANS};font-size:12.5px;color:{INK};line-height:1.5;margin-top:10px;padding:8px 12px;background:{PAPER};border-radius:6px;">
          <span style="color:{color};font-weight:700;">{label}:</span> {esc(g.get('viabilityNote'))}
        </div>
        <div style="font-family:{SANS};font-size:11px;color:{MUTED};margin-top:10px;">
          {tags} &nbsp;&nbsp;<a href="{url}" style="color:{CLAY};text-decoration:none;font-weight:600;">Open program →</a>
        </div>
      </td></tr>
    </table>"""


def section_html(audience, grants):
    if not grants:
        return ""
    cards = "".join(card_html(g) for g in sorted(grants, key=sort_key))
    return f"""
    <tr><td style="padding:8px 0 4px 0;">
      <div style="font-family:{SERIF};font-size:22px;font-weight:700;color:{INK};margin-top:14px;">{AUDIENCE_LABELS.get(audience, audience.title())}</div>
      <div style="font-family:{SANS};font-size:13px;color:{MUTED};margin:2px 0 14px 0;">{AUDIENCE_BLURB.get(audience,'')} &nbsp;·&nbsp; {len(grants)} new</div>
      {cards}
    </td></tr>"""


def is_credits(g):
    return g.get("fundingType") == "credits"


def credits_appendix(credit_grants):
    """Condensed 'for later' list of credit/compute programs."""
    if not credit_grants:
        return ""
    rows = "".join(
        f"""<tr><td style="font-family:{SANS};font-size:13px;color:{INK};padding:5px 0;border-bottom:1px solid {LINE};">
          <a href="{esc(g.get('url','#'))}" style="color:{INK};text-decoration:none;font-weight:600;">{esc(g.get('name'))}</a>
          <span style="color:{MUTED};">— {esc(g.get('amount'))}</span></td></tr>"""
        for g in sorted(credit_grants, key=sort_key)
    )
    return f"""
    <tr><td style="padding:18px 0 4px 0;">
      <div style="font-family:{SERIF};font-size:18px;font-weight:700;color:{MUTED};">☁ Credits &amp; Compute <span style="font-size:13px;font-weight:400;">— for later</span></div>
      <div style="font-family:{SANS};font-size:12px;color:{MUTED};margin:2px 0 10px 0;">Useful, but not real money. {len(credit_grants)} new.</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>
    </td></tr>"""


def render(grants, days):
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=days)).isoformat()
    new = recent(grants, cutoff)
    money = [g for g in new if not is_credits(g)]   # cash / mixed / equity — the priority
    credit_grants = [g for g in new if is_credits(g)]

    by_aud = {a: [] for a in AUDIENCE_LABELS}
    for g in money:
        for a in audiences_of(g):
            by_aud.setdefault(a, []).append(g)

    date_str = today.strftime("%B %-d, %Y") if os.name != "nt" else today.strftime("%B %#d, %Y")

    sections = "".join(section_html(a, by_aud.get(a, [])) for a in AUDIENCE_LABELS)
    sections += credits_appendix(credit_grants)
    if not new:
        sections = f"""<tr><td style="padding:30px 0;font-family:{SANS};font-size:14px;color:{MUTED};text-align:center;">
          No new opportunities surfaced this week. The radar still tracks {len(grants)} live programs —
          <a href="{LIVE_URL}" style="color:{CLAY};">browse them all →</a></td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI Funding Radar — Weekly Report</title></head>
<body style="margin:0;padding:0;background:{PAPER};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER};">
<tr><td align="center" style="padding:32px 16px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">

    <tr><td style="padding-bottom:6px;">
      <div style="font-family:{SANS};font-size:11px;font-weight:700;letter-spacing:0.18em;color:{CLAY};text-transform:uppercase;">AI Funding Radar · Weekly</div>
      <div style="font-family:{SERIF};font-size:34px;font-weight:900;color:{INK};line-height:1.15;margin-top:6px;">This Week in Grants</div>
      <div style="font-family:{SANS};font-size:13px;color:{MUTED};margin-top:8px;">{date_str} &nbsp;·&nbsp; <span style="color:{CLAY};font-weight:700;">{len(money)} real-money grants</span> &nbsp;·&nbsp; {len(credit_grants)} credit programs (later)</div>
    </td></tr>

    <tr><td style="padding:18px 0;">
      <div style="height:1px;background:{LINE};"></div>
    </td></tr>

    {sections}

    <tr><td style="padding:24px 0 8px 0;">
      <div style="height:1px;background:{LINE};margin-bottom:18px;"></div>
      <table role="presentation" width="100%"><tr>
        <td style="font-family:{SANS};font-size:12px;color:{MUTED};line-height:1.6;">
          Tracking <strong style="color:{INK};">{len(grants)}</strong> programs across teams, creators &amp; orgs.<br>
          Curated for Liminal Commons and our community.
        </td>
        <td align="right">
          <a href="{LIVE_URL}" style="font-family:{SANS};font-size:13px;font-weight:700;color:{PAPER};background:{CLAY};text-decoration:none;padding:10px 18px;border-radius:8px;">Open the full radar →</a>
        </td>
      </tr></table>
    </td></tr>

  </table>
</td></tr></table>
</body></html>"""


def telegram_summary(grants, days=7):
    """Short plaintext summary for a Telegram group post (+ link)."""
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=days)).isoformat()
    new = recent(grants, cutoff)
    if not new:
        return f"🛰️ AI Funding Radar — no new grants this week. {len(grants)} tracked: {LIVE_URL}"
    money = sorted([g for g in new if not is_credits(g)], key=sort_key)
    credit_grants = [g for g in new if is_credits(g)]
    lines = [f"🛰️ *AI Funding Radar* — {len(money)} real-money grants this week:"]
    for g in money[:12]:
        mark = {"cash": "💵", "mixed": "◐", "equity": "📈"}.get(g.get("fundingType"), "•")
        lines.append(f"{mark} {g.get('name')} — {g.get('amount')}")
    if credit_grants:
        lines.append(f"\n☁ +{len(credit_grants)} credit/compute programs (for later)")
    lines.append(f"\nFull radar → {LIVE_URL}")
    return "\n".join(lines)


def main():
    days = 7
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    grants = gl.load_existing()
    out = render(grants, days)
    if "--stdout" in sys.argv:
        print(out)
        return
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(out)
    new_count = len(recent(grants, (datetime.date.today() - datetime.timedelta(days=days)).isoformat()))
    print(f"Wrote {REPORT_FILE} ({new_count} new in last {days}d, {len(grants)} total).")


if __name__ == "__main__":
    main()
