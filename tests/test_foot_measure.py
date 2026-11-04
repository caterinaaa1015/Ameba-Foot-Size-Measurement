"""Geometry and FOOT10 protocol tests; all images/devices are synthetic."""
import contextlib
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from foot_geometry import measure_manual, measure_auto, write_png
from foot_measure import FootApp, demo_image, save_result
from foot_serial import Decoder, FootCamera, Frame, checksum


@contextlib.contextmanager
def output_directory():
    root = (Path(__file__).parent / ".build" / "foot_tests").resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        assert Path(folder).resolve().is_relative_to(root)
        yield Path(folder)


def jpeg_packet():
    ok, data = cv2.imencode(".jpg", demo_image())
    assert ok
    payload = data.tobytes()
    header = f"JPEG,MODE=FOOT10,TX=7,LENGTH={len(payload)},CHECKSUM={checksum(payload)}\n"
    return header.encode() + payload + b"\n", payload


def status(rx=0, result=0, blue="OFF", green="OFF"):
    return (f"STATUS,SOURCE=AMEBA,MODE=FOOT10,TX=7,RX_ID={rx},RESULT_ID={result},"
            f"BLUE={blue},GREEN={green},BUSY=OFF\n").encode()


class FakeFootSerial:
    def __init__(self):
        self.buffer = bytearray()
        self.commands = []
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.buffer)

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, data):
        command = data.decode().strip()
        self.commands.append(command)
        if command == "CAPTURE":
            self.buffer.extend(jpeg_packet()[0])
        elif command.startswith("ACK,"):
            self.buffer.extend(status(rx=7, blue="ON"))
        elif command == "RESULT,7,1":
            self.buffer.extend(status(rx=7, result=7, green="ON"))
        else:
            self.buffer.extend(status())
        return len(data)

    def read(self, size):
        data = bytes(self.buffer[:min(size, 127)])
        del self.buffer[:len(data)]
        if not data:
            time.sleep(0.001)
        return data

    def close(self):
        self.closed = True


class GeometryTests(unittest.TestCase):
    def test_manual_known_scale_and_rotation(self):
        image = demo_image()
        for end in ([400, 620], [920, 100]):
            result = measure_manual(image, [[824, 400], [876, 400], [400, 100], end])
            self.assertAlmostEqual(result["foot_length_mm"], 260)
            self.assertAlmostEqual(result["mm_per_pixel"], 0.5)

    def test_manual_rejects_bad_points_and_small_coin(self):
        for points in ([[[0, 0]]], [[0, 0], [20, 0], [50, 50], [50, 500]],
                       [[0, 0], [52, 0], [50, 50], [50, 800]],
                       [[0, 0], [52, 0], [float("nan"), 50], [50, 500]]):
            with self.subTest(points=points), self.assertRaises(ValueError):
                measure_manual(demo_image(), points)

    def test_auto_synthetic_scale_and_rotation(self):
        for angle in (0, 25, 70):
            image = np.full((900, 1400, 3), (130, 45, 25), np.uint8)
            cv2.ellipse(image, (470, 450), (95, 260), angle, 0, 360, (160, 185, 215), -1)
            cv2.circle(image, (1100, 450), 52, (190, 190, 190), -1)
            result, mask = measure_auto(image)
            # Ideal length: 520 / 104 * 26 = 130 mm. Raster boundary is approximate.
            self.assertAlmostEqual(result["foot_length_mm"], 130, delta=2)
            self.assertEqual(mask.shape, image.shape[:2])

    def test_auto_refuses_missing_multiple_and_elliptical_coins(self):
        for mode in ("missing", "multiple", "ellipse"):
            image = demo_image()
            if mode in {"missing", "ellipse"}:
                cv2.rectangle(image, (800, 350), (900, 450), (130, 45, 25), -1)
            if mode == "multiple":
                cv2.circle(image, (1050, 400), 26, (190, 190, 190), -1)
            if mode == "ellipse":
                cv2.ellipse(image, (850, 400), (35, 20), 0, 0, 360, (190, 190, 190), -1)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                measure_auto(image)

    def test_border_contact_rejected(self):
        image = demo_image()
        cv2.rectangle(image, (450, 0), (500, 150), (160, 185, 215), -1)
        with self.assertRaises(ValueError):
            measure_auto(image)

    def test_report_units_error_and_no_shoe_size(self):
        image = demo_image()
        result = measure_manual(image, [[824, 400], [876, 400], [480, 100], [480, 620]])
        with output_directory() as folder:
            path = save_result(folder, image, result, {"kind": "synthetic_test"}, 258)
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["signed_error_mm"], 2)
            self.assertTrue((folder / report["overlay"]).is_file())
            self.assertIsNone(report["shoe_size"])


