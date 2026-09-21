import json
import unittest

from processing.issue_extraction import (
    detect_issue_labels,
    normalize_issue_labels,
    parse_llm_issue_results,
)


class IssueTaxonomyTests(unittest.TestCase):
    def test_detects_each_specific_category(self) -> None:
        examples = {
            "network_quality": "The 5G signal is slow and coverage keeps dropping.",
            "pricing_promotions": "The promotion gives a cheap monthly price and cashback.",
            "mobile_plans": "This SIM-only plan includes 100GB and unlimited SMS.",
            "roaming": "My roaming data did not work in Malaysia.",
            "porting": "My number transfer and port-in request failed.",
            "customer_service": "The hotline support agent did not resolve my complaint.",
            "billing_payment": "I was charged twice and am waiting for a refund.",
            "app_account": "The app login rejects my OTP and account password.",
            "devices": "The router and ONR equipment keep restarting.",
        }
        for expected, text in examples.items():
            with self.subTest(expected=expected):
                self.assertIn(expected, detect_issue_labels(text))

    def test_uses_general_discussion_as_fallback_only(self) -> None:
        self.assertEqual(
            detect_issue_labels("What does everyone think about this telco news?"),
            ["general_discussion"],
        )
        self.assertNotIn(
            "general_discussion",
            detect_issue_labels("The network coverage is poor."),
        )

    def test_drops_general_discussion_when_specific_labels_exist(self) -> None:
        self.assertEqual(
            normalize_issue_labels(["network_quality", "general_discussion"]),
            ["network_quality"],
        )

    def test_parses_batched_issue_json(self) -> None:
        raw = json.dumps(
            {
                "results": [
                    {"sample_id": "c:1", "issues": ["billing_payment", "app_account"]}
                ]
            }
        )
        parsed = parse_llm_issue_results(raw, {"c:1"})
        self.assertEqual(parsed["c:1"], ["billing_payment", "app_account"])


if __name__ == "__main__":
    unittest.main()
