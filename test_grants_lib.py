#!/usr/bin/env python3
"""Tests for grants_lib pure logic. Run: python test_grants_lib.py"""

import grants_lib as gl


def test_fix_mojibake_repairs_em_dash():
    # "Rolling program â€" actively accepting" is the corrupted form of an em dash.
    corrupted = "Rolling program â€” actively accepting"
    assert gl.fix_mojibake(corrupted) == "Rolling program — actively accepting"


def test_fix_mojibake_leaves_clean_text_untouched():
    clean = "Up to $350,000 in cloud credits — no equity"
    assert gl.fix_mojibake(clean) == clean


def test_fix_mojibake_recurses_into_dict_and_list():
    out = gl.fix_mojibake({"a": ["x â€” y"], "n": 5})
    assert out == {"a": ["x — y"], "n": 5}


def test_merge_skips_duplicate_name_case_insensitive():
    existing = [{"id": 1, "name": "Google Cloud AI Startup Program"}]
    added = gl.merge(existing, [{"name": "google cloud ai startup program"}])
    assert added == []
    assert len(existing) == 1


def test_merge_assigns_new_id_and_normalises():
    existing = [{"id": 1, "name": "A"}]
    added = gl.merge(existing, [{"name": "Brand New Grant"}])
    assert added == ["Brand New Grant"]
    new = existing[-1]
    assert new["id"] == 2
    assert new["category"] == "Corporate"   # default applied
    assert new["viability"] == "partial"    # default applied
    assert new["_updated"] == gl.TODAY


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
            passed += 1
    print(f"\n{passed} tests passed.")


def test_merge_skips_variant_title_on_same_url():
    from grants_lib import merge
    existing = [{"id": 1, "name": "Freed Fellowship Grant",
                 "url": "https://freedfellowship.com/"}]
    added = merge(existing, [{"name": "The Freed Fellowship Grant",
                              "url": "https://freedfellowship.com/?utm_source=x"}])
    assert added == []
    assert len(existing) == 1


def test_merge_keeps_distinct_hub_programs():
    from grants_lib import merge
    existing = [{"id": 1, "name": "Arbitrum Trailblazer AI Grant Program",
                 "url": "https://example.org/grants"}]
    added = merge(existing, [{"name": "Arbitrum Audit Program",
                              "url": "https://example.org/grants"}])
    assert len(added) == 1
    assert len(existing) == 2


def test_all_dates_day_first_single():
    import datetime
    assert gl._all_dates("Closes 1 Oct 2026") == [datetime.date(2026, 10, 1)]


def test_all_dates_day_first_range_no_phantom():
    # "24 Sep – 1 Oct 2026" must yield the two real dates, NOT a bare-month
    # Oct-28 phantom (which once marked a closed round as open).
    import datetime
    assert gl._all_dates("Round 3 open 24 Sep – 1 Oct 2026") == [
        datetime.date(2026, 9, 24), datetime.date(2026, 10, 1)]


def test_all_dates_day_first_range_across_new_year():
    import datetime
    assert gl._all_dates("Window 28 Dec – 5 Jan 2027") == [
        datetime.date(2026, 12, 28), datetime.date(2027, 1, 5)]
