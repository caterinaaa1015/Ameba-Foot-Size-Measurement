import unittest

import numpy as np

from coin_integration import denomination_from_label, render_detections, score_known_coin


class CoinIntegrationTests(unittest.TestCase):
    def test_only_expected_coin_labels_have_denominations(self):
        self.assertEqual(denomination_from_label("coin_1"), 1)
        self.assertEqual(denomination_from_label("coin_10"), 10)
        self.assertIsNone(denomination_from_label("background"))

    def test_known_coin_scoring_records_misses_and_extra_boxes(self):
        one = {"label": "coin_1", "denomination": 1, "confidence": .9, "xyxy": [1, 2, 20, 22]}
        ten = {"label": "coin_10", "denomination": 10, "confidence": .8, "xyxy": [30, 2, 50, 22]}
        self.assertEqual(score_known_coin(1, []), ("missed", 0))
        self.assertEqual(score_known_coin(1, [one]), ("correct", 0))
        self.assertEqual(score_known_coin(1, [ten]), ("wrong_class", 0))
        self.assertEqual(score_known_coin(1, [one, ten]), ("correct", 1))

    def test_render_keeps_source_image_unchanged(self):
        source = np.zeros((40, 60, 3), dtype=np.uint8)
        detection = {"label": "coin_1", "denomination": 1, "confidence": .9, "xyxy": [5, 5, 25, 25]}
        rendered = render_detections(source, [detection])
        self.assertFalse(source.any())
        self.assertTrue(rendered.any())


if __name__ == "__main__":
    unittest.main()
