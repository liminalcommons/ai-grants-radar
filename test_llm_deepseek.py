import os
import tempfile
import unittest

import llm_deepseek as ds


def fake_post(payload, api_key, timeout):
    assert payload["model"] == ds.MODEL
    assert payload["response_format"] == {"type": "json_object"}
    assert api_key == "test-key"
    return 200, {"choices": [{"message": {"content": "{\"a\": 1}"}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 3}}


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        os.environ["OPENCODE_GO_API_KEY"] = "test-key"
        self.ledger = os.path.join(tempfile.mkdtemp(), "spend.csv")

    def test_call_returns_text_and_logs_spend(self):
        text = ds.call_deepseek("hi", "trial/1", session_id="s",
                                post=fake_post, ledger_path=self.ledger)
        self.assertEqual(text, "{\"a\": 1}")
        with open(self.ledger, encoding="utf-8") as f:
            rows = f.read().strip().split("\n")
        self.assertEqual(len(rows), 2)  # header + 1 call
        self.assertIn("trial/1", rows[1])
        self.assertIn("deepseek-v4.1-flash", rows[1])

    def test_make_llm_tags_calls_sequentially(self):
        seen = []

        def post(payload, key, timeout):
            seen.append(payload)
            return fake_post(payload, key, timeout)

        llm = ds.make_llm("trial-extract", session_id="s",
                          post=post, ledger_path=self.ledger)
        llm("p1")
        llm("p2")
        with open(self.ledger, encoding="utf-8") as f:
            body = f.read()
        self.assertIn("trial-extract/1", body)
        self.assertIn("trial-extract/2", body)

    def test_failure_still_logs_spend_then_raises(self):
        def boom(payload, key, timeout):
            raise TimeoutError("slow")

        with self.assertRaises(RuntimeError):
            ds.call_deepseek("hi", "trial/9", post=boom, ledger_path=self.ledger)
        with open(self.ledger, encoding="utf-8") as f:
            body = f.read()
        self.assertIn("trial/9", body)
        self.assertIn("TimeoutError", body)


if __name__ == "__main__":
    unittest.main()
