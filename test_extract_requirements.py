import csv
import datetime
import json
import os
import tempfile
import unittest

import extract_requirements as er

HERE = os.path.dirname(os.path.abspath(__file__))
TODAY = datetime.date(2026, 5, 1)


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


def fake(payload):
    return lambda prompt: json.dumps(payload)


def e(value, quote, conf=0.9):
    return {"value": value, "quote": quote, "confidence": conf}


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.text = fixture("page_us_org.txt")
        self.grant = {"id": 7, "name": "Acme", "funder": "Acme"}

    def test_us_only_and_org_only(self):
        llm = fake({"eligibility": {
            "geography": e("country:US", "registered US nonprofits and companies only"),
            "entityRequired": e("org", "legal entity incorporated in the\nUnited States"),
        }})
        r = er.extract(self.grant, self.text, TODAY, llm)
        self.assertEqual(r["fields"]["eligibility"]["geography"], "country:US")
        self.assertEqual(r["fields"]["eligibility"]["entityRequired"], "org")
        self.assertEqual(r["review_items"], [])
        self.assertEqual(r["fields"]["_derived"]["by"], "auto")
        self.assertEqual(r["fields"]["_derived"]["checked"], "2026-05-01")

    def test_entity_none_and_restricted_geo_and_applicant_types(self):
        llm = fake({"eligibility": {
            "geography": e("restricted:US,CA", "registered US nonprofits"),
            "entityRequired": e("none", "legal entity"),
            "applicantTypes": e(["individual", "org"], "companies only"),
        }})
        r = er.extract(self.grant, self.text, TODAY, llm)
        el = r["fields"]["eligibility"]
        self.assertEqual(el["geography"], "restricted:US,CA")
        self.assertEqual(el["entityRequired"], "none")
        self.assertEqual(el["applicantTypes"], ["individual", "org"])

    def test_applicant_type_outside_vocab_reviewed(self):
        llm = fake({"eligibility": {"applicantTypes": e(["startup"], "companies only")}})
        r = er.extract(self.grant, self.text, TODAY, llm)
        self.assertNotIn("eligibility", r["fields"])
        self.assertEqual(r["review_items"][0]["reason"], "invalid value")

    def test_old_entity_values_rejected(self):
        for v in ("individual", "either"):
            llm = fake({"eligibility": {"entityRequired": e(v, "legal entity")}})
            r = er.extract(self.grant, self.text, TODAY, llm)
            self.assertNotIn("eligibility", r["fields"])

    def test_rolling_deadline_omits_date(self):
        text = "Rolling Fund\nApplications are accepted on a rolling basis.\n"
        llm = fake({"timeline": {"deadlineDate": e("2026-12-01", "rolling basis")}})
        r = er.extract(self.grant, text, TODAY, llm)
        tl = r["fields"]["timeline"]
        self.assertEqual(tl["deadlineType"], "rolling")
        self.assertNotIn("deadlineDate", tl)

    def test_prompt_uses_organization(self):
        seen = []
        g = {"id": 1, "name": "N", "organization": "OrgCo"}
        er.extract(g, self.text, TODAY, lambda p: seen.append(p) or "{}")
        self.assertIn("OrgCo", seen[0])

    def test_prompt_caps_quote_length_and_bans_fences(self):
        self.assertIn("200", er.PROMPT)
        self.assertIn("no markdown fences", er.PROMPT)

    def test_hallucinated_quote_dropped_and_reviewed(self):
        llm = fake({"eligibility": {
            "geography": e("country:CA", "open to Canadian residents")}})
        r = er.extract(self.grant, self.text, TODAY, llm)
        self.assertNotIn("eligibility", r["fields"])
        self.assertEqual(len(r["review_items"]), 1)
        self.assertEqual(r["review_items"][0]["field"], "eligibility.geography")
        self.assertIn("quote", r["review_items"][0]["reason"])

    def test_low_confidence_goes_to_review(self):
        llm = fake({"requirements": [
            {"item": "proposal", "quote": "two-page project proposal", "confidence": 0.5},
            {"item": "budget", "quote": "and a budget", "confidence": 0.9}]})
        r = er.extract(self.grant, self.text, TODAY, llm)
        self.assertEqual([x["item"] for x in r["fields"]["requirements"]], ["budget"])
        self.assertIn("low confidence", r["review_items"][0]["reason"])

    def test_invalid_enum_reviewed(self):
        llm = fake({"eligibility": {"entityRequired": e("startup", "legal entity")}})
        r = er.extract(self.grant, self.text, TODAY, llm)
        self.assertNotIn("eligibility", r["fields"])
        self.assertEqual(r["review_items"][0]["reason"], "invalid value")

    def test_deterministic_dates_and_amounts(self):
        r = er.extract(self.grant, self.text, TODAY, fake({}))
        tl = r["fields"]["timeline"]
        self.assertEqual(tl["deadlineDate"], "2026-07-15")
        self.assertEqual(tl["opensDate"], "2026-03-01")
        self.assertEqual(tl["decisionDate"], "2026-09-01")
        self.assertEqual(r["fields"]["amountMax"], 150000)
        self.assertIsNone(r["fields"]["amountMin"])
        self.assertEqual(r["fields"]["currency"], "USD")

    def test_past_deadline_parsed(self):
        r = er.extract(self.grant, fixture("page_past_deadline.txt"), TODAY, fake({}))
        self.assertEqual(r["fields"]["timeline"]["deadlineDate"], "2026-03-01")
        self.assertEqual(r["fields"]["amountMin"], 5000)
        self.assertEqual(r["fields"]["amountMax"], 20000)

    def test_llm_failure_reviewed_not_raised(self):
        r = er.extract(self.grant, self.text, TODAY, lambda p: "not json")
        self.assertEqual(r["review_items"][0]["field"], "*")
        self.assertIn("timeline", r["fields"])

    def test_write_review_csv(self):
        items = [{"grant_id": 1, "field": "f", "value": "v", "quote": "q", "reason": "r"}]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "review", "x.csv")
            er.write_review(items, p)
            er.write_review(items, p)
            with open(p, encoding="utf-8") as f:
                rows = list(csv.reader(f))
        self.assertEqual(rows[0], er.REVIEW_HEADER)
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