class ProtocolTests(unittest.TestCase):
    def test_fragmented_packet_and_status(self):
        packet, payload = jpeg_packet()
        wire = status() + packet + status(rx=7, blue="ON")
        decoder, events = Decoder(), []
        for offset in range(0, len(wire), 17):
            events.extend(decoder.feed(wire[offset:offset + 17]))
        self.assertEqual([e[0] for e in events], ["status", "frame", "status"])
        self.assertEqual(events[1][1].jpeg, payload)
        self.assertEqual(events[1][1].decode().shape[:2], (720, 1280))

    def test_corrupt_packet_wrong_firmware_and_bad_header_rejected(self):
        packet, _ = jpeg_packet()
        for wire in (packet.replace(b"JFIF", b"XXXX", 1),
                     b"STATUS,SOURCE=AMEBA,MODEL=SCRFD\n",
                     b"JPEG,MODE=FOOT10,TX=1,LENGTH=9999999,CHECKSUM=0\n",
                     b"JPEG,MODE=FOOT10,TX=0,LENGTH=10,CHECKSUM=0\n",
                     status().replace(b"BLUE=OFF", b"BLUE=YES")):
            with self.subTest(wire=wire[:60]), self.assertRaises(ValueError):
                Decoder().feed(wire)

    def test_valid_checksum_is_not_sufficient_to_decode(self):
        payload = b"\xff\xd8broken\xff\xd9"
        with self.assertRaises((ValueError, OSError)):
            Frame(payload, 1, checksum(payload)).decode()

    def test_capture_ack_result_handshake(self):
        fake = FakeFootSerial()
        with patch("foot_serial.serial.Serial", return_value=fake):
            camera = FootCamera("TEST")
            try:
                frame = camera.capture()
                self.assertFalse(any(c.startswith("ACK,") for c in fake.commands))
                reply = camera.acknowledge(frame)
                self.assertEqual(reply["RX_ID"], 7)
                self.assertEqual(reply["BLUE"], "ON")
                reply = camera.report_measurement(frame)
                self.assertEqual(reply["GREEN"], "ON")
                with self.assertRaises(ValueError):
                    camera.report_measurement(Frame(frame.jpeg, 99, frame.checksum))
            finally:
                camera.close()
        self.assertTrue(fake.closed)


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        with patch("foot_measure.ports", return_value=[]), patch("foot_measure.default_port", return_value=""):
            self.app = FootApp(self.root, Path(".build") / "unused")
        self.app.set_image(demo_image(), {"kind": "synthetic_test"})
        self.root.update()

    def tearDown(self):
        self.app.close()
        self.assertEqual(self.errors, [])

    def test_manual_clicks_map_from_scrolled_zoom_to_original_pixels(self):
        self.app.zoom.set("200%")
        self.app.start_manual()
        self.app.canvas.xview_moveto(0.1)
        self.app.canvas.yview_moveto(0.1)
        points = [[824, 400], [876, 400], [480, 100], [480, 620]]
        for x, y in points:
            event = SimpleNamespace(x=self.app.offset[0] + x * self.app.scale[0] - self.app.canvas.canvasx(0),
                                    y=self.app.offset[1] + y * self.app.scale[1] - self.app.canvas.canvasy(0))
            self.app.click(event)
        self.assertAlmostEqual(self.app.result["foot_length_mm"], 260)
        self.assertIsNotNone(self.app.photo)

    def test_new_image_clears_prior_results_and_confirmation(self):
        self.app.automatic()
        self.assertIsNotNone(self.app.result)
        self.app.confirmed.set(True)
        self.app.set_image(demo_image(), {"kind": "new"})
        self.assertIsNone(self.app.result)
        self.assertFalse(self.app.confirmed.get())

    def test_failed_auto_cannot_save_previous_measurement(self):
        self.app.automatic()
        self.assertIsNotNone(self.app.result)
        self.app.threshold.set("bad")
        self.app.automatic()
        self.assertIsNone(self.app.result)


if __name__ == "__main__":
    unittest.main()
