import json

import predeploy_check as pc


def _clean(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "app.js").write_text("fetch('/grants.json')")
    (tmp_path / "grants.json").write_text(json.dumps([{"name": "A", "url": "http://a"}]))
    (tmp_path / ".vercel").mkdir()
    (tmp_path / ".vercel" / "project.json").write_text("{}")
    return str(tmp_path)


def test_clean_passes(tmp_path):
    assert pc.check(_clean(tmp_path)) == []
    assert pc.main([str(tmp_path)]) == 0


def test_planted_files_fail(tmp_path):
    d = _clean(tmp_path)
    for name in (".env", "x.db", "x.py"):
        (tmp_path / name).write_text("x")
        assert pc.check(d), name
        (tmp_path / name).unlink()
    assert pc.check(d) == []


def test_token_in_content_fails(tmp_path):
    d = _clean(tmp_path)
    (tmp_path / "app.js").write_text("var k='sk-ant-abc'")
    assert any("sk-ant-" in p for p in pc.check(d))
    assert pc.main([d]) == 1


def test_missing_required(tmp_path):
    d = _clean(tmp_path)
    (tmp_path / "index.html").unlink()
    assert any("index.html" in p for p in pc.check(d))


def test_bad_grants(tmp_path):
    d = _clean(tmp_path)
    g = tmp_path / "grants.json"
    for bad in ("[]", "{}", "nope", json.dumps([{"name": "A"}])):
        g.write_text(bad)
        assert pc.check(d), bad


def test_mojibake_threshold(tmp_path):
    d = _clean(tmp_path)
    g = tmp_path / "grants.json"
    row = {"name": "A â€”", "url": "u"}
    g.write_text(json.dumps([row] * 5))
    assert pc.check(d) == []
    g.write_text(json.dumps([row] * 6))
    assert pc.check(d)


def test_telegram_word_ok_but_bot_token_fails(tmp_path):
    d = _clean(tmp_path)
    g = tmp_path / "grants.json"
    g.write_text(json.dumps([{"name": "TON Telegram grants", "url": "u"}]))
    assert pc.check(d) == []
    (tmp_path / "app.js").write_text("TELEGRAM_BOT_TOKEN=123")
    assert any("TELEGRAM_BOT_TOKEN" in p for p in pc.check(d))
