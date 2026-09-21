import json
import unittest

from models.llm_evaluation import (
    classification_metrics,
    cost_summary,
    multilabel_metrics,
    normalize_issues,
    normalize_sentiment,
    parse_llm_results,
)


class NormalizationTests(unittest.TestCase):
    def test_normalizes_sentiment_aliases(self) -> None:
        self.assertEqual(normalize_sentiment("not happy"), "not_happy")
        self.assertEqual(normalize_sentiment("positive"), "happy")
        self.assertEqual(normalize_sentiment("mixed"), "neutral")

    def test_normalizes_issue_aliases(self) -> None:
        self.assertEqual(
            normalize_issues(
                "Pricing & Promotions, Customer Service, General Discussion"
            ),
            ["pricing_promotions", "customer_service"],
        )
        self.assertEqual(
            normalize_issues("Network outage & connectivity"),
            ["network_quality"],
        )
        self.assertEqual(
            normalize_issues("Mobile plans & pricing"),
            ["mobile_plans", "pricing_promotions"],
        )


class MetricsTests(unittest.TestCase):
    def test_classification_metrics(self) -> None:
        metrics = classification_metrics(
            ["happy", "not_happy", "neutral"],
            ["happy", "neutral", "neutral"],
            ["happy", "not_happy", "neutral"],
        )
        self.assertAlmostEqual(metrics["accuracy"], 2 / 3)
        self.assertEqual(
            metrics["confusion_matrix"],
            [[1, 0, 0], [0, 0, 1], [0, 0, 1]],
        )

    def test_multilabel_metrics(self) -> None:
        metrics = multilabel_metrics(
            [["pricing_promotions", "network_quality"], ["roaming"]],
            [["pricing_promotions"], ["roaming"]],
            ["pricing_promotions", "network_quality", "roaming"],
        )
        self.assertAlmostEqual(metrics["exact_match_accuracy"], 0.5)
        self.assertAlmostEqual(metrics["micro_precision"], 1.0)
        self.assertAlmostEqual(metrics["micro_recall"], 2 / 3)

    def test_cost_summary(self) -> None:
        cost = cost_summary(1_000_000, 500_000, 0.15, 0.60)
        self.assertAlmostEqual(cost["estimated_total_cost"], 0.45)
        self.assertTrue(cost["pricing_provided"])


class ResponseParsingTests(unittest.TestCase):
    def test_parses_complete_json_response(self) -> None:
        raw = json.dumps(
            {
                "results": [
                    {
                        "sample_id": "REP-0001",
                        "sentiment": "happy",
                        "issues": ["pricing_promotions"],
                    }
                ]
            }
        )
        parsed = parse_llm_results(raw, {"REP-0001"})
        self.assertEqual(parsed["REP-0001"]["sentiment"], "happy")
        self.assertEqual(parsed["REP-0001"]["issues"], ["pricing_promotions"])

    def test_rejects_missing_results(self) -> None:
        with self.assertRaises(ValueError):
            parse_llm_results('{"results":[]}', {"REP-0001"})


if __name__ == "__main__":
    unittest.main()
