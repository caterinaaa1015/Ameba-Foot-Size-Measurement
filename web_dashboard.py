"""Local browser dashboard for Ameba coin + socked-foot measurement.

The server binds only to 127.0.0.1.  Models and RTSP frames never leave the
computer; the browser is only the crisp user interface.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlparse
import socket

import cv2
import numpy as np

from coin_integration import detect_coins
from foot_ai_integration import COIN_DIAMETERS_MM, best_known_coin, detect_socked_feet, rasterize_mask, render_combined_detections
from foot_geometry import annotate, measure_ai_assisted, measure_manual, write_png
from foot_live import LiveStream
from foot_measure import new_folder, save_result
from foot_measure_live import DEFAULT_COIN_WEIGHTS
from measurement_ledger import MeasurementLedger


BASE = Path(__file__).resolve().parent
WEB_ROOT = BASE / "web_dashboard"
DEFAULT_FOOT_WEIGHTS = BASE / "runs/segment/output/foot_seg/pilot_140_hardcases/weights/best.pt"


class MeasurementService:
    def __init__(self, output, coin_weights=DEFAULT_COIN_WEIGHTS, foot_weights=DEFAULT_FOOT_WEIGHTS):
        self.output = Path(output)
        self.coin_weights, self.foot_weights = Path(coin_weights), Path(foot_weights)
        self.ledger = MeasurementLedger(self.output / "measurement_records.json")
        self.lock = threading.Lock()
        self.coin_model = self.foot_model = self.stream = None
        self.frame = self.overlay = None
        self.coins = self.feet = []
        self.frozen = False
        self.result = self.last_source = None
        self.status = "等待輸入 RTSP 位址"
        self._generation = 0
        self._worker = None

    def ensure_models(self):
        if self.coin_model is None:
            if not self.coin_weights.is_file():
                raise ValueError(f"找不到硬幣模型：{self.coin_weights}")
            from coin_yolo import load
            self.coin_model = load(self.coin_weights)
        if self.foot_model is None:
            if not self.foot_weights.is_file():
                raise ValueError(f"找不到足部輪廓模型：{self.foot_weights}")
            from ultralytics import YOLO
            self.foot_model = YOLO(str(self.foot_weights))

    def start(self, url):
        self.ensure_models()
        if self.stream:
            self.stream.close()
        with self.lock:
            self._generation += 1
            generation = self._generation
            self.stream = LiveStream(url)
            self.frozen = False
            self.frame = self.overlay = None
            self.coins, self.feet, self.result = [], [], None
            self.status = "正在接收 RTSP 即時影像…"
        self._worker = threading.Thread(target=self._analysis_loop, args=(generation,), daemon=True,
                                        name="FootAIAnalysis")
        self._worker.start()

    def _analysis_loop(self, generation):
        """Analyse in one background worker; browser requests only read a cached JPEG."""
        while generation == self._generation:
            if not self.frozen:
                try:
                    self.refresh()
                except Exception as error:
                    with self.lock:
                        self.status = f"AI 分析暫時失敗：{error}"
            time.sleep(0.15)

    def refresh(self):
        if self.frozen or self.stream is None:
            return
        try:
            frame, _ = self.stream.snapshot()
        except ValueError as error:
            # Keep the RTSP failure visible to the browser instead of leaving
            # the page permanently on "正在接收" with a broken-image icon.
            with self.lock:
                self.status = f"無法取得 RTSP 影像：{error}"
            return
        coins = detect_coins(self.coin_model, frame, .2)
        feet = detect_socked_feet(self.foot_model, frame, .25)
        with self.lock:
            self.frame, self.coins, self.feet = frame, coins, feet
            self.overlay = render_combined_detections(frame, coins, feet)
            coin = best_known_coin(coins)
            self.status = (f"硬幣 NT${coin['denomination']}、足部輪廓已辨識，可拍下分析"
                           if coin and feet else "等待同時辨識一枚硬幣與足部輪廓")

    def freeze(self):
        with self.lock:
            coin = best_known_coin(self.coins)
            if self.frame is None or coin is None or not self.feet:
                raise ValueError("需要同時辨識一枚 10／50 元硬幣與足部輪廓")
            self.frozen = True
            self.result = None
            self.last_source = {"kind": "ameba_rtsp_decoded_frame", "captured_utc": datetime.now(timezone.utc).isoformat(),
                                "coin_detector": {"weights": str(self.coin_weights), "detections": self.coins},
                                "foot_segmenter": {"weights": str(self.foot_weights), "detections": self.feet}}
            self.status = "分析已凍結，請點選硬幣兩端、腳跟與最長腳趾"

    def measure(self, points):
        with self.lock:
            coin = best_known_coin(self.coins)
            if not self.frozen or self.frame is None or coin is None:
                raise ValueError("請先拍下 AI 分析畫面")
            if not isinstance(points, list) or len(points) != 4:
                raise ValueError("需要四個點：硬幣兩端、腳跟、最長腳趾")
            denomination = coin["denomination"]
            self.result = measure_manual(self.frame, points, COIN_DIAMETERS_MM[denomination], f"detected_NTD{denomination}")
            self.overlay = annotate(self.overlay if self.overlay is not None else self.frame, self.result)
            self.status = "量測完成，請填寫受測者資料並儲存"
            return self.result

    def auto_measure(self):
        with self.lock:
            coin = best_known_coin(self.coins)
            if not self.frozen or self.frame is None or coin is None or not self.feet:
                raise ValueError("請先在同時辨識到硬幣與足部輪廓時凍結分析畫面")
            denomination = coin["denomination"]
            self.result = measure_ai_assisted(self.frame, coin, self.feet[0],
                                              COIN_DIAMETERS_MM[denomination],
                                              f"detected_NTD{denomination}")
            self.overlay = annotate(self.overlay if self.overlay is not None else self.frame, self.result)
            self.status = "已自動計算腳長，請確認畫面上的量測線後儲存"
            return self.result

    def save_record(self, payload):
        with self.lock:
            coin = best_known_coin(self.coins)
            if self.result is None or self.frame is None or coin is None:
                raise ValueError("請先完成四點量測")
            folder = new_folder(self.output / "captures")
            foot = self.feet[0]
            write_png(folder / "original.png", self.frame)
            write_png(folder / "ai_overlay.png", self.overlay)
            write_png(folder / "ai_foot_mask.png", rasterize_mask(self.frame.shape, foot))
            source = dict(self.last_source or {})
            source["scale_reference"] = {"denomination": coin["denomination"], "diameter_mm": COIN_DIAMETERS_MM[coin["denomination"]]}
            path = save_result(folder, self.frame, self.result, source)
            record = self.ledger.create(str(payload.get("subject_name", "")), str(payload.get("subject_id", "")),
                                        str(payload.get("note", "")), self.result, coin["denomination"], path)
            self.status = "量測紀錄已儲存"
            return record

    def state(self):
        with self.lock:
            coin = best_known_coin(self.coins)
            return {"status": self.status, "frozen": self.frozen,
                    "image_size": None if self.frame is None else [int(self.frame.shape[1]), int(self.frame.shape[0])],
                    "coin": None if coin is None else {"denomination": coin["denomination"], "confidence": round(coin["confidence"], 3)},
                    "foot": None if not self.feet else {"confidence": round(self.feet[0]["confidence"], 3)},
                    "result": self.result, "records": self.ledger.records}

    def model_state(self):
        """Return only local model metadata for the dashboard status page."""
        with self.lock:
            return {
                "coin": {
                    "title": "硬幣辨識模型",
                    "file": self.coin_weights.name,
                    "available": self.coin_weights.is_file(),
                    "loaded": self.coin_model is not None,
                    "classes": ["10 元", "50 元"],
                    "live_result": None if best_known_coin(self.coins) is None else f"{best_known_coin(self.coins)['denomination']} 元",
                },
                "foot": {
                    "title": "足部輪廓分割模型",
                    "file": self.foot_weights.name,
                    "available": self.foot_weights.is_file(),
                    "loaded": self.foot_model is not None,
                    "classes": ["穿襪足部"],
                    "live_result": None if not self.feet else "已辨識足部輪廓",
                },
            }

    def jpeg(self):
        with self.lock:
            if self.overlay is None:
                return None
            ok, data = cv2.imencode(".jpg", self.overlay, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise ValueError("預覽影像編碼失敗")
            return data.tobytes()

    def close(self):
        self._generation += 1
        if self.stream:
            self.stream.close()


class DashboardHandler(SimpleHTTPRequestHandler):
    service: MeasurementService = None
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        # This is a local development dashboard.  Never let Chrome retain an
        # old HTML/JS bundle after the Python service has been updated.
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, *_args):
        return
    def json(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
    def do_GET(self):
        if self.path == "/api/state":
            self.json(HTTPStatus.OK, self.service.state()); return
        if self.path == "/api/models":
            self.json(HTTPStatus.OK, self.service.model_state()); return
        if self.path == "/api/frame.jpg":
            try: data = self.service.jpeg()
            except ValueError as error: self.json(HTTPStatus.BAD_REQUEST, {"error": str(error)}); return
            if data is None: self.send_error(HTTPStatus.NO_CONTENT); return
            self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "image/jpeg"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        super().do_GET()
    def do_POST(self):
        try:
            payload = self.body()
            if self.path == "/api/start": self.service.start(str(payload.get("url", ""))); result = self.service.state()
            elif self.path == "/api/freeze": self.service.freeze(); result = self.service.state()
            elif self.path == "/api/measure": result = self.service.measure(payload.get("points"))
            elif self.path == "/api/auto-measure": result = self.service.auto_measure()
            elif self.path == "/api/records": result = self.service.save_record(payload)
            elif self.path.startswith("/api/records/"):
                record_id = self.path.rsplit("/", 1)[-1]
                result = self.service.ledger.update_identity(record_id, str(payload.get("subject_name", "")), str(payload.get("subject_id", "")), str(payload.get("note", "")))
            else: self.send_error(HTTPStatus.NOT_FOUND); return
            self.json(HTTPStatus.OK, result)
        except (ValueError, json.JSONDecodeError) as error:
            self.json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def do_DELETE(self):
        try:
            if not self.path.startswith("/api/records/"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            record_id = self.path.rsplit("/", 1)[-1]
            if not record_id:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            result = self.service.ledger.delete(record_id)
            self.json(HTTPStatus.OK, result)
        except ValueError as error:
            self.json(HTTPStatus.BAD_REQUEST, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser(description="Local web dashboard for AI foot measurement")
    parser.add_argument("--host", default="127.0.0.1",
                        help="監聽位址；同一個 Wi-Fi 展示請使用 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--output", type=Path, default=Path("foot_measure_dashboard"))
    args = parser.parse_args()
    service = MeasurementService(args.output)
    DashboardHandler.service = service
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    if args.host == "0.0.0.0":
        addresses = sorted({address[4][0] for address in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                            if not address[4][0].startswith("127.")})
        print("區網展示模式已啟動。請讓其他裝置與這台電腦連上同一個 Wi-Fi")
        for address in addresses:
            print(f"其他裝置可開啟： http://{address}:{args.port}")
    else:
        print(f"開啟瀏覽器： http://{args.host}:{args.port}")
    try: server.serve_forever()
    finally: service.close(); server.server_close()


if __name__ == "__main__": main()
