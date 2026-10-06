"""Polite page fetcher: robots.txt, 1 req/s per host, retries, link health.

Never bypasses logins/captchas/403: those are reported as status 'blocked'.
Network goes through `_http_get` so tests can mock it.
"""
import re
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from urllib.parse import urlsplit

USER_AGENT = "FundingRadarBot/1.0 (+https://github.com/liminalcommons/funding-radar)"
TIMEOUT = 20
MAX_BYTES = 5_000_000
RETRIES = 2          # extra attempts after the first, on 5xx / network errors
BACKOFF = 1.5        # seconds, doubled per retry

_sleep = time.sleep
_now = time.monotonic

_robots_cache = {}
_rate_lock = threading.Lock()
_next_slot = {}      # host -> monotonic time the next request may start

_CAPTCHA = re.compile(r"g-recaptcha|hcaptcha|cf-challenge|cf-turnstile|captcha-delivery|"
                      r"just a moment\.\.\.|verify you are human", re.I)
_LOGIN_PATH = re.compile(r"/(log-?in|sign-?in|sso|auth)(/|$)", re.I)
_PASSWORD_FIELD = re.compile(r"<input[^>]+type=[\"']?password", re.I)


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(url):
    p = urlsplit(url)
    return (p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", p.query)


def _http_get(url, timeout=TIMEOUT):
    """Return (code, final_url, headers_dict, body_bytes). Raises OSError on network failure."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.8,*/*;q=0.5",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), {k.lower(): v for k, v in r.headers.items()}, r.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        try:
            body = e.read(MAX_BYTES)
        except Exception:
            body = b""
        return e.code, e.geturl() or url, {k.lower(): v for k, v in (e.headers or {}).items()}, body


def _robots_allows(url):
    p = urlsplit(url)
    origin = f"{p.scheme}://{p.netloc}"
    rp = _robots_cache.get(origin)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            code, _, _, body = _http_get(origin + "/robots.txt", TIMEOUT)
        except OSError:
            code, body = None, b""
        if code in (401, 403):
            rp.parse(["User-agent: *", "Disallow: /"])
        elif code == 200:
            rp.parse(body.decode("utf-8", "replace").splitlines())
        else:
            rp.parse([])  # missing/unreachable robots.txt: allowed
        _robots_cache[origin] = rp
    return rp.can_fetch(USER_AGENT, url)


def _wait_for_slot(host, rps):
    interval = 1.0 / rps if rps > 0 else 0.0
    with _rate_lock:
        start = max(_now(), _next_slot.get(host, 0.0))
        _next_slot[host] = start + interval
    delay = start - _now()
    if delay > 0:
        _sleep(delay)


def _result(status, url, final_url=None, code=None, html="", content_type="html", **extra):
    r = {"status": status, "final_url": final_url or url, "http_code": code,
         "html": html, "fetched_at": _utcnow(), "content_type": content_type}
    r.update(extra)
    return r


def _looks_blocked(final_url, html):
    if _LOGIN_PATH.search(urlsplit(final_url).path):
        return "login wall"
    if _CAPTCHA.search(html):
        return "captcha"
    if _PASSWORD_FIELD.search(html) and len(re.sub(r"<[^>]+>", " ", html).split()) < 150:
        return "login wall"
    return None


def fetch(url, max_per_host_rps=1):
    """Fetch one URL -> {status ok|dead|redirect|blocked, final_url, http_code, html,
    fetched_at, content_type}. status 'redirect' means final_url differs from url.
    PDFs: status ok, content_type 'pdf', html '' and pdf_text_extracted False (out of scope)."""
    if urlsplit(url).scheme not in ("http", "https"):
        return _result("dead", url, error="unsupported scheme")
    host = urlsplit(url).netloc.lower()
    if not _robots_allows(url):
        return _result("blocked", url, error="robots.txt disallows")

    code = final_url = headers = body = None
    err = None
    for attempt in range(RETRIES + 1):
        _wait_for_slot(host, max_per_host_rps)
        try:
            code, final_url, headers, body = _http_get(url, TIMEOUT)
            err = None
        except OSError as e:
            code, err = None, f"{type(e).__name__}: {e}"
        if err is None and code < 500:
            break
        if attempt < RETRIES:
            _sleep(BACKOFF * (2 ** attempt))

    if err is not None:
        return _result("dead", url, error=err)
    final_url = final_url or url
    if code in (401, 403, 429):
        return _result("blocked", url, final_url, code, error=f"HTTP {code}")
    if code >= 400:
        return _result("dead", url, final_url, code)

    status = "ok" if _norm(final_url) == _norm(url) else "redirect"
    ctype = (headers or {}).get("content-type", "").lower()
    if "application/pdf" in ctype or urlsplit(final_url).path.lower().endswith(".pdf"):
        return _result(status, url, final_url, code, content_type="pdf", pdf_text_extracted=False)

    m = re.search(r"charset=([\w-]+)", ctype)
    try:
        html = body.decode(m.group(1) if m else "utf-8", "replace")
    except LookupError:
        html = body.decode("utf-8", "replace")
    why = _looks_blocked(final_url, html)
    if why:
        return _result("blocked", url, final_url, code, html=html, error=why)
    return _result(status, url, final_url, code, html=html)


def fetch_many(urls, max_per_host_rps=1, max_workers=8, overall_timeout=300):
    """Fetch many URLs concurrently (rate limited per host). Returns {url: result}.
    URLs unfinished after `overall_timeout` seconds get status 'dead' with
    error='timeout' and transient=True (callers should treat that as unknown)."""
    urls = list(dict.fromkeys(urls))
    out = {}
    ex = ThreadPoolExecutor(max_workers=max_workers)
    futs = {ex.submit(fetch, u, max_per_host_rps): u for u in urls}
    done, pending = wait(futs, timeout=overall_timeout)
    for f in done:
        try:
            out[futs[f]] = f.result()
        except Exception as e:
            out[futs[f]] = _result("dead", futs[f], error=f"{type(e).__name__}: {e}", transient=True)
    for f in pending:
        f.cancel()
        out[futs[f]] = _result("dead", futs[f], error="timeout", transient=True)
    ex.shutdown(wait=False, cancel_futures=True)
    return {u: out[u] for u in urls}
