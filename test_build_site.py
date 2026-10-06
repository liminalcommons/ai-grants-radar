import json
import os
from unittest import mock

import build_site
import grants_lib


def _src(tmp_path, classic=True):
    s = tmp_path / "src"
    (s / "site").mkdir(parents=True)
    for n in ("index.html", "app.js", "filters.js", "style.css",
              "filters.test.mjs", "package.json", "notes.md", "x.py"):
        (s / "site" / n).write_text("x")
    if classic:
        (s / "classic").mkdir()
        (s / "classic" / "index.html").write_text("c")
        (s / "classic" / "secret.env").write_text("s")
    (s / "grants.json").write_text("[]")
    (s / "report.html").write_text("r")
    (s / "vercel.json").write_text(json.dumps({}))
    (s / ".env").write_text("TOKEN=1")
    (s / "a.db").write_text("d")
    (s / "README.md").write_text("m")
    (s / "weekly.py").write_text("p")
    (s / ".vercel").mkdir()
    (s / ".vercel" / "project.json").write_text("{}")
    return s


def _files(out):
    return {os.path.relpath(os.path.join(r, f), out).replace(os.sep, "/")
            for r, _, fs in os.walk(out) for f in fs}


def test_layout(tmp_path):
    s = _src(tmp_path)
    out = build_site.build(str(tmp_path / "public"), src=str(s))
    assert _files(out) == {
        "index.html", "app.js", "filters.js", "style.css",
        "classic/index.html", "grants.json", "report.html", "vercel.json",
        ".vercel/project.json",
    }


def test_no_classic_ok(tmp_path):
    s = _src(tmp_path, classic=False)
    out = build_site.build(str(tmp_path / "public"), src=str(s))
    assert "classic/index.html" not in _files(out)


def test_forbidden_types(tmp_path):
    s = _src(tmp_path)
    out = build_site.build(str(tmp_path / "public"), src=str(s))
    for f in _files(out):
        assert not f.endswith((".py", ".db", ".env", ".md", ".test.mjs"))


def test_idempotent_and_wipes(tmp_path):
    s = _src(tmp_path)
    o = str(tmp_path / "public")
    build_site.build(o, src=str(s))
    (tmp_path / "public" / "stale.html").write_text("old")
    a = build_site.build(o, src=str(s))
    first = _files(a)
    assert "stale.html" not in first
    assert _files(build_site.build(o, src=str(s))) == first


def test_deploy_builds_then_runs_vercel():
    calls = []
    with mock.patch.object(build_site, "build",
                           side_effect=lambda *a, **k: calls.append("build") or "/p"), \
         mock.patch.object(grants_lib.subprocess, "run",
                           side_effect=lambda *a, **k: calls.append((a, k))) as run:
        grants_lib.deploy()
    assert calls[0] == "build"
    args, kw = calls[1]
    assert "vercel --prod --yes" in args[0]
    assert kw["cwd"] == "/p"
    assert run.call_count == 1
