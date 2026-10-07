import datetime
import unittest

import eval_data_quality as ev

TODAY = datetime.date(2026, 10, 7)


def grant(**kw):
    g = {"id": 1, "name": "Test Grant", "organization": "Test Org",
         "category": "Foundation", "amount": "$10K", "deadline": "Rolling",
         "deadlineStatus": "rolling", "deadlineType": "rolling", "deadlineDate": None,
         "eligibility": "Open to nonprofits worldwide",
         "description": "A test grant with a long enough description to pass checks.",
         "url": "https://example-test-grant.org/apply", "viability": "yes",
         "audience": ["org"], "fundingType": "cash", "effort": "low",
         "domain": "AI"}
    g.update(kw)
    return g


class EvalTests(unittest.TestCase):
    def test_clean_grant_scores_100(self):
        r = ev.evaluate([grant()], TODAY)
        self.assertEqual(r["score"], 100.0)
        self.assertEqual(r["totals"]["FAIL"], 0)

    def test_missing_field_fails_schema(self):
        r = ev.evaluate([grant(amount="")], TODAY)
        self.assertEqual(r["checks"]["schema"]["passed"], 0)
        self.assertTrue(any(i["check"] == "schema" and i["level"] == "FAIL"
                            for i in r["issues"]))

    def test_stale_stored_status_fails_deadline(self):
        # stored open but the date passed relative to TODAY
        r = ev.evaluate([grant(deadline="Closes May 1, 2026",
                               deadlineStatus="open", deadlineType="fixed",
                               deadlineDate="2026-05-01")], TODAY)
        self.assertTrue(any(i["check"] == "deadline_consistency" and i["level"] == "FAIL"
                            for i in r["issues"]))

    def test_true_dupe_fails_dedupe(self):
        g1, g2 = grant(id=1), grant(id=2)
        r = ev.evaluate([g1, g2], TODAY)
        self.assertEqual(r["checks"]["dedupe"]["true_dupe_groups"], 1)
        self.assertTrue(any(i["check"] == "dedupe" and i["level"] == "FAIL"
                            for i in r["issues"]))

    def test_hub_variants_warn_only(self):
        g1 = grant(id=1, name="Program A")
        g2 = grant(id=2, name="Program B")
        r = ev.evaluate([g1, g2], TODAY)
        self.assertEqual(r["checks"]["dedupe"]["hub_variant_groups"], 1)
        self.assertFalse(any(i["level"] == "FAIL" for i in r["issues"]))

    def test_bad_url_fails(self):
        r = ev.evaluate([grant(url="not a url")], TODAY)
        self.assertTrue(any(i["check"] == "url_health" and i["level"] == "FAIL"
                            for i in r["issues"]))

    def test_placeholder_host_fails(self):
        r = ev.evaluate([grant(url="https://example.com/apply")], TODAY)
        self.assertTrue(any(i["check"] == "url_health" and i["level"] == "FAIL"
                            for i in r["issues"]))

    def test_short_content_fails(self):
        r = ev.evaluate([grant(eligibility="x", description="short")], TODAY)
        self.assertTrue(any(i["check"] == "content_quality" and i["level"] == "FAIL"
                            for i in r["issues"]))

    def test_unknown_status_is_info_not_fail(self):
        r = ev.evaluate([grant(deadline="Check program page",
                               deadlineStatus="unknown", deadlineType="unknown",
                               deadlineDate=None)], TODAY)
        self.assertFalse(any(i["level"] == "FAIL" for i in r["issues"]))
        self.assertTrue(any(i["level"] == "INFO" for i in r["issues"]))


if __name__ == "__main__":
    unittest.main()
