"""Liveness audit: stamping from stub fetch results, no network. Plus the
sqlite round-trip (unknown fields must survive via `extra`)."""
import check_grants
import grants_db


def grant(id, url="https://example.org/call"):
    return {"id": id, "name": f"Grant {id}", "url": url}


def stub(results):
    return lambda urls: {u: results.get(u, {"status": "dead", "transient": True}) for u in urls}


def test_stamp_alive_dead_blocked_unknown():
    grants = [grant(1), grant(2), grant(3), grant(4)]
    tally, flagged = check_grants.run(
        grants,
        "2026-10-08",
        sync_db=False,
        fetch_fn=stub({
            "https://example.org/call": {"status": "dead", "transient": True},
            "u-alive": {"status": "ok"},
            "u-dead": {"status": "dead"},
            "u-blocked": {"status": "blocked"},
        }),
    )
    assert tally == {"alive": 0, "dead": 0, "blocked": 0, "unknown": 4}
    grants = [grant(1, "u-alive"), grant(2, "u-dead"), grant(3, "u-blocked"), grant(4, "u-x")]
    tally, flagged = check_grants.run(grants, "2026-10-08", sync_db=False, fetch_fn=stub({
        "u-alive": {"status": "ok"},
        "u-dead": {"status": "dead"},
        "u-blocked": {"status": "blocked"},
    }))
    assert tally == {"alive": 1, "dead": 1, "blocked": 1, "unknown": 1}
    assert [g["last_checked"] for g in grants] == ["2026-10-08"] * 4
    assert [g.get("check_ok") for g in grants] == [1, 0, 0, None]
    assert flagged == [2, 3]


def test_stamps_survive_sqlite_round_trip(tmp_path):
    conn = grants_db.connect(str(tmp_path / "t.db"))
    rec = {"id": 1, "name": "G", "url": "https://example.org/call",
           "last_checked": "2026-10-08", "check_ok": 1}
    grants_db.upsert(conn, rec)
    conn.commit()
    out = grants_db.export_records(conn)
    conn.close()
    assert out[0]["last_checked"] == "2026-10-08"
    assert out[0]["check_ok"] == 1
