"""Offline tests for grants_db. Run: python -m pytest test_grants_db.py"""
import json
import os

import pytest

import grants_db as gdb

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures", "grants_5.json")


@pytest.fixture
def conn():
    c = gdb.connect(":memory:")
    yield c
    c.close()


def test_normalise_url():
    assert gdb.normalise_url("HTTPS://Example.COM/Path/?utm=1#frag") == "example.com/Path"
    assert gdb.normalise_url("https://a.org/") == "a.org"
    assert gdb.normalise_url("") == ""


def test_dedupe_falls_back_to_name():
    assert gdb.keys_for({"name": "My  Grant!", "url": ""}) == ("my grant", "my grant")


def test_migrate_idempotent(conn):
    gdb.migrate(conn)
    gdb.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"grants", "sources", "page_snapshots", "schema_version"} <= tables


def test_roundtrip_fixture_byte_identical(conn, tmp_path):
    summary = gdb.import_json(FIXTURE, conn)
    assert summary["rows"] == 5 and summary["inserted"] == 5
    out = tmp_path / "out.json"
    gdb.export_json(str(out), conn)
    assert out.read_bytes() == open(FIXTURE, "rb").read()


def test_reimport_is_idempotent(conn):
    gdb.import_json(FIXTURE, conn)
    s = gdb.import_json(FIXTURE, conn)
    assert s["inserted"] == 0 and s["updated"] == 5
    assert conn.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 5


def test_shared_url_rows_kept_and_reported(conn):
    gdb.import_json(FIXTURE, conn)
    groups = gdb.duplicate_groups(conn)
    assert len(groups) == 1 and len(groups[0]["ids"]) == 2
    keys = [r[0] for r in conn.execute("SELECT dedupeKey FROM grants")]
    assert len(set(keys)) == 5


def test_unknown_keys_kept_in_extra(conn):
    gdb.upsert(conn, {"id": 7, "name": "X", "url": "https://x.org/", "mystery": {"a": [1]}})
    rec = gdb.export_records(conn)[0]
    assert rec["mystery"] == {"a": [1]}
    assert conn.execute("SELECT extra FROM grants").fetchone()[0] is not None


def test_export_sorted_by_id(conn, tmp_path):
    for i in (3, 1, 2):
        gdb.upsert(conn, {"id": i, "name": "n%d" % i, "url": "https://x.org/%d" % i})
    assert [r["id"] for r in gdb.export_records(conn)] == [1, 2, 3]


def test_new_fields_only_when_set_and_with_keys_flag(conn):
    gdb.upsert(conn, {"id": 1, "name": "A", "url": "https://a.org"})
    assert "timeline" not in gdb.export_records(conn)[0]
    gdb.upsert(conn, {"name": "A", "url": "https://a.org/",
                      "timeline": {"deadlineDate": "2026-12-01"}, "amountMin": 1000.0, "currency": "USD",
                      "eligibility": {"geography": ["US"]}})
    rec = gdb.export_records(conn, with_keys=True)[0]
    assert rec["timeline"]["deadlineDate"] == "2026-12-01"
    assert rec["amountMin"] == 1000 and rec["currency"] == "USD"
    assert rec["eligibilityDetail"] == {"geography": ["US"]}
    assert rec["dedupeKey"] == "a.org"


def test_upsert_merges_on_url_key(conn):
    a, how = gdb.upsert(conn, {"name": "Grant", "url": "https://X.org/g/?a=1", "amount": "$5"})
    b, how2 = gdb.upsert(conn, {"name": "grant", "url": "https://x.org/g", "description": "d"})
    assert (how, how2) == ("inserted", "updated") and a == b
    rec = gdb.export_records(conn)[0]
    assert rec["amount"] == "$5" and rec["description"] == "d"


def test_auto_never_overwrites_human_field(conn):
    gdb.upsert(conn, {"name": "G", "url": "https://g.org", "deadlineDate": "2026-11-01",
                      "_derived": {"by": "human", "checked": "2026-10-01"}})
    gdb.upsert(conn, {"name": "G", "url": "https://g.org", "deadlineDate": "2027-01-01",
                      "description": "filled by auto", "_derived": {"by": "auto"}})
    rec = gdb.export_records(conn)[0]
    assert rec["deadlineDate"] == "2026-11-01"      # human value kept
    assert rec["description"] == "filled by auto"   # empty field may be filled
    assert rec["_derived"]["by"] == "human"


def test_human_can_overwrite_auto(conn):
    gdb.upsert(conn, {"name": "G", "url": "https://g.org", "deadlineDate": "2027-01-01",
                      "_derived": {"by": "auto"}})
    gdb.upsert(conn, {"name": "G", "url": "https://g.org", "deadlineDate": "2026-11-01",
                      "_derived": {"by": "human"}})
    rec = gdb.export_records(conn)[0]
    assert rec["deadlineDate"] == "2026-11-01" and rec["_derived"]["by"] == "human"


def test_cli_import_export_stats(tmp_path, capsys):
    db = str(tmp_path / "g.db")
    out = str(tmp_path / "o.json")
    assert gdb.main(["import", FIXTURE, "--db", db]) == 0
    assert gdb.main(["export", out, "--db", db]) == 0
    assert open(out, "rb").read() == open(FIXTURE, "rb").read()
    assert gdb.main(["stats", "--db", db]) == 0
    assert "grants" in capsys.readouterr().out
