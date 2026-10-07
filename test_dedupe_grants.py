"""Tests for dedupe_grants.py: URL normalization and keeper choice."""

from dedupe_grants import dedupe, keeper_key, name_jaccard, normalize_url


def test_normalize_strips_tracking_and_case():
    assert (
        normalize_url("HTTPS://Example.ORG/Call/?utm_source=x&b=2&a=1")
        == "https://example.org/Call?a=1&b=2"
    )


def test_normalize_trailing_slash_and_ports():
    assert normalize_url("https://example.org/call/") == "https://example.org/call"
    assert normalize_url("https://example.org:443/call") == "https://example.org/call"
    assert normalize_url("http://example.org:80/") == "http://example.org/"


def test_normalize_keeps_meaningful_query():
    assert (
        normalize_url("https://example.org/fund?round=2026")
        == "https://example.org/fund?round=2026"
    )


def test_dedupe_prefers_deadline_then_description():
    rows = [
        {"id": "g2", "url": "https://example.org/a?utm=x", "name": "Grant A Program", "deadlineDate": "", "description": "long " * 50},
        {"id": "g1", "url": "https://example.org/a", "name": "Grant A", "deadlineDate": "2026-12-01", "description": "short"},
    ]
    kept, dropped = dedupe(rows)
    assert [r["id"] for r in kept] == ["g1"]
    assert dropped == {"g1": ["g2"]}


def test_dedupe_stable_tiebreak_by_lowest_id():
    rows = [
        {"id": "g9", "url": "https://example.org/a", "name": "Same Grant"},
        {"id": "g3", "url": "https://example.org/a/", "name": "Same Grant"},
    ]
    kept, dropped = dedupe(rows)
    assert [r["id"] for r in kept] == ["g3"]
    assert dropped == {"g3": ["g9"]}


def test_dedupe_keeps_uniques_and_empty_urls_by_id():
    rows = [
        {"id": "g1", "url": "https://example.org/a"},
        {"id": "g2", "url": "https://example.org/b"},
        {"id": "g3", "url": ""},
    ]
    kept, dropped = dedupe(rows)
    assert [r["id"] for r in kept] == ["g1", "g2", "g3"]
    assert dropped == {}


def test_keeper_key_orders_deadline_first():
    dated = {"id": "g1", "deadlineDate": "2026-01-01", "description": "x"}
    richer = {"id": "g2", "deadlineDate": "", "description": "x" * 5000}
    assert keeper_key(dated) > keeper_key(richer)


def test_normalize_strips_bare_utm_and_fbclid():
    assert normalize_url("https://example.org/a?utm=x") == "https://example.org/a"
    assert (
        normalize_url("https://example.org/a?fbclid=AbC&page=2")
        == "https://example.org/a?page=2"
    )


def test_dedupe_handles_integer_ids():
    rows = [
        {"id": 9, "url": "https://example.org/a", "name": "Same Grant"},
        {"id": 3, "url": "https://example.org/a/", "name": "Same Grant"},
    ]
    kept, dropped = dedupe(rows)
    assert [r["id"] for r in kept] == [3]
    assert dropped == {3: [9]}


def test_name_jaccard_spots_variants_and_hub_mates():
    assert name_jaccard("The Freed Fellowship Grant", "Freed Fellowship Grant") == 1.0
    assert name_jaccard("Open Source AGI Grant Programme", "Open Source AGI Grant & Investment Program") >= 0.5
    assert name_jaccard("Trailblazer AI Grant Program", "Audit Program") < 0.5
    assert name_jaccard("Arab Documentary Photography Program", "Inge Morath Award") < 0.5


def test_dedupe_keeps_distinct_programs_on_hub_url():
    rows = [
        {"id": 1, "url": "https://example.org/grants", "name": "Trailblazer AI Grant Program"},
        {"id": 2, "url": "https://example.org/grants", "name": "Audit Program"},
        {"id": 3, "url": "https://example.org/grants", "name": "ArbiFuel"},
    ]
    kept, dropped = dedupe(rows)
    assert sorted(r["id"] for r in kept) == [1, 2, 3]
    assert dropped == {}


def test_same_grant_uses_containment_not_overlap():
    from dedupe_grants import same_grant
    assert same_grant("The Freed Fellowship Grant", "Freed Fellowship Grant")
    assert same_grant("Rapid Response Grants", "Meyer Foundation — Rapid Response Grants")
    assert not same_grant("Arbitrum Trailblazer AI Grant Program", "Arbitrum Foundation Grant Program")
    assert not same_grant("Alchemy-Arbitrum Grant Program", "Arbitrum Trailblazer AI Grant Program")
    assert not same_grant("Gitcoin Grants — GG24 & Upcoming Rounds", "Gitcoin Grants 25 (GG25)")


def test_dedupe_keeps_arbitrum_style_hub_programs():
    rows = [
        {"id": 112, "url": "https://example.org/grants", "name": "Arbitrum Foundation Grant Program"},
        {"id": 438, "url": "https://example.org/grants", "name": "Arbitrum Audit Program"},
        {"id": 507, "url": "https://example.org/grants", "name": "Arbitrum Trailblazer AI Grant Program"},
    ]
    kept, dropped = dedupe(rows)
    assert sorted(r["id"] for r in kept) == [112, 438, 507]
    assert dropped == {}
