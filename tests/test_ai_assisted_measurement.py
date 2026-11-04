"""Unit test for coin-scaled socked-foot measurement geometry."""
import unittest

import cv2
import numpy as np

from foot_geometry import measure_ai_assisted


class AIAssistedMeasurementTests(unittest.TestCase):
    def test_circle_scale_and_mask_axis_produce_millimetres(self):
        image = np.full((600, 800, 3), 220, dtype=np.uint8)
        cv2.circle(image, (620, 300), 50, (80, 80, 80), 3)
        coin = {"xyxy": [565, 245, 675, 355]}
        # Toe (left), wide forefoot, narrow ankle, then a wider sock cuff.
        # The automatic routine must stop at the ankle instead of counting
        # the cuff as extra foot length.
        foot = {"polygon": [[100, 250], [130, 210], [220, 190], [300, 195],
                            [350, 230], [390, 255], [430, 245], [500, 235],
                            [510, 360], [420, 350], [385, 330], [340, 350],
                            [260, 390], [150, 390], [105, 350]]}

        result = measure_ai_assisted(image, coin, foot, 26.0, "detected_NTD10")

        self.assertEqual(result["mode"], "ai_assisted")
        self.assertAlmostEqual(result["coin_diameter_px"], 100, delta=8)
        self.assertGreater(result["foot_length_mm"], 50)
        self.assertIn("coin_circle", result)
        self.assertIn("foot_contour", result)
        self.assertGreater(result["ankle_cut_score"], .14)

    def test_missing_coin_edge_requires_manual_fallback(self):
        image = np.full((600, 800, 3), 220, dtype=np.uint8)
        coin = {"xyxy": [565, 245, 675, 355]}
        foot = {"polygon": [[100, 250], [130, 210], [220, 190], [300, 195],
                            [350, 230], [390, 255], [430, 245], [500, 235],
                            [510, 360], [420, 350], [385, 330], [340, 350],
                            [260, 390], [150, 390], [105, 350]]}

        with self.assertRaisesRegex(ValueError, "硬幣圓邊"):
            measure_ai_assisted(image, coin, foot, 26.0, "detected_NTD10")


if __name__ == "__main__":
    unittest.main()
