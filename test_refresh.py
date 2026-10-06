import datetime
import json
import os
import tempfile
import unittest

import grants_db as gdb
import refresh
from scrape import content_hash, html_to_text

TODAY = datetime.date(2026, 10, 5)
OLD = "2026-08-01"   # well past STALE_DAYS

PAGE_CHANGED = ("<html><body><h1>Alpha Fund</h1><p>Open to companies worldwide.</p>"
                "<p>Applicants must be a registered company.</p></body></html>")
PAGE_SAME = "<html><body><h1>Beta Prize</h1><p>Rolling applications.</p></body></html>"


def llm_payload():
    q = "Applicants must be a registered company."
    return {"eligibility": {"entityRequired": {"value": "company", "quote": q, "confidence": 0.95}},
            "requirements": [{"item": "Registered company", "quote": q, "confidence": 0.9}]}


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.json_path = os.path.join(self.tmp.name, "grants.json")
        self.review = os.path.join(self.tmp.name, "review.csv")
        self.conn = gdb.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.llm_calls = []

    def llm(self, prompt):
        self.llm_calls.append(prompt)
        return json.dumps(llm_payload())

    def add(self, **kw):
        rec = {"name": "G", "url": "https://x.test/", "deadline": "Rolling", **kw}
        return gdb.upsert(self.conn, rec)[0]

    def run_refresh(self, pages, **kw):
        def fake_fetch(urls):
            return {u: pages.get(u, {"status": "dead", "http_code": 404, "html": ""})
                    for u in urls}
        kw.setdefault("llm", self.llm)
        return refresh.run(self.conn, today=TODAY, fetch_fn=fake_fetch, review_path=self.review,
                           json_path=self.json_path, **kw)

    def get(self, gid):
        return next(r for r in gdb.export_records(self.conn) if r["id"] == gid)


class EndToEnd(Env):
    def test_changed_dead_unchanged(self):
        same_hash = content_hash(html_to_text(PAGE_SAME))
        a = self.add(name="Alpha Fund", url="https://a.test/",
                     page={"status": "ok", "lastChecked": OLD, "contentHash": "stale-hash"})
        b = self.add(name="Beta Prize", url="https://b.test/",
                     page={"status": "ok", "lastChecked": OLD, "contentHash": same_hash})
        c = self.add(name="Gamma Grant", url="https://c.test/",
                     page={"status": "ok", "lastChecked": OLD, "contentHash": "h"})
        pages = {"https://a.test/": {"status": "ok", "html": PAGE_CHANGED},
                 "https://b.test/": {"status": "ok", "html": PAGE_SAME}}  # c -> dead
        s = self.run_refresh(pages)

        self.assertEqual((s["fetched"], s["changed"], s["dead"], s["blocked"]), (2, 1, 1, 0))
        self.assertEqual(s["extracted"], 1)
        self.assertEqual(len(self.llm_calls), 1)            # unchanged page not re-extracted
        self.assertIn("Alpha Fund", self.llm_calls[0])

        ra, rb, rc = self.get(a), self.get(b), self.get(c)
        self.assertEqual(ra["eligibilityDetail"]["entityRequired"], "company")
        self.assertEqual(ra["requirements"][0]["item"], "Registered company")
        self.assertEqual(ra["page"]["lastChecked"], TODAY.isoformat())
        self.assertNotEqual(ra["page"]["contentHash"], "stale-hash")
        self.assertNotIn("requirements", rb)
        self.assertEqual(rb["page"], {"status": "ok", "lastChecked": TODAY.isoformat(),
                                      "contentHash": same_hash})
        self.assertEqual(rc["page"]["status"], "dead")
        self.assertEqual(rc["page"]["contentHash"], "h")     # last good hash kept

        with open(self.json_path, encoding="utf-8") as f:
            exported = json.load(f)
        self.assertEqual([g["id"] for g in exported], sorted([a, b, c]))
        self.assertEqual(refresh.summary_line(s).count("/"), 7)

    def test_second_run_is_idle(self):
        self.add(name="Beta Prize", url="https://b.test/")
        pages = {"https://b.test/": {"status": "ok", "html": PAGE_SAME}}
        self.run_refresh(pages)
        s = self.run_refresh(pages)           # now fresh: nothing due
        self.assertEqual((s["selected"], s["fetched"]), (0, 0))
        self.assertEqual(len(self.llm_calls), 1)


