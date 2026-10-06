#!/usr/bin/env python3
"""Offline tests for scrape/. Run: python test_scrape.py (network is mocked)."""
import time
from contextlib import contextmanager
from pathlib import Path

import importlib

F = importlib.import_module("scrape.fetch")  # scrape.fetch the name is the function
from scrape import fetch_many, html_to_text, content_hash

PAGES = Path(__file__).parent / "tests" / "fixtures" / "pages"
HTML = {"Content-Type": "text/html; charset=utf-8"}


def page(name):
    return (PAGES / name).read_text(encoding="utf-8")


@contextmanager
def fake_net(routes, robots="", sleeps=None, clock=None):
    """routes: url -> (code, final_url, headers, body) or list of those (consumed in order)
    or an Exception. Patches the network layer, sleep and rate-limit state."""
    calls = []

    def http_get(url, timeout=20):
        calls.append(url)
        if url.endswith("/robots.txt"):
            if isinstance(robots, tuple):
                return robots[0], url, {}, robots[1].encode()
            return 200, url, {}, robots.encode()
        r = routes[url]
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        if isinstance(r, Exception):
            raise r
        code, final, headers, body = r
        return code, final or url, headers, body.encode() if isinstance(body, str) else body

    saved = (F._http_get, F._sleep, F._now)
    F._http_get = http_get
    F._sleep = (lambda s: sleeps.append(s)) if sleeps is not None else (lambda s: None)
    F._now = clock or time.monotonic
    F._robots_cache.clear()
    F._next_slot.clear()
    try:
        yield calls
    finally:
        F._http_get, F._sleep, F._now = saved
        F._robots_cache.clear()
        F._next_slot.clear()


U = "https://fund.example.org/grant"


def test_ok_page():
    with fake_net({U: (200, U, HTML, page("grant_basic.html"))}):
        r = F.fetch(U)
    assert r["status"] == "ok" and r["http_code"] == 200 and r["final_url"] == U
    assert "Climate Innovation Fund" in r["html"] and r["fetched_at"].endswith("Z")


def test_robots_disallow_is_blocked_and_page_not_requested():
    with fake_net({U: (200, U, HTML, "x")}, robots="User-agent: *\nDisallow: /grant") as calls:
        r = F.fetch(U)
    assert r["status"] == "blocked" and "robots" in r["error"]
    assert U not in calls


def test_robots_for_our_agent_name_applies():
    robots = "User-agent: FundingRadarBot\nDisallow: /\n"
    with fake_net({U: (200, U, HTML, "x")}, robots=robots):
        assert F.fetch(U)["status"] == "blocked"


def test_missing_robots_allows():
    with fake_net({U: (200, U, HTML, "<p>hi</p>")}, robots=(404, "")):
        assert F.fetch(U)["status"] == "ok"


def test_404_is_dead():
    with fake_net({U: (404, U, HTML, "nope")}):
        r = F.fetch(U)
    assert r["status"] == "dead" and r["http_code"] == 404


def test_301_is_redirect_with_final_url():
    new = "https://fund.example.org/new-grant"
    with fake_net({U: (200, new, HTML, page("grant_basic.html"))}):
        r = F.fetch(U)
    assert r["status"] == "redirect" and r["final_url"] == new
    assert "Climate" in r["html"]


def test_trailing_slash_is_not_redirect():
    with fake_net({U: (200, U + "/", HTML, "<p>x</p>")}):
        assert F.fetch(U)["status"] == "ok"


def test_403_and_429_blocked():
    for code in (401, 403, 429):
        with fake_net({U: (code, U, HTML, "denied")}):
            assert F.fetch(U)["status"] == "blocked", code


def test_captcha_and_login_wall_blocked_not_bypassed():
    with fake_net({U: (200, U, HTML, page("captcha.html"))}):
        assert F.fetch(U)["status"] == "blocked"
    with fake_net({U: (200, U, HTML, page("login_wall.html"))}):
        assert F.fetch(U)["status"] == "blocked"
    login = "https://fund.example.org/login"
    with fake_net({U: (200, login, HTML, "<p>Please enter your details</p>")}):
        assert F.fetch(U)["status"] == "blocked"


