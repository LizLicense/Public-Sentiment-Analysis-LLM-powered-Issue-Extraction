import unittest

from processing.telco_labeler import detect_telcos, is_eight_telco_reference


class EightDetectionTests(unittest.TestCase):
    def test_accepts_strong_brand_phrases(self) -> None:
        examples = [
            "Eight Telecom launched a new plan.",
            "Is the Eight mobile SIM-only plan worth it?",
            "Eight is an MVNO with roaming data.",
            "Should I port from Singtel to Eight?",
            "Does Eight support 5G?",
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertTrue(is_eight_telco_reference(text))
                self.assertIn("Eight", detect_telcos(text))

    def test_rejects_number_and_transport_uses(self) -> None:
        examples = [
            "Eight buses were added to the route.",
            "She worked there for eight years.",
            "Eight people attended the event.",
            "I waited eight hours while the Singtel network was down.",
            "Singtel had an eight-hour network outage.",
            "The team scored eight points.",
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertFalse(is_eight_telco_reference(text))
                self.assertNotIn("Eight", detect_telcos(text))

    def test_keeps_other_telcos_when_eight_is_a_number(self) -> None:
        self.assertEqual(
            detect_telcos("I waited eight hours for Singtel support."),
            ["Singtel"],
        )


if __name__ == "__main__":
    unittest.main()
