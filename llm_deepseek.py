#!/usr/bin/env python3
"""
llm_deepseek.py — DeepSeek via OpenCode Go (Zen) for v1 batch scripts.

Owner-authorized for modest, batched calls. EVERY call appends one row to
spend-ledger.csv (ts, tag, model, input/output tokens, latency, status) —
never bypass spend logging. Jev is OFF; this module must never call Jev.

Usage:
    import llm_deepseek as ds
    llm = ds.make_llm("trial-extract", session_id="eval-2026-10-07")
    text = llm(prompt)   # -> str (raises RuntimeError on HTTP/API failure)

OpenAI-compatible endpoint; auth is Bearer OPENCODE_GO_API_KEY (ai-grants/.env,
already loaded by grants_lib). Sends x-opencode-session + grants-bot UA like
the v1 chat worker.
"""

import csv
import datetime
import json
import os
import time
import urllib.request

import grants_lib as gl  # noqa: F401  (loads .env on import)

ENDPOINT = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "deepseek-v4.1-flash"
USER_AGENT = "grants-bot/1.0"
LEDGER = os.path.join(gl.DIR, "spend-ledger.csv")
LEDGER_HEADER = ["ts", "tag", "model", "input_tokens", "output_tokens",
                 "latency_ms", "status", "error"]


def ensure_ledger(path=LEDGER):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(LEDGER_HEADER)
    return path


def log_spend(row, path=LEDGER):
    ensure_ledger(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([row.get(k, "") for k in LEDGER_HEADER])


def _post(payload, api_key, timeout):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}",
                 "User-Agent": USER_AGENT,
                 "x-opencode-session": payload.get("session_id", "v1-batch")},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def call_deepseek(prompt, tag, session_id="v1-batch", model=MODEL,
                  timeout=60, max_tokens=4000, post=_post,
                  ledger_path=LEDGER):
    """One chat-completions call. Returns reply text; always logs spend."""
    api_key = os.environ.get("OPENCODE_GO_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENCODE_GO_API_KEY not set (ai-grants/.env)")
    payload = {"model": model, "session_id": session_id,
               "messages": [{"role": "user", "content": prompt}],
               "max_tokens": max_tokens}
    if model.startswith("deepseek"):
        # json_object is a DeepSeek-only affordance here: other Go models 400 it.
        payload["response_format"] = {"type": "json_object"}
    t0 = time.monotonic()
    status, error, text, usage = None, "", "", {}
    try:
        status, body = post(payload, api_key, timeout)
        text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        usage = body.get("usage") or {}
        if not text:
            error = "empty reply"
        return text
    except Exception as e:  # noqa: BLE001 — must log then re-raise
        error = f"{type(e).__name__}: {e}"[:200]
        raise RuntimeError(f"DeepSeek call {tag} failed: {error}") from e
    finally:
        ms = int((time.monotonic() - t0) * 1000)
        log_spend({"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "tag": tag, "model": model,
                   "input_tokens": usage.get("prompt_tokens", ""),
                   "output_tokens": usage.get("completion_tokens", ""),
                   "latency_ms": ms, "status": status or "", "error": error},
                  ledger_path)


def make_llm(tag_prefix, session_id="v1-batch", **kw):
    """Return llm(prompt)->str compatible with extract_requirements.extract."""
    n = [0]

    def llm(prompt):
        n[0] += 1
        return call_deepseek(prompt, f"{tag_prefix}/{n[0]}",
                             session_id=session_id, **kw)
    return llm