class Budget(Env):
    def test_max_extract_defers_and_next_run_catches_up(self):
        a = self.add(name="Alpha Fund", url="https://a.test/")
        b = self.add(name="Beta Prize", url="https://b.test/")
        pages = {"https://a.test/": {"status": "ok", "html": PAGE_CHANGED},
                 "https://b.test/": {"status": "ok", "html": PAGE_SAME}}
        s = self.run_refresh(pages, max_extract=1)
        self.assertEqual((s["extracted"], s["deferred"], s["fetched"]), (1, 1, 2))
        self.assertEqual(len(self.llm_calls), 1)
        self.assertIn("deferred 1", refresh.summary_line(s))
        rows = [self.get(a), self.get(b)]
        done = [r for r in rows if "requirements" in r or "eligibilityDetail" in r]
        left = [r for r in rows if r not in done]
        self.assertEqual((len(done), len(left)), (1, 1))
        self.assertNotIn("contentHash", left[0]["page"])    # old (absent) hash kept
        self.assertEqual(left[0]["page"]["status"], "ok")
        self.assertNotIn("lastChecked", left[0]["page"])    # still due
        s2 = self.run_refresh(pages, max_extract=1)
        self.assertEqual((s2["extracted"], s2["deferred"], s2["selected"]), (1, 0, 1))
        self.assertEqual(len(self.llm_calls), 2)

    def test_deferred_keeps_old_hash(self):
        gid = self.add(name="Alpha Fund", url="https://a.test/",
                       page={"status": "ok", "lastChecked": OLD, "contentHash": "old"})
        s = self.run_refresh({"https://a.test/": {"status": "ok", "html": PAGE_CHANGED}},
                             max_extract=0)
        self.assertEqual((s["extracted"], s["deferred"]), (0, 1))
        self.assertEqual(self.get(gid)["page"]["contentHash"], "old")
        self.assertEqual(self.get(gid)["page"]["lastChecked"], OLD)

    def test_candidates_use_budget_first(self):
        old = self.add(name="Alpha Fund", url="https://a.test/")
        cands = refresh.prepare_candidates(
            self.conn, [{"name": "New One", "url": "https://n.test/", "deadline": "Rolling"}], TODAY)
        pages = {"https://a.test/": {"status": "ok", "html": PAGE_CHANGED},
                 "https://n.test/": {"status": "ok", "html": PAGE_CHANGED}}
        s = self.run_refresh(pages, candidates=cands, max_extract=1)
        self.assertEqual((s["extracted"], s["deferred"]), (1, 1))
        self.assertIn("New One", self.llm_calls[0])
        self.assertNotIn("eligibilityDetail", self.get(old))


class Selection(Env):
    def test_is_due(self):
        fresh = {"status": "ok", "lastChecked": "2026-10-01"}
        self.assertEqual(refresh.is_due({}, TODAY), "never fetched")
        self.assertEqual(refresh.is_due({"page": {"status": "ok", "lastChecked": OLD}}, TODAY), "stale")
        self.assertIsNone(refresh.is_due({"page": fresh}, TODAY))
        self.assertEqual(refresh.is_due({"page": fresh, "deadlineDate": "2026-10-20"}, TODAY),
                         "deadline soon")
        self.assertIsNone(refresh.is_due({"page": fresh, "deadlineDate": "2027-03-01"}, TODAY))
        self.assertIsNone(refresh.is_due({"page": fresh, "deadlineDate": "2026-09-01"}, TODAY))

    def test_limit_and_ids(self):
        ids = [self.add(name=f"G{i}", url=f"https://g{i}.test/") for i in range(4)]
        self.assertEqual(self.run_refresh({}, limit=2, no_extract=True)["selected"], 2)
        s = self.run_refresh({}, ids=[ids[3]], no_extract=True)
        self.assertEqual(s["selected"], 1)


