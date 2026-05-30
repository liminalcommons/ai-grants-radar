#!/usr/bin/env python3
"""
notify.py — deliver the weekly report via Telegram group + email.

Stdlib only (urllib + smtplib), so it runs anywhere — locally, in a cron, or
inside a Claude Code routine. Credentials come from environment variables; if a
channel's vars are missing, that channel is skipped with a clear message
(never a hard failure), so you can wire one channel at a time.

Env vars:
  Telegram:  TELEGRAM_BOT_TOKEN   (from @BotFather)
             TELEGRAM_CHAT_ID     (the group's chat id, usually negative)
  Email:     SMTP_HOST  SMTP_PORT  SMTP_USER  SMTP_PASS
             REPORT_EMAIL_TO      (default: account1@liminalcommons.com)
             REPORT_EMAIL_FROM    (default: SMTP_USER)

Usage:
  python notify.py            # send to whatever channels are configured
  python notify.py --telegram # only Telegram
  python notify.py --email    # only email
"""

import os
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
from email.message import EmailMessage

import grants_lib as gl
import importlib

report = importlib.import_module("generate-report")  # module name has a hyphen

DEFAULT_TO = "account1@liminalcommons.com"


def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        print("  [telegram] skipped — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        return False
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "false",
    }).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
        ok = r.status == 200
    print(f"  [telegram] {'sent' if ok else 'failed'} to group {chat_id}.")
    return ok


def send_email(html_body, subject):
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    if not (host and user and password):
        print("  [email] skipped — set SMTP_HOST, SMTP_USER, SMTP_PASS.")
        return False
    port = int(os.environ.get("SMTP_PORT", "587"))
    to_addr = os.environ.get("REPORT_EMAIL_TO", DEFAULT_TO)
    from_addr = os.environ.get("REPORT_EMAIL_FROM", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content("This is the weekly AI Funding Radar report. View in an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls(context=ctx)
        s.login(user, password)
        s.send_message(msg)
    print(f"  [email] sent to {to_addr}.")
    return True


def main():
    only_tg = "--telegram" in sys.argv
    only_email = "--email" in sys.argv
    do_tg = only_tg or not only_email
    do_email = only_email or not only_tg

    grants = gl.load_existing()
    html_body = report.render(grants, days=7)
    summary = report.telegram_summary(grants, days=7)
    new_count = len(report.recent(grants, _cutoff(7)))
    subject = f"🛰️ AI Funding Radar — {new_count} new this week"

    print("Delivering weekly report...")
    if do_tg:
        send_telegram(summary)
    if do_email:
        send_email(html_body, subject)


def _cutoff(days):
    import datetime
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


if __name__ == "__main__":
    main()
