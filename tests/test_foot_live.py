import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from foot_live import LiveStream, validate_url
from foot_measure import demo_image
from foot_measure_live import LiveFootApp
from setup_foot_wifi import credential_header
try:
    from tests.test_foot_measure import output_directory
except ModuleNotFoundError:  # Supports unittest discovery executed inside tests/.
    from test_foot_measure import output_directory


class StreamTests(unittest.TestCase):
    def test_url_and_credentials(self):
        self.assertEqual(validate_url(' rtsp://192.168.1.2:554 '), 'rtsp://192.168.1.2:554')
        for url in ('http://localhost', 'rtsp://', 'rtsp://user:pass@localhost', 'rtsp://localhost:bad'):
            with self.assertRaises(ValueError):
                validate_url(url)
        header = credential_header('測試"\\', 'password123')
        self.assertIn('(char)0x22,(char)0x5c,0', header)
        self.assertIn('(char)0xe6', header)
        for ssid, password in (('', ''), ('a' * 33, ''), ('abc', 'short')):
            with self.assertRaises(ValueError):
                credential_header(ssid, password)

    def test_disconnect_discards_frame_and_releases_capture(self):
        released = threading.Event()
        capture = SimpleNamespace(isOpened=lambda: True, read=lambda: (False, None), release=released.set)
        stream = LiveStream('rtsp://localhost:554', factory=lambda *args: capture)
        stream.thread.join(2)
        self.assertTrue(released.is_set())
        with self.assertRaises(ValueError):
            stream.snapshot()

    def test_stale_and_closed_frames_rejected(self):
        stream = LiveStream.__new__(LiveStream)
        stream.lock, stream.stop = threading.Lock(), threading.Event()
        stream.latest = (np.zeros((2, 2, 3), dtype=np.uint8), time.monotonic() - 2)
        with self.assertRaises(ValueError):
            stream.snapshot()
        stream.latest = (np.zeros((2, 2, 3), dtype=np.uint8), time.monotonic())
        image, _ = stream.snapshot()
        image[:] = 255
        self.assertFalse(stream.latest[0].any())
        stream.close()
        with self.assertRaises(ValueError):
            stream.snapshot()


class PreviewTests(unittest.TestCase):
    def test_collection_saves_fresh_frames_stops_at_target_and_handles_failure(self):
        root = tk.Tk()
        root.withdraw()
        with output_directory() as folder, patch('foot_measure.ports', return_value=[]), patch('foot_measure.default_port', return_value=''):
            app = LiveFootApp(root, folder, 'rtsp://localhost:554', folder / 'dataset')
            try:
                app.stream = SimpleNamespace(url=app.url.get(), close=lambda: None)
                app.previewing = True
                app.visible_frame = demo_image()
                app.visible_time = time.monotonic()
                app.target.set('2')
                app.start_collection()
                batch = app.collection_folder
                app.collect_frame()
                self.assertEqual(app.collected, 0)
                app.next_collection = 0
                app.collect_frame()
                self.assertEqual(app.collected, 1)
                self.assertTrue(app.previewing)
                self.assertTrue((batch / 'coin_1_0001.png').exists())
                app.next_collection = 0
                app.collect_frame()
                self.assertEqual(app.collected, 1)  # Same decoded frame must not be saved twice.
                app.visible_time = time.monotonic()
                app.collect_frame()
                self.assertEqual(app.collected, 2)
                self.assertFalse(app.collecting)
                self.assertEqual(len(list(batch.glob('*.json'))), 2)
                app.start_collection()
                self.assertNotEqual(batch, app.collection_folder)
                app.visible_time = time.monotonic() - 2
                app.collect_frame()
                self.assertFalse(app.collecting)
                self.assertEqual(app.collected, 0)
                app.visible_time = time.monotonic()
                app.start_collection()
                app.next_collection = 0
                with patch('foot_measure_live.write_png', side_effect=OSError('disk full')):
                    app.collect_frame()
                self.assertFalse(app.collecting)
                self.assertEqual(app.collected, 0)
                self.assertIn('disk full', app.collection_progress.get())
                app.interval.set('nan')
                with patch('foot_measure_live.messagebox.showerror') as error:
                    app.start_collection()
                    error.assert_called_once()
                self.assertFalse(app.collecting)
            finally:
                app.close()

    def test_freeze_visible_frame_resume_and_refuse_stale(self):
        root = tk.Tk()
        root.withdraw()
        with output_directory() as folder, patch('foot_measure.ports', return_value=[]), patch('foot_measure.default_port', return_value=''):
            app = LiveFootApp(root, folder, 'rtsp://localhost:554')
            try:
                displayed = demo_image()
                newer = np.zeros_like(displayed)
                stream = SimpleNamespace(url=app.url.get(), thread=SimpleNamespace(is_alive=lambda: True),
                                         snapshot=lambda: (newer.copy(), time.monotonic()), close=lambda: None)
                app.stream = stream
                app.previewing = True
                app.visible_frame, app.visible_time = displayed, time.monotonic()
                app.capture()
                self.assertFalse(app.previewing)
                np.testing.assert_array_equal(app.image, displayed)
                self.assertTrue((app.folder / 'original.png').exists())
                # The decoder can move on, but a frozen image must not change.
                root.after_cancel(app.live_timer)
                app.update_preview()
                np.testing.assert_array_equal(app.image, displayed)
                app.start_preview()
                self.assertIsNone(app.image)
                self.assertTrue(app.previewing)
                app.visible_frame, app.visible_time = newer, time.monotonic() - 2
                with patch('foot_measure_live.messagebox.showinfo') as info:
                    app.capture()
                    info.assert_called_once()
                self.assertIsNone(app.image)
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main()