def test_5xx_retries_with_backoff_then_succeeds():
    sleeps = []
    seq = [(503, U, HTML, ""), (500, U, HTML, ""), (200, U, HTML, "<p>ok</p>")]
    with fake_net({U: seq}, sleeps=sleeps) as calls:
        r = F.fetch(U)
    assert r["status"] == "ok"
    assert calls.count(U) == 3
    assert [s for s in sleeps if s in (1.5, 3.0)] == [1.5, 3.0], sleeps


def test_5xx_exhausts_retries_dead():
    with fake_net({U: (502, U, HTML, "")}) as calls:
        r = F.fetch(U)
    assert r["status"] == "dead" and r["http_code"] == 502
    assert calls.count(U) == 3  # first try + 2 retries


def test_network_error_dead():
    with fake_net({U: OSError("boom")}):
        r = F.fetch(U)
    assert r["status"] == "dead" and r["http_code"] is None and "boom" in r["error"]


def test_pdf_flagged():
    pdf = "https://fund.example.org/call.pdf"
    with fake_net({pdf: (200, pdf, {"Content-Type": "application/pdf"}, b"%PDF-1.4")}):
        r = F.fetch(pdf)
    assert r["status"] == "ok" and r["content_type"] == "pdf"
    assert r["pdf_text_extracted"] is False and r["html"] == ""


def test_rate_limit_one_per_second_per_host():
    sleeps = []
    t = [100.0]
    routes = {f"https://a.example/{i}": (200, f"https://a.example/{i}", HTML, "<p>x</p>") for i in range(3)}
    routes["https://b.example/0"] = (200, "https://b.example/0", HTML, "<p>x</p>")
    with fake_net(routes, sleeps=sleeps, clock=lambda: t[0]):
        for u in routes:
            F.fetch(u)
    # frozen clock: same-host requests 2 and 3 wait 1s and 2s; first and other host do not wait
    assert [round(s, 2) for s in sleeps] == [1.0, 2.0]


def test_fetch_many_returns_all_and_does_not_hang_on_slow_host():
    fast = "https://fast.example/x"
    slow = "https://slow.example/x"
    orig = F.fetch

    def fake_fetch(u, rps=1):
        if "slow" in u:
            time.sleep(2)
        return F._result("ok", u, html="<p>x</p>")

    F.fetch = fake_fetch
    try:
        t0 = time.time()
        res = fetch_many([fast, slow, fast], overall_timeout=0.3)
        elapsed = time.time() - t0
    finally:
        F.fetch = orig
    assert elapsed < 1.5
    assert res[fast]["status"] == "ok"
    assert res[slow]["status"] == "dead" and res[slow]["error"] == "timeout" and res[slow]["transient"]
    assert list(res) == [fast, slow]


def test_html_to_text_strips_chrome_keeps_structure():
    t = html_to_text(page("grant_basic.html"))
    assert "# Climate Innovation Fund" in t
    assert "## Requirements" in t
    assert "- Registered company in the EU" in t
    assert "- Less than 5 years old" in t
    assert "Deadline: 30 June 2026" in t
    for junk in ("var x", "color:red", "About us", "Copyright", "Privacy"):
        assert junk not in t, junk


def test_hash_stable_across_whitespace_nav_footer_and_case_changes():
    a = content_hash(html_to_text(page("grant_basic.html")))
    b = content_hash(html_to_text(page("grant_reformatted.html")))
    assert a == b
    assert content_hash("Hello   World\n") == content_hash(" hello world")


def test_hash_changes_when_content_changes():
    a = content_hash(html_to_text(page("grant_basic.html")))
    c = content_hash(html_to_text(page("grant_changed.html")))
    assert a != c


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
            passed += 1
    print(f"\n{passed} tests passed.")
