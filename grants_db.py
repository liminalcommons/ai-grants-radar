#!/usr/bin/env python3
"""SQLite store for grants (stdlib only). grants.json becomes an export of this DB.

    python grants_db.py import [grants.json] [--db data/grants.db]
    python grants_db.py export [grants.json] [--db data/grants.db] [--with-keys]
    python grants_db.py stats  [--db data/grants.db]

Field contract: see "Plan: Grants website rebuild". Notes on the choices made here:

* ``eligibility`` stays the legacy prose string (index.html renders it). The
  structured contract object {geography, entityRequired, applicantTypes,
  restrictions} is stored/exported as ``eligibilityDetail``. upsert() routes a
  dict passed as ``eligibility`` to that column.
* dedupeKey = normalised URL (lowercase host, no query/fragment/trailing slash),
  falling back to the normalised name. Several real, distinct programs share one
  landing page (26 URLs in grants.json), so a URL collision with a *different*
  name never drops a row: the key becomes ``<urlKey>|<nameKey>``. Rows with the
  same URL *and* the same normalised name merge. ``duplicate_groups()`` reports
  the shared-URL groups.
* Each row remembers the key order it was imported with (``key_order``), so the
  export is byte-identical to the file it came from. New contract fields are
  only emitted when set, and dedupeKey only with ``with_keys=True``.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "data", "grants.db")
DEFAULT_JSON = os.path.join(HERE, "grants.json")
SCHEMA_VERSION = 1

# Legacy fields stored as plain TEXT (str or null).
TEXT_FIELDS = [
    "name", "organization", "category", "amount", "deadline", "deadlineDate",
    "eligibility", "description", "url", "viability", "viabilityNote",
    "relevant2026Note", "_updated", "fundingType", "effort", "domain",
    "deadlineStatus", "deadlineType",
]
# Fields stored as JSON text. relevant2026 is bool in most rows, str in some.
JSON_FIELDS = [
    "tags", "audience", "relevant2026",
    "eligibilityDetail", "requirements", "timeline", "page", "_derived",
]
NUM_FIELDS = ["amountMin", "amountMax"]
NEW_TEXT_FIELDS = ["currency"]
# Order used for rows that have no remembered key order (new records).
CANONICAL_ORDER = [
    "id", "name", "organization", "category", "amount", "deadline",
    "deadlineDate", "eligibility", "description", "url", "tags", "viability",
    "viabilityNote", "relevant2026", "relevant2026Note", "_updated",
    "audience", "fundingType", "effort", "domain", "deadlineStatus",
    "deadlineType", "amountMin", "amountMax", "currency", "eligibilityDetail",
    "requirements", "timeline", "page", "_derived",
]
KNOWN = set(CANONICAL_ORDER)
HUMAN = "human"


# --------------------------------------------------------------- keys

def normalise_url(url):
    if not url or not isinstance(url, str):
        return ""
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    p = urlsplit(u)
    host = p.netloc.lower()
    return host + p.path.rstrip("/")


def normalise_name(name):
    return re.sub(r"\W+", " ", (name or "").lower()).strip()


def keys_for(record):
    """(urlKey, nameKey). urlKey falls back to nameKey when there is no URL."""
    nk = normalise_name(record.get("name"))
    return normalise_url(record.get("url")) or nk, nk


# --------------------------------------------------------------- schema

def connect(db_path=DEFAULT_DB):
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return conn


def _q(col):
    return '"%s"' % col


def _grants_ddl():
    cols = ["id INTEGER PRIMARY KEY", "dedupeKey TEXT NOT NULL UNIQUE",
            "urlKey TEXT NOT NULL", "nameKey TEXT NOT NULL"]
    cols += [_q(c) + " TEXT" for c in TEXT_FIELDS]
    cols += [_q(c) + " TEXT" for c in JSON_FIELDS]
    cols += [_q(c) + " REAL" for c in NUM_FIELDS]
    cols += [_q(c) + " TEXT" for c in NEW_TEXT_FIELDS]
    cols += ["extra TEXT", "key_order TEXT"]
    return "CREATE TABLE IF NOT EXISTS grants (%s)" % ", ".join(cols)


MIGRATIONS = {
    1: [
        _grants_ddl(),
        "CREATE INDEX IF NOT EXISTS idx_grants_urlkey ON grants(urlKey)",
        """CREATE TABLE IF NOT EXISTS sources (
               id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE,
               kind TEXT, last_run TEXT)""",
        """CREATE TABLE IF NOT EXISTS page_snapshots (
               id INTEGER PRIMARY KEY,
               grant_id INTEGER NOT NULL REFERENCES grants(id),
               fetched_at TEXT NOT NULL, content_hash TEXT, text TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_snap_grant ON page_snapshots(grant_id, fetched_at)",
    ],
}


