import unittest

import numpy as np

from foot_ai_integration import (COIN_DIAMETERS_MM, _restore_rotation,
                                 best_known_coin, rasterize_mask, render_combined_detections)
from foot_geometry import measure_manual


class AiIntegrationTests(unittest.TestCase):
    def test_known_denomination_selects_expected_reference_size(self):
        coin = {"denomination": 50, "confidence": .9, "xyxy": [1, 1, 10, 10]}
        self.assertEqual(best_known_coin([coin]), coin)
        self.assertEqual(COIN_DIAMETERS_MM[coin["denomination"]], 28.0)
        self.assertIsNone(best_known_coin([{"denomination": None}]))

    def test_mask_render_and_raster_do_not_change_camera_frame(self):
        frame = np.zeros((50, 70, 3), dtype=np.uint8)
        foot = {"confidence": .9, "xyxy": [10, 10, 40, 35], "polygon": [[10, 10], [40, 10], [35, 35], [10, 30]]}
        coin = {"denomination": 10, "confidence": .9, "xyxy": [45, 15, 60, 30]}
        mask = rasterize_mask(frame.shape, foot)
        self.assertTrue(mask.any())
        output = render_combined_detections(frame, [coin], [foot])
        self.assertFalse(frame.any())
        self.assertTrue(output.any())

    def test_manual_measurement_uses_detected_coin_reference(self):
        image = np.zeros((300, 300, 3), dtype=np.uint8)
        result = measure_manual(image, [[10, 10], [110, 10], [20, 40], [20, 240]],
                                coin_diameter_mm=20.0, reference="detected_NTD1")
        self.assertEqual(result["reference"], "detected_NTD1")
        self.assertAlmostEqual(result["foot_length_mm"], 40.0)

    def test_rotated_polygon_returns_to_original_coordinates(self):
        shape = (100, 200, 3)
        original = np.array([[20, 30], [70, 45]], dtype=np.float32)
        clockwise = np.column_stack((shape[0] - 1 - original[:, 1], original[:, 0]))
        restored = _restore_rotation(clockwise, "cw", shape)
        np.testing.assert_allclose(restored, original)


if __name__ == "__main__":
    unittest.main()
