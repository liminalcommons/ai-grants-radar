"""Assemble a clean public/ dir for deployment.

Only allowlisted file types are ever copied, so secrets, databases, scripts
and docs can never be uploaded. deploy() ships public/ and nothing else.
"""

import os
import shutil

DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWED_EXT = {".html", ".css", ".js", ".json", ".ics", ".png", ".svg", ".ico"}
SKIP_NAMES = {"package.json"}


def _allowed(name):
    if name in SKIP_NAMES or name.endswith(".test.mjs"):
        return False
    return os.path.splitext(name)[1].lower() in ALLOWED_EXT


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def _copy_tree(src_dir, dst_dir):
    for root, _dirs, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        for name in files:
            if _allowed(name):
                _copy(os.path.join(root, name),
                      os.path.normpath(os.path.join(dst_dir, rel, name)))


def build(out="public", src=DIR):
    """Wipe and rebuild `out` from `src`. Returns the absolute out path."""
    if not os.path.isabs(out):
        out = os.path.join(src, out)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    site = os.path.join(src, "site")
    if os.path.isdir(site):
        for name in os.listdir(site):
            p = os.path.join(site, name)
            if os.path.isfile(p) and _allowed(name):
                _copy(p, os.path.join(out, name))

    classic = os.path.join(src, "classic")
    if os.path.isdir(classic):
        _copy_tree(classic, os.path.join(out, "classic"))

    for name in ("grants.json", "report.html", "vercel.json"):
        p = os.path.join(src, name)
        if os.path.isfile(p):
            _copy(p, os.path.join(out, name))

    proj = os.path.join(src, ".vercel", "project.json")
    if os.path.isfile(proj):
        _copy(proj, os.path.join(out, ".vercel", "project.json"))
    return out


if __name__ == "__main__":
    print(build())