def migrate(conn):
    """Idempotent: applies any migrations above the stored schema_version."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] or 0
    for v in sorted(MIGRATIONS):
        if v > current:
            for stmt in MIGRATIONS[v]:
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (v,))
    conn.commit()
    return max(MIGRATIONS)


# --------------------------------------------------------------- row <-> record

def _dumps(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _record_to_row(rec):
    """Split a grants.json-style dict into column values (None = NULL)."""
    rec = dict(rec)
    row, extra = {}, {}
    if isinstance(rec.get("eligibility"), dict):
        rec.setdefault("eligibilityDetail", rec["eligibility"])
        rec["eligibility"] = None
    for k, v in rec.items():
        if k == "id" or k == "dedupeKey":
            continue
        if k in JSON_FIELDS:
            row[k] = None if v is None else _dumps(v)
        elif k in TEXT_FIELDS or k in NEW_TEXT_FIELDS:
            if v is None or isinstance(v, str):
                row[k] = v
            else:
                extra[k] = v          # unexpected type: keep it verbatim
        elif k in NUM_FIELDS:
            if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
                row[k] = v
            else:
                extra[k] = v
        else:
            extra[k] = v
    return row, extra


def _row_to_record(row, with_keys=False):
    present = json.loads(row["key_order"]) if row["key_order"] else []
    vals = {"id": row["id"]}
    extra = json.loads(row["extra"]) if row["extra"] else {}
    for c in TEXT_FIELDS + NEW_TEXT_FIELDS:
        vals[c] = row[c]
    for c in JSON_FIELDS:
        vals[c] = None if row[c] is None else json.loads(row[c])
    for c in NUM_FIELDS:
        v = row[c]
        vals[c] = int(v) if isinstance(v, float) and v.is_integer() else v
    vals.update(extra)
    out = {}
    for k in present:
        if k in vals:
            out[k] = vals[k]
    # New contract fields appear only once set; never as noise nulls.
    for k in CANONICAL_ORDER:
        if k not in out and vals.get(k) is not None:
            out[k] = vals[k]
    for k in vals:
        if k not in out and k not in KNOWN:
            out[k] = vals[k]
    if with_keys:
        out["dedupeKey"] = row["dedupeKey"]
    return out


def _key_order(rec):
    return [k for k in rec if k not in ("dedupeKey",)]


# --------------------------------------------------------------- write

def _find(conn, urlkey, namekey):
    """Existing row for this (urlKey, nameKey), or None."""
    rows = conn.execute("SELECT * FROM grants WHERE urlKey=?", (urlkey,)).fetchall()
    for r in rows:
        if r["nameKey"] == namekey:
            return r
    return None


def _free_key(conn, urlkey, namekey):
    taken = conn.execute("SELECT 1 FROM grants WHERE dedupeKey=?", (urlkey,)).fetchone()
    return urlkey if not taken else urlkey + "|" + namekey


def _is_empty(v):
    return v is None or v == "" or v == [] or v == {}


def _insert(conn, rec):
    urlkey, namekey = keys_for(rec)
    if not urlkey:
        raise ValueError("record needs a url or a name")
    row, extra = _record_to_row(rec)
    row["urlKey"], row["nameKey"] = urlkey, namekey
    row["dedupeKey"] = _free_key(conn, urlkey, namekey)
    row["extra"] = _dumps(extra) if extra else None
    row["key_order"] = _dumps(_key_order(rec))
    gid = rec.get("id")
    if gid is None or conn.execute("SELECT 1 FROM grants WHERE id=?", (gid,)).fetchone():
        gid = (conn.execute("SELECT MAX(id) FROM grants").fetchone()[0] or 0) + 1
    row["id"] = gid
    cols = list(row)
    conn.execute("INSERT INTO grants (%s) VALUES (%s)" % (
        ",".join(_q(c) for c in cols), ",".join("?" * len(cols))), [row[c] for c in cols])
    return gid


def upsert(conn, record):
    """Insert or merge on dedupeKey. Returns (id, 'inserted'|'updated').

    Merge rules: missing/empty incoming values never erase data. If the stored
    row is human-curated (_derived.by == "human") an auto record only fills
    empty fields and never overwrites. A human record overwrites everything.
    """
    urlkey, namekey = keys_for(record)
    existing = _find(conn, urlkey, namekey)
    if existing is None:
        gid = _insert(conn, record)
        conn.commit()
        return gid, "inserted"

    cur = _row_to_record(existing)
    cur_human = (cur.get("_derived") or {}).get("by") == HUMAN
    inc_human = (record.get("_derived") or {}).get("by") == HUMAN
    protect = cur_human and not inc_human

    inc = dict(record)
    if isinstance(inc.get("eligibility"), dict):
        inc.setdefault("eligibilityDetail", inc["eligibility"])
        del inc["eligibility"]
    merged = dict(cur)
    for k, v in inc.items():
        if k in ("id", "dedupeKey") or _is_empty(v):
            continue
        if protect and not _is_empty(cur.get(k)):
            continue
        merged[k] = v
    if protect:
        merged["_derived"] = cur["_derived"]
    merged["id"] = existing["id"]

    row, extra = _record_to_row(merged)
    row["extra"] = _dumps(extra) if extra else None
    row["key_order"] = _dumps(_key_order(merged))
    # A cleared column must go back to NULL, so write every data column.
    sets = [c for c in TEXT_FIELDS + JSON_FIELDS + NUM_FIELDS + NEW_TEXT_FIELDS]
    vals = [row.get(c) for c in sets] + [row["extra"], row["key_order"], existing["id"]]
    conn.execute("UPDATE grants SET %s, extra=?, key_order=? WHERE id=?" %
                 ",".join(_q(c) + "=?" for c in sets), vals)
    conn.commit()
    return existing["id"], "updated"


# --------------------------------------------------------------- import / export

def import_json(path, conn=None, db_path=DEFAULT_DB):
    """Load grants.json into the DB (upsert per row). Returns a summary dict."""
    own = conn is None
    conn = conn or connect(db_path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("grants.json must be a list of objects")
    ins = upd = 0
    for rec in data:
        _, how = upsert(conn, rec)
        ins += how == "inserted"
        upd += how == "updated"
    out = {"rows": len(data), "inserted": ins, "updated": upd,
           "duplicate_groups": duplicate_groups(conn)}
    if own:
        conn.close()
    return out


def export_records(conn, with_keys=False):
    rows = conn.execute("SELECT * FROM grants ORDER BY id").fetchall()
    return [_row_to_record(r, with_keys) for r in rows]


def export_json(path, conn=None, db_path=DEFAULT_DB, with_keys=False):
    """Write grants.json: sorted by id, indent=2, UTF-8, trailing newline."""
    own = conn is None
    conn = conn or connect(db_path)
    recs = export_records(conn, with_keys)
    text = json.dumps(recs, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if own:
        conn.close()
    return len(recs)


def duplicate_groups(conn):
    """Groups of rows sharing a urlKey: [{urlKey, ids, names}]. Rows stay separate
    when their names differ; they merge on import only if the names match too."""
    out = []
    for r in conn.execute(
            "SELECT urlKey FROM grants GROUP BY urlKey HAVING COUNT(*)>1 ORDER BY urlKey"):
        rows = conn.execute("SELECT id, name FROM grants WHERE urlKey=? ORDER BY id",
                            (r["urlKey"],)).fetchall()
        out.append({"urlKey": r["urlKey"], "ids": [x["id"] for x in rows],
                    "names": [x["name"] for x in rows]})
    return out


def stats(conn):
    one = lambda q: conn.execute(q).fetchone()[0]
    total = one("SELECT COUNT(*) FROM grants")
    return {
        "grants": total,
        "schema_version": one("SELECT MAX(version) FROM schema_version"),
        "shared_url_groups": len(duplicate_groups(conn)),
        "with_deadlineDate": one("SELECT COUNT(*) FROM grants WHERE deadlineDate IS NOT NULL"),
        "with_eligibilityDetail": one("SELECT COUNT(*) FROM grants WHERE eligibilityDetail IS NOT NULL"),
        "with_requirements": one("SELECT COUNT(*) FROM grants WHERE requirements IS NOT NULL"),
        "with_timeline": one("SELECT COUNT(*) FROM grants WHERE timeline IS NOT NULL"),
        "with_page": one("SELECT COUNT(*) FROM grants WHERE page IS NOT NULL"),
        "human_curated": one("SELECT COUNT(*) FROM grants WHERE json_extract(_derived,'$.by')='human'"),
        "page_snapshots": one("SELECT COUNT(*) FROM page_snapshots"),
        "sources": one("SELECT COUNT(*) FROM sources"),
    }


# --------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="grants.db import/export/stats")
    ap.add_argument("cmd", choices=["import", "export", "stats"])
    ap.add_argument("path", nargs="?", default=DEFAULT_JSON)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--with-keys", action="store_true", help="export dedupeKey too")
    a = ap.parse_args(argv)
    conn = connect(a.db)
    if a.cmd == "import":
        s = import_json(a.path, conn)
        print("imported %d rows (%d new, %d merged)" % (s["rows"], s["inserted"], s["updated"]))
        print("%d groups share a URL (kept as separate rows):" % len(s["duplicate_groups"]))
        for g in s["duplicate_groups"]:
            print("  %s -> ids %s" % (g["urlKey"], g["ids"]))
    elif a.cmd == "export":
        n = export_json(a.path, conn, with_keys=a.with_keys)
        print("exported %d rows to %s" % (n, a.path))
    else:
        for k, v in stats(conn).items():
            print("%-24s %s" % (k, v))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
