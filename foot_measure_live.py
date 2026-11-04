"""Live Ameba RTSP preview, freeze the displayed frame, then measure."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import tkinter as tk
from tkinter import messagebox, ttk

from coin_integration import detect_coins, render_detections, score_known_coin
from foot_geometry import write_png
from foot_live import LiveStream
from foot_measure import FootApp, new_folder

BASE = Path(__file__).resolve().parent
# The measurement workflow now supports NT$10 and NT$50 only.  This model was
# trained specifically for those two reference coins at the installed camera
# distance, rather than spending capacity on the retired NT$1 class.
DEFAULT_COIN_WEIGHTS = BASE / "models/coin_10_50_best.pt"


class LiveFootApp(FootApp):
    def __init__(self, root, output, url="", dataset_output=Path("coin_dataset/raw"),
                 coin_weights=DEFAULT_COIN_WEIGHTS, coin_confidence=.2):
        self.dataset_output = Path(dataset_output)
        self.coin_weights = Path(coin_weights)
        self.coin_confidence = float(coin_confidence)
        self.coin_model = None
        self.coin_model_error = None
        self.visible_detections = []
        self.detection_stats = None
        self.collecting = False
        self.collected = 0
        self.stream = None
        self.previewing = False
        self.visible_frame = None
        self.visible_time = 0
        super().__init__(root, output)
        root.title("Ameba · Wi-Fi 硬幣偵測與腳長量測")
        top = self.port_box.master
        # In live-detection mode the inherited threshold/zoom rows are only
        # needed after a frame has been frozen for foot measurement.  Hiding
        # them gives the camera preview substantially more vertical space.
        self.measurement_controls = tuple(top.grid_slaves(row=1) + top.grid_slaves(row=2))
        # Hide the USB-only row. Keep existing measurement controls in other rows.
        for child in top.grid_slaves(row=0):
            child.grid_remove()
        self.url = tk.StringVar(value=url)
        connection = ttk.Frame(top, style="FootCard.TFrame")
        connection.grid(row=0, column=0, columnspan=7, sticky="ew", pady=(0, 10))
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="相機網址").grid(row=0, column=0, padx=(0, 12))
        ttk.Entry(connection, textvariable=self.url, width=30).grid(row=0, column=1, sticky="ew", padx=(0, 10))
        controls = [("開始／回到預覽", self.start_preview), ("停止串流", self.stop_preview)]
        for column, (label, command) in enumerate(controls, 2):
            button = ttk.Button(connection, text=label, command=command)
            button.grid(row=0, column=column, padx=3)
            self.buttons.append(button)
        actions = ttk.Frame(top, style="FootCard.TFrame")
        actions.grid(row=3, column=0, columnspan=7, sticky="w", pady=(8, 0))
        for column, (label, command) in enumerate([("拍下目前畫面", self.capture), ("開啟照片", self.open_file),
                                                  ("手動四點", self.start_manual), ("自動量測", self.automatic)]):
            button = ttk.Button(actions, text=label, command=command,
                                style="FootPrimary.TButton" if column == 0 else "TButton")
            button.grid(row=0, column=column, padx=(0, 8))
            self.buttons.append(button)
        collector = ttk.Frame(top, style="FootCard.TFrame")
        collector.grid(row=4, column=0, columnspan=7, sticky="ew", pady=(10, 0))
        self.coin = tk.StringVar(value="1")
        self.interval = tk.StringVar(value="2")
        self.target = tk.StringVar(value="100")
        ttk.Label(collector, text="定時存圖：面額").grid(row=0, column=0)
        coin_box = ttk.Combobox(collector, textvariable=self.coin, values=("1", "10", "50"), width=4, state="readonly")
        coin_box.grid(row=0, column=1, padx=4)
        ttk.Label(collector, text="元　間隔（秒）").grid(row=0, column=2)
        interval_box = ttk.Entry(collector, textvariable=self.interval, width=5)
        interval_box.grid(row=0, column=3, padx=4)
        ttk.Label(collector, text="目標張數").grid(row=0, column=4)
        target_box = ttk.Entry(collector, textvariable=self.target, width=5)
        target_box.grid(row=0, column=5, padx=4)
        start = ttk.Button(collector, text="開始收集", command=self.start_collection)
        start.grid(row=0, column=6, padx=4)
        ttk.Button(collector, text="停止收集", command=self.stop_collection).grid(row=0, column=7, padx=4)
        self.collection_inputs = (coin_box, interval_box, target_box, start)
        self.collection_progress = tk.StringVar(value="尚未收集；選定 1 元、10 元或 50 元後，系統會依你的面額標記儲存訓練影像。")
        ttk.Label(collector, textvariable=self.collection_progress, wraplength=850).grid(row=1, column=0, columnspan=8, sticky="w", pady=4)
        self.detection_summary = tk.StringVar(value="硬幣偵測：尚未啟動。10 元資料將用於下一輪重新訓練。")
        ttk.Label(collector, textvariable=self.detection_summary, wraplength=850).grid(row=2, column=0, columnspan=8, sticky="w", pady=(0, 4))
        self.status.set("填入 RTSP 網址後按開始預覽；可收集 1 元、10 元與 50 元硬幣資料。")
        self.summary.set("預覽會以完整畫面等比例放大，不裁切；會顯示硬幣框與面額。這一輪只測偵測，既有腳長換算仍固定使用 10 元 26 mm。")
        self.set_measurement_controls_visible(False)
        self.live_timer = root.after(80, self.update_preview)

    def set_measurement_controls_visible(self, visible):
        """Keep the preview roomy, but restore measurement options for a frozen photo."""
        for control in self.measurement_controls:
            if visible:
                control.grid()
            else:
                control.grid_remove()
        if visible:
            self.confirmation_check.pack(anchor="w", padx=20, pady=(0, 14))
        else:
            self.confirmation_check.pack_forget()

    def redraw(self):
        """Render live frames as a contained, centred image with no cropping."""
        super().redraw()
        if self.previewing and self.zoom.get() == "適合視窗":
            # The base renderer uses the smallest scale necessary to contain
            # the source frame; reset any old scrollbar position each refresh.
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)

    def ensure_coin_model(self):
        if self.coin_model is not None:
            return
        if not self.coin_weights.is_file():
            raise ValueError(f"找不到硬幣模型：{self.coin_weights}")
        try:
            from coin_yolo import load
            self.coin_model = load(self.coin_weights)
            self.coin_model_error = None
        except Exception as error:
            self.coin_model_error = str(error)
            raise ValueError("硬幣模型無法載入。請用 .venv-yolo 啟動，並確認 ultralytics 已安裝。") from error

    def inspect_coins(self, frame):
        if self.coin_model is None:
            return []
        try:
            self.coin_model_error = None
            return detect_coins(self.coin_model, frame, self.coin_confidence)
        except Exception as error:
            self.coin_model_error = str(error)
            return []

    def update_detection_summary(self):
        if self.coin_model_error:
            self.detection_summary.set(f"硬幣偵測錯誤：{self.coin_model_error}")
        elif not self.visible_detections:
            self.detection_summary.set("硬幣偵測：本張沒有高於門檻的 1 元／10 元／50 元硬幣。")
        else:
            labels = "、".join(
                f"{item['denomination']} 元 {item['confidence']:.2f}" for item in self.visible_detections)
            self.detection_summary.set(f"硬幣偵測：{labels}")

    def start_preview(self):
        if self.busy:
            return
        self.stop_collection()
        self.set_measurement_controls_visible(False)
        try:
            self.status.set("正在載入 1 元／10 元／50 元硬幣模型…")
            self.root.update_idletasks()
            self.ensure_coin_model()
            if self.stream is None or self.stream.url != self.url.get().strip() or not self.stream.thread.is_alive():
                if self.stream:
                    self.stream.close()
                self.stream = LiveStream(self.url.get())
            self.previewing = True
            self.visible_frame = None
            self.set_image_empty()
            self.status.set("正在連接／接收即時畫面…")
        except ValueError as error:
            messagebox.showerror("RTSP 網址", str(error))

    def set_image_empty(self):
        self.image = self.display = self.result = self.mask = self.frame = self.folder = None
        self.points, self.manual = [], False
        self.visible_detections = []
        self.confirmed.set(False)
        self.zoom.set("適合視窗")
        self.canvas.delete("all")
        self.summary.set("即時預覽中。硬幣框可辨識 1 元／10 元／50 元；腳長換算仍要依原本固定 10 元流程。")

    def update_preview(self):
        if self.closed:
            return
        if self.previewing and self.stream:
            try:
                frame, stamp = self.stream.snapshot()
                if stamp != self.visible_time or self.visible_frame is None:
                    self.visible_frame, self.visible_time = frame, stamp
                    self.visible_detections = self.inspect_coins(frame)
                    self.display = render_detections(frame, self.visible_detections)
                    self.update_detection_summary()
                    self.redraw()
                    self.status.set("即時預覽中（Wi-Fi 串流可能有延遲）。調整好位置後，按『拍下目前畫面』。")
            except ValueError as error:
                self.visible_frame = None
                self.display = None
                self.canvas.delete("all")
                self.status.set(str(error))
        self.collect_frame()
        self.live_timer = self.root.after(80, self.update_preview)

    def start_collection(self):
        if self.collecting or self.busy:
            return
        try:
            interval = float(self.interval.get())
            target = int(self.target.get())
            coin = self.coin.get()
            if not math.isfinite(interval) or interval < 1 or target < 1 or coin not in ("1", "10", "50"):
                raise ValueError("請選擇面額，間隔至少 1 秒，目標張數為正整數。")
            if not self.previewing or self.visible_frame is None or time.monotonic() - self.visible_time > 1.5:
                raise ValueError("請先開始預覽，等到新畫面後再開始收集。")
            self.collection_folder = new_folder(self.dataset_output / f"coin_{coin}")
        except (ValueError, OSError) as error:
            messagebox.showerror("無法開始收集", str(error))
            return
        self.collection_coin, self.collection_interval, self.collection_target = coin, interval, target
        self.collected = 0
        self.detection_stats = {"frames": 0, "correct": 0, "wrong_class": 0, "missed": 0, "extra_boxes": 0}
        self.last_collected_stamp = None
        self.next_collection = time.monotonic() + interval
        self.collecting = True
        for widget in self.collection_inputs:
            widget.configure(state="disabled")
        self.show_collection_progress("收集中")

    def show_collection_progress(self, state):
        score = ""
        if self.detection_stats and self.detection_stats["frames"]:
            stats = self.detection_stats
            score = (f"；偵測：正確 {stats['correct']}、誤判 {stats['wrong_class']}、"
                     f"漏檢 {stats['missed']}、額外框 {stats['extra_boxes']}"
                     f"（成功率 {stats['correct'] / stats['frames']:.0%}）")
        purpose = ""
        self.collection_progress.set(
            f"{state}：{self.collection_coin} 元，{self.collected}/{self.collection_target} 張，每 {self.collection_interval:g} 秒\n"
            f"保存位置：{self.collection_folder.resolve()}{score} {purpose}".rstrip())

    def stop_collection(self, reason="已停止"):
        if not self.collecting:
            return
        self.collecting = False
        for widget in self.collection_inputs:
            widget.configure(state="normal")
        self.collection_inputs[0].configure(state="readonly")
        self.show_collection_progress(reason)

    def collect_frame(self):
        if not self.collecting:
            return
        now = time.monotonic()
        if not self.previewing or self.visible_frame is None or now - self.visible_time > 1.5:
            self.stop_collection("影像中斷，已停止；恢復預覽後可開始新批次")
            return
        if now < self.next_collection or self.visible_time == self.last_collected_stamp:
            return
        frame = self.visible_frame.copy()
        detections = [dict(item) for item in self.visible_detections]
        if self.detection_stats is None:
            prediction_status, extra_boxes = "not_evaluated", 0
        else:
            prediction_status, extra_boxes = score_known_coin(self.collection_coin, detections)
        stem = f"coin_{self.collection_coin}_{self.collected + 1:04d}"
        png = self.collection_folder / f"{stem}.png"
        metadata = {"kind": "ameba_rtsp_decoded_frame", "image": png.name,
                    "coin_denomination_user_supplied": int(self.collection_coin),
                    "coin_detector": {"weights": str(self.coin_weights), "confidence_threshold": self.coin_confidence,
                                      "detections": detections, "prediction_status": prediction_status,
                                      "extra_boxes": extra_boxes},
                    "annotation_status": "unlabeled", "batch_id": self.collection_folder.name,
                    "captured_utc": datetime.now(timezone.utc).isoformat(),
                    "rtsp_url": self.stream.url, "interval_seconds": self.collection_interval}
        try:
            write_png(png, frame)
            png.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError) as error:
            self.stop_collection(f"存檔失敗，已停止（最後一筆可能不完整）：{error}")
            return
        self.collected += 1
        if self.detection_stats is not None:
            self.detection_stats["frames"] += 1
            self.detection_stats[prediction_status] += 1
            self.detection_stats["extra_boxes"] += extra_boxes
        self.last_collected_stamp = self.visible_time
        self.next_collection = time.monotonic() + self.collection_interval
        self.show_collection_progress("收集中")
        if self.collected >= self.collection_target:
            self.stop_collection("目標完成")

    def capture(self):
        if self.busy:
            return
        if not self.previewing or self.visible_frame is None or time.monotonic() - self.visible_time > 1.5:
            messagebox.showinfo("尚無即時影像", "請先開始預覽，等待清楚的新畫面後再拍照。")
            return
        # Freeze the exact frame last shown to the user, not a later decoder frame.
        self.stop_collection()
        frame = self.visible_frame.copy()
        self.previewing = False
        source = {"kind": "ameba_rtsp_decoded_frame", "image": "original.png",
                  "rtsp_url": self.stream.url, "captured_utc": datetime.now(timezone.utc).isoformat(),
                  "coin_detector": {"weights": str(self.coin_weights), "confidence_threshold": self.coin_confidence,
                                    "detections": [dict(item) for item in self.visible_detections]},
                  "note": "Displayed H264 decoded frame; PNG adds no further lossy compression. No USB LED ACK."}
        self.set_image(frame, source)
        self.set_measurement_controls_visible(True)
        try:
            folder = new_folder(self.output)
            write_png(folder / "original.png", frame)
            (folder / "capture.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
            self.folder = folder
            self.status.set("已凍結並保存目前畫面，可選手動四點／自動量測；想重拍請按『開始／回到預覽』。")
        except (OSError, ValueError) as error:
            self.status.set(f"已凍結，但原圖保存失敗：{error}")
            messagebox.showerror("存檔失敗", str(error))

    def stop_preview(self):
        if self.busy:
            return
        self.stop_collection()
        was_live = self.previewing
        self.previewing = False
        if self.stream:
            self.stream.close()
            self.stream = None
        self.visible_frame = None
        if was_live:
            self.set_image_empty()
        self.status.set("已停止串流。已拍下的照片仍可量測；尚未拍照的預覽不會保留。")

    def begin_collection_when_ready(self, attempts=0):
        """Start a requested timed collection only after a fresh RTSP frame exists."""
        if self.closed or self.collecting:
            return
        if self.previewing and self.visible_frame is not None and time.monotonic() - self.visible_time <= 1.5:
            self.start_collection()
            return
        if attempts >= 30:
            self.status.set("尚未收到可用 RTSP 畫面，未開始自動收集。請檢查 Wi-Fi／網址後手動按開始收集。")
            return
        self.root.after(500, lambda: self.begin_collection_when_ready(attempts + 1))

    def open_path(self, path):
        self.stop_collection()
        self.previewing = False
        self.set_measurement_controls_visible(True)
        super().open_path(path)

    def close(self):
        self.stop_collection()
        self.root.after_cancel(self.live_timer)
        if self.stream:
            self.stream.close()
        super().close()


def main():
    parser = argparse.ArgumentParser(description="Ameba Wi-Fi 預覽 → 1 元／5 元 YOLO 偵測 → 拍照與腳長量測")
    parser.add_argument("--url", default="")
    parser.add_argument("--output", type=Path, default=Path("foot_captures"))
    parser.add_argument("--dataset-output", type=Path, default=Path("coin_dataset/raw"))
    parser.add_argument("--coin-weights", type=Path, default=DEFAULT_COIN_WEIGHTS)
    parser.add_argument("--coin-conf", type=float, default=.2)
    parser.add_argument("--collect-coin", choices=("1", "10", "50"))
    parser.add_argument("--collect-interval", type=float, default=2)
    parser.add_argument("--collect-target", type=int, default=100)
    parser.add_argument("--auto-collect", action="store_true",
                        help="在收到新 RTSP 畫面後，依指定收集設定開始定時存圖")
    args = parser.parse_args()
    root = tk.Tk()
    app = LiveFootApp(root, args.output, args.url, args.dataset_output, args.coin_weights, args.coin_conf)
    if args.collect_coin:
        app.coin.set(args.collect_coin)
        app.interval.set(str(args.collect_interval))
        app.target.set(str(args.collect_target))
    if args.url:
        root.after(300, app.start_preview)
    if args.auto_collect:
        if not args.url or not args.collect_coin:
            parser.error("--auto-collect 需要 --url 與 --collect-coin")
        root.after(1000, app.begin_collection_when_ready)
    root.mainloop()


if __name__ == "__main__":
    main()
