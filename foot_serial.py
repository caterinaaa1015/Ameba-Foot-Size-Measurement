"""FOOT10 camera transport. Byte checks and full JPEG decoding precede ACK."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import io
import time

import cv2
import numpy as np
import serial
from serial.tools import list_ports
from PIL import Image

MAX_JPEG = 524288


def checksum(payload):
    value = 2166136261
    for byte in payload:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value


@dataclass(frozen=True)
class Frame:
    jpeg: bytes
    transfer_id: int
    checksum: int

    def decode(self):
        # OpenCV may return partial pixels for truncated JPEGs; Pillow must fully load it first.
        with Image.open(io.BytesIO(self.jpeg)) as checked:
            if checked.format != "JPEG" or not (0 < checked.width <= 1920 and 0 < checked.height <= 1080):
                raise ValueError("非預期的 JPEG 格式或尺寸")
            checked.load()
        image = cv2.imdecode(np.frombuffer(self.jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None or not (0 < image.shape[0] <= 1080 and 0 < image.shape[1] <= 1920):
            raise ValueError("JPEG 解碼失敗或超過預期尺寸，未回傳接收確認。")
        return image


def fields(line):
    result = {}
    for field in line.split(",")[1:]:
        key, value = field.split("=", 1)
        if key in result:
            raise ValueError("重複的協定欄位")
        result[key] = value
    return result


class Decoder:
    def __init__(self):
        self.buffer = bytearray()
        self.pending = None

    def feed(self, data):
        self.buffer.extend(data)
        events = []
        while True:
            if self.pending:
                size, tx, expected = self.pending
                if len(self.buffer) < size:
                    break
                payload = bytes(self.buffer[:size])
                del self.buffer[:size]
                self.pending = None
                if (not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9")
                        or checksum(payload) != expected):
                    raise ValueError("JPEG 校驗失敗，請重新拍攝；本張未送 ACK。")
                events.append(("frame", Frame(payload, tx, expected)))
                continue
            end = self.buffer.find(b"\n")
            if end < 0:
                if len(self.buffer) > 4096:
                    raise ValueError("串列資料異常，請確認燒錄鞋碼相機韌體並關閉 NN Logs。")
                break
            line = bytes(self.buffer[:end]).decode("ascii", errors="replace").strip()
            del self.buffer[:end + 1]
            if line.startswith("JPEG,"):
                values = fields(line)
                if values.get("MODE") != "FOOT10":
                    raise ValueError("請上傳 ameba_foot_camera.ino，這不是鞋碼相機韌體。")
                size, tx, expected = (int(values[k]) for k in ("LENGTH", "TX", "CHECKSUM"))
                if not (0 < size <= MAX_JPEG and 0 < tx <= 0xFFFFFFFF and 0 <= expected <= 0xFFFFFFFF):
                    raise ValueError("無效的 JPEG 長度或傳輸編號")
                self.pending = (size, tx, expected)
            elif line.startswith("STATUS,"):
                values = fields(line)
                if values.get("MODE") != "FOOT10" or values.get("SOURCE") != "AMEBA":
                    raise ValueError("板上不是 FOOT10 韌體，請上傳 ameba_foot_camera.ino。")
                for key in ("BLUE", "GREEN", "BUSY"):
                    if values.get(key) not in {"ON", "OFF"}:
                        raise ValueError("不完整的板端狀態")
                for key in ("TX", "RX_ID", "RESULT_ID"):
                    value = int(values[key])
                    if not 0 <= value <= 0xFFFFFFFF:
                        raise ValueError("無效的板端編號")
                    values[key] = value
                events.append(("status", values))
            elif line.startswith("ERROR,"):
                raise ValueError("Ameba 回報：" + line[6:])
        return events


def ports():
    return list(list_ports.comports())


def default_port():
    available = ports()
    ch340 = [p.device for p in available if "CH340" in p.description.upper()]
    if len(ch340) == 1:
        return ch340[0]
    return available[0].device if len(available) == 1 else ""


class FootCamera:
    def __init__(self, port):
        self.device = serial.Serial(port, 115200, timeout=0.15, write_timeout=2)
        self.port = port
        self.decoder, self.events = Decoder(), deque()
        self.last_frame = None
        try:
            self.send("STATUS?")
            self.wait(lambda e: e[0] == "status", 20)
        except Exception:
            self.close()
            raise

    def send(self, command):
        self.device.write((command + "\n").encode("ascii"))

    def wait(self, predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while self.events:
                event = self.events.popleft()
                if predicate(event):
                    return event[1]
            self.events.extend(self.decoder.feed(self.device.read(min(max(self.device.in_waiting, 1), 8192))))
        raise TimeoutError("等待 Ameba 逾時。確認韌體／相機排線與 Camera Options；必要時按 RESET 再拍攝。")

    def capture(self):
        self.device.reset_input_buffer()
        self.decoder, self.events = Decoder(), deque()
        self.last_frame = None
        self.send("CAPTURE")
        frame = self.wait(lambda e: e[0] == "frame", 70)
        frame.decode()
        self.last_frame = frame
        return frame

    def acknowledge(self, frame):
        if self.last_frame != frame:
            raise ValueError("只能確認本次連線最新收到的影像")
        self.send(f"ACK,{frame.transfer_id},{frame.checksum}")
        return self.wait(lambda e: e[0] == "status" and e[1]["RX_ID"] == frame.transfer_id
                         and e[1]["BLUE"] == "ON", 5)

    def report_measurement(self, frame):
        if self.last_frame != frame:
            raise ValueError("影像不屬於此連線，無法更新板端燈號")
        self.send(f"RESULT,{frame.transfer_id},1")
        return self.wait(lambda e: e[0] == "status" and e[1]["RESULT_ID"] == frame.transfer_id
                         and e[1]["GREEN"] == "ON", 5)

    def close(self):
        self.device.close()
