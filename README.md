# AI Funding Radar

A self-updating radar of AI funding opportunities for **three audiences** —
small AI product teams, individual creators/builders, and small orgs/nonprofits —
with **real cash prioritized over cloud credits**.

Live: https://ai-grants-xi.vercel.app · Weekly report: `/report.html`

## Pipeline

| Script | Role |
|---|---|
| `grants_lib.py` | shared core: load/save, dedup-merge, mojibake repair, funding-type classifier, Vercel deploy, `.env` loader |
| `research-grants.py` | discover new grants via headless Claude + web search (`--audience team\|creator\|org`) |
| `generate-report.py` | render the earthy weekly HTML report (`report.html`) — cash-first, credits in a "for later" appendix |
| `notify.py` | deliver: Telegram group post + email (HTML report) |
| `weekly.py` | the full weekly pipeline: research → report → deploy → notify |
| `update-grants.py` | manually merge a JSON file/object of grants |

## Run

```bash
python weekly.py            # full weekly pipeline
python research-grants.py   # just discovery (all audiences)
python generate-report.py   # just render report.html
python notify.py            # just deliver (needs .env)
python test_grants_lib.py   # tests
```

## Secrets

Copy `.env.example` → `.env` (gitignored). Telegram needs `TELEGRAM_BOT_TOKEN` +
`TELEGRAM_CHAT_ID`; email needs `SMTP_*`. Missing channels are skipped, not failed.

## Data

`grants.json` — each record carries `audience` (subset of team/creator/org),
`fundingType` (cash/credits/equity/mixed), `viability` (yes/partial/no), and
`relevant2026`. The site (`index.html`) and report read this file directly.

## Weekly automation

A weekly Claude Code routine (or local scheduler) runs `weekly.py`. The routine
prioritizes **non-dilutive cash** (grants, fellowships, prizes) and treats cloud
credits as secondary.
