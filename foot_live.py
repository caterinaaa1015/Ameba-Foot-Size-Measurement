"""RTSP preview worker: bounded latest-frame storage, timeout and stale rejection."""
import os
import threading
import time
from urllib.parse import urlsplit

# Ameba's H.264 RTSP stream can lose codec-parameter packets over UDP.
# Force TCP before OpenCV loads its FFmpeg backend for a reliable local stream.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2


def validate_url(url):
    value = url.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
        raise ValueError("請輸入完整 RTSP 網址，例如 rtsp://192.168.1.100:554")
    if parsed.username or parsed.password:
        raise ValueError("此版請使用 Ameba 未設帳密的區網 RTSP 網址。")
    _ = parsed.port
    return value


class LiveStream:
    def __init__(self, url, factory=None):
        self.url = validate_url(url)
        self.factory = factory or cv2.VideoCapture
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.error = "正在連接相機…"
        self.thread = threading.Thread(target=self.run, daemon=True, name="FootRTSP")
        self.thread.start()

    def run(self):
        # The Ameba H.264 stream occasionally starts before OpenCV receives
        # its parameter frames.  Reconnect a few times so one bad initial
        # decode does not leave the dashboard permanently blank.
        last_error = ""
        for attempt in range(4):
            if self.stop.is_set():
                return
            capture = None
            try:
                capture = self.factory(self.url, cv2.CAP_FFMPEG, [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000])
                if not capture.isOpened():
                    raise OSError("無法連接 RTSP；確認板子已上傳 Wi-Fi 韌體、電腦與板子在同一區網，以及網址正確。")
                while not self.stop.is_set():
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        raise OSError("相機串流中斷。請檢查 Wi-Fi 後重新按開始預覽。")
                    if not (0 < frame.shape[0] <= 2160 and 0 < frame.shape[1] <= 3840):
                        raise ValueError("串流影像尺寸超出預期")
                    with self.lock:
                        self.latest = (frame.copy(), time.monotonic())
                        self.error = ""
                return
            except Exception as error:
                last_error = str(error)
                with self.lock:
                    self.latest = None
                    self.error = (f"RTSP 重新連線中（{attempt + 1}/4）：{last_error}"
                                  if attempt < 3 else last_error)
                if not self.stop.wait(0.7):
                    continue
                return
            finally:
                if capture is not None:
                    capture.release()

    def snapshot(self):
        with self.lock:
            if self.stop.is_set():
                raise ValueError("串流已停止")
            if self.latest is None:
                raise ValueError(self.error or "尚未收到相機畫面")
            frame, received_at = self.latest
            if time.monotonic() - received_at > 1.5:
                raise ValueError("超過 1.5 秒未收到新畫面，請重新連線後再拍照。")
            return frame.copy(), received_at

    def close(self):
        self.stop.set()
        with self.lock:
            self.latest = None