class Flags(Env):
    def setUp(self):
        super().setUp()
        self.gid = self.add(name="Alpha Fund", url="https://a.test/")
        self.pages = {"https://a.test/": {"status": "ok", "html": PAGE_CHANGED}}

    def test_no_extract(self):
        s = self.run_refresh(self.pages, no_extract=True)
        self.assertEqual((s["changed"], s["extracted"]), (1, 0))
        self.assertEqual(self.llm_calls, [])
        self.assertEqual(self.get(self.gid)["page"]["status"], "ok")

    def test_dry_run_writes_nothing(self):
        s = self.run_refresh(self.pages, dry_run=True)
        self.assertEqual(s["extracted"], 1)
        self.assertNotIn("page", self.get(self.gid))
        self.assertFalse(os.path.exists(self.json_path))
        self.assertFalse(os.path.exists(self.review))

    def test_blocked_and_redirect(self):
        self.pages = {"https://a.test/": {"status": "blocked", "html": ""}}
        s = self.run_refresh(self.pages)
        self.assertEqual((s["blocked"], s["extracted"]), (1, 0))
        self.assertEqual(self.get(self.gid)["page"]["status"], "blocked")

    def test_transient_failure_leaves_row(self):
        s = self.run_refresh({"https://a.test/": {"status": "dead", "transient": True}})
        self.assertEqual((s["transient"], s["dead"]), (1, 0))
        self.assertNotIn("page", self.get(self.gid))


class Deadlines(Env):
    def test_expired_rederived_and_counted(self):
        gid = self.add(name="Old", url="https://o.test/", deadline="2026-09-01",
                       deadlineDate="2026-09-01", deadlineStatus="open", deadlineType="fixed",
                       page={"status": "ok", "lastChecked": "2026-10-04"})
        s = self.run_refresh({})
        self.assertEqual(s["expired"], 1)
        self.assertEqual(self.get(gid)["deadlineStatus"], "expired")
        self.assertEqual(self.run_refresh({})["expired"], 0)   # only newly expired count


class Candidates(Env):
    def test_candidate_scraped_and_extracted_before_insert(self):
        finds = [{"name": "Alpha Fund", "url": "https://a.test/", "deadline": "Rolling"},
                 {"name": "Ghost", "url": "https://ghost.test/", "deadline": "Rolling"}]
        self.add(name="Existing", url="https://e.test/", page={"status": "ok", "lastChecked": "2026-10-04"})
        cands = refresh.prepare_candidates(self.conn, finds + [dict(finds[0])], TODAY)
        self.assertEqual(len(cands), 2)   # in-batch duplicate dropped
        pages = {"https://a.test/": {"status": "ok", "html": PAGE_CHANGED}}
        s = self.run_refresh(pages, candidates=cands, candidates_only=True)
        self.assertEqual((s["added"], s["rejected"], s["extracted"]), (1, 1, 1))
        names = [r["name"] for r in gdb.export_records(self.conn)]
        self.assertIn("Alpha Fund", names)
        self.assertNotIn("Ghost", names)
        row = next(r for r in gdb.export_records(self.conn) if r["name"] == "Alpha Fund")
        self.assertEqual(row["eligibilityDetail"]["entityRequired"], "company")

    def test_existing_find_is_skipped(self):
        self.add(name="Alpha Fund", url="https://a.test/")
        self.assertEqual(refresh.prepare_candidates(
            self.conn, [{"name": "Alpha Fund", "url": "https://a.test/"}], TODAY), [])


if __name__ == "__main__":
    unittest.main()
