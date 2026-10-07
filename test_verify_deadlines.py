"""Tests for verify-deadlines.py: status is a pure projection of deadline fields."""

import datetime

import grants_lib as gl

TODAY = datetime.date(2026, 10, 7)


def test_expired_past_fixed_date():
    d = gl.derive_deadline({"deadlineDate": "2026-09-01", "deadlineType": "fixed"}, TODAY)
    assert d["deadlineStatus"] == "expired"


def test_upcoming_future_fixed_date():
    d = gl.derive_deadline({"deadlineDate": "2026-12-01", "deadlineType": "fixed"}, TODAY)
    assert d["deadlineStatus"] in ("open", "upcoming")


def test_rolling_stays_rolling():
    d = gl.derive_deadline({"deadline": "Applications accepted on a rolling basis", "deadlineDate": ""}, TODAY)
    assert d["deadlineStatus"] == "rolling"


def test_missing_date_is_unknown():
    d = gl.derive_deadline({"deadlineDate": "", "deadlineType": ""}, TODAY)
    assert d["deadlineStatus"] == "unknown"


def test_rerun_is_idempotent():
    g = {"deadlineDate": "2026-09-01", "deadlineType": "fixed"}
    once = gl.derive_deadline(dict(g), TODAY)
    g.update(once)
    twice = gl.derive_deadline(dict(g), TODAY)
    assert once == twice
