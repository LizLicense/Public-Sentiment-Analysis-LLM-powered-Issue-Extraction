import unittest

import pandas as pd

from processing.build_clean_corpus import cap_per_thread, deduplicate, thread_table, title_is_telco, weighted_views


def frame(rows):
    return pd.DataFrame(rows, columns=["source", "thread_title", "post_text", "telco_label", "sentiment_label", "issue_primary"])


class DeduplicateTests(unittest.TestCase):
    def test_keeps_one_copy_per_thread_and_text(self) -> None:
        df = frame([
            ("reddit", "Singtel down?", "No signal at all", "Singtel", "not_happy", "network_quality"),
            ("reddit", "Singtel  down?", "no signal   at all", "Singtel", "not_happy", "network_quality"),
            ("reddit", "Other thread", "No signal at all", "Singtel", "not_happy", "network_quality"),
        ])
        out = deduplicate(df)
        self.assertEqual(len(out), 2)
        self.assertEqual(sorted(out["n_copies"]), [1, 2])


class ThreadFilterTests(unittest.TestCase):
    def test_title_rules(self) -> None:
        self.assertTrue(title_is_telco("GOMO user - "))
        self.assertTrue(title_is_telco("CirclesLife charging $70-$90 out of nowhere?"))
        self.assertTrue(title_is_telco("Best SIM-only plan with 5G?"))
        self.assertFalse(title_is_telco("Eight Singapore taxi drivers arrested over bribery"))
        self.assertFalse(title_is_telco("Woman sues Prudential over buried clause"))

    def test_drops_thread_below_share_unless_title_is_telco(self) -> None:
        df = deduplicate(frame(
            [("reddit", "Where to buy a mattress?", f"post {i}", "Singtel" if i == 0 else "", "neutral", "general_discussion")
             for i in range(10)]
            + [("reddit", "GOMO signal issues", f"reply {i}", "", "not_happy", "network_quality") for i in range(3)]
        ))
        threads = thread_table(df, min_share=0.2).set_index("thread_title")
        self.assertFalse(threads.loc["Where to buy a mattress?", "keep"])
        self.assertTrue(threads.loc["GOMO signal issues", "keep"])


class WeightingTests(unittest.TestCase):
    def test_thread_equal_weighting_stops_one_big_thread_dominating(self) -> None:
        df = deduplicate(frame(
            [("reddit", "Outage", f"down {i}", "Singtel", "not_happy", "network_quality") for i in range(9)]
            + [("reddit", "Roaming", "roaming was fine", "M1", "happy", "roaming")]
        ))
        views = weighted_views(df, cap=5, seed=0)
        self.assertEqual(views["per_post"]["issue_primary"]["network_quality"], 90.0)
        self.assertEqual(views["thread_equal"]["issue_primary"]["network_quality"], 50.0)
        self.assertEqual(len(cap_per_thread(df, cap=5, seed=0)), 6)


if __name__ == "__main__":
    unittest.main()
