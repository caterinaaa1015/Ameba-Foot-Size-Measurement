"""Desktop NT$10 coin foot-length experiment: python foot_measure.py."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import uuid

import cv2
import numpy as np
from PIL import Image, ImageTk

from foot_geometry import annotate, measure_auto, measure_manual, read_image, write_png
from foot_serial import FootCamera, default_port, ports


def new_folder(output):
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ") + "_" + uuid.uuid4().hex[:8]
    folder = Path(output) / name
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def save_result(folder, image, result, source, actual_mm=None, mask=None):
    if actual_mm is not None and (not math.isfinite(actual_mm) or actual_mm <= 0):
        raise ValueError("實測腳長請輸入正數，單位是 mm；不知道可留白。")
    stem = "measurement_" + uuid.uuid4().hex[:8]
    report = dict(result)
    report.update({"created_utc": datetime.now(timezone.utc).isoformat(), "source": source,
                   "image_size": [image.shape[1], image.shape[0]], "user_confirmed": True,
                   "overlay": stem + ".png", "actual_foot_length_mm": actual_mm})
    if actual_mm is not None:
        report["signed_error_mm"] = result["foot_length_mm"] - actual_mm
        report["absolute_error_mm"] = abs(report["signed_error_mm"])
    write_png(folder / report["overlay"], annotate(image, result))
    if mask is not None:
        report["mask"] = stem + "_mask.png"
        write_png(folder / report["mask"], mask)
    path = folder / (stem + ".json")
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def demo_image():
    """Synthetic geometry only, deliberately not a real foot or real coin."""
    image = np.full((720, 1280, 3), (130, 45, 25), np.uint8)
    cv2.ellipse(image, (480, 360), (95, 260), 0, 0, 360, (160, 185, 215), -1)
    cv2.circle(image, (850, 400), 26, (190, 190, 190), -1)
    return image


class FootApp:
    def __init__(self, root, output, port=""):
        self.root, self.output = root, Path(output)
        self.camera = None
        self.image = self.display = self.photo = None
        self.result = self.mask = self.frame = self.folder = None
        self.source = {}
        self.points = []
        self.manual = self.busy = self.closed = False
        self.events = queue.Queue()
        self.scale, self.offset = (1.0, 1.0), (0, 0)
        self.port = tk.StringVar(value=port or default_port())
        self.actual = tk.StringVar()
        self.threshold = tk.StringVar(value="40")
        self.zoom = tk.StringVar(value="適合視窗")
        self.confirmed = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="固定一枚 10 元硬幣（26 mm），俯拍一隻完整裸腳。尚未連接硬體。")
        self.summary = tk.StringVar(value="先拍攝或開啟照片；自動模式需純色背景。也可用手動四點驗證比例。")
        root.title("Ameba · 10 元硬幣腳長量測原型")
        width = min(1320, root.winfo_screenwidth() - 60)
        height = min(980, root.winfo_screenheight() - 80)
        root.geometry(f"{width}x{height}")
        root.minsize(900, 650)
        self._style()
        header = ttk.Frame(root, padding=(20, 10, 20, 6))
        header.pack(fill="x")
        ttk.Label(header, text="Ameba  /  腳長量測", style="FootTitle.TLabel").pack(anchor="w")
        ttk.Label(header, text="01  調整畫面    /    02  拍照量測    /    03  確認儲存",
                  style="FootHint.TLabel").pack(anchor="w", pady=(5, 0))
        top = ttk.Frame(root, padding=8, style="FootCard.TFrame")
        top.pack(fill="x", padx=20)
        top.columnconfigure(6, weight=1)
        ttk.Label(top, text="COM 埠").grid(row=0, column=0, padx=4)
        self.port_box = ttk.Combobox(top, textvariable=self.port, width=12)
        self.port_box.grid(row=0, column=1, padx=4)
        ttk.Button(top, text="更新埠清單", command=self.refresh_ports).grid(row=0, column=2, padx=4)
        self.buttons = []
        for column, (label, callback) in enumerate([
                ("① 拍攝一張", self.capture), ("開啟照片", self.open_file),
                ("② 自動量測", self.automatic), ("② 手動四點", self.start_manual)], start=3):
            button = ttk.Button(top, text=label, command=callback)
            button.grid(row=0, column=column, padx=4, pady=4)
            self.buttons.append(button)
        settings = ttk.Frame(top, style="FootCard.TFrame")
        settings.grid(row=1, column=0, columnspan=7, sticky="ew", pady=5)
        settings.columnconfigure(4, weight=1)
        ttk.Label(settings, text="背景差異門檻").grid(row=0, column=0, padx=(0, 10))
        ttk.Entry(settings, textvariable=self.threshold, width=8).grid(row=0, column=1, padx=(0, 18))
        ttk.Label(settings, text="實測腳長 mm（選填）").grid(row=0, column=2, padx=(0, 10))
        ttk.Entry(settings, textvariable=self.actual, width=9).grid(row=0, column=3)
        self.save_button = ttk.Button(settings, text="確認並儲存", command=self.save, style="FootPrimary.TButton")
        self.save_button.grid(row=0, column=5, padx=(12, 0))
        self.buttons.append(self.save_button)
        ttk.Label(top, text="檢視比例").grid(row=2, column=0)
        zoom_box = ttk.Combobox(top, textvariable=self.zoom, values=["適合視窗", "100%", "200%"],
                               state="readonly", width=12)
        zoom_box.grid(row=2, column=1, pady=3)
        zoom_box.bind("<<ComboboxSelected>>", lambda event: self.redraw())
        ttk.Label(top, text="手動選硬幣時可放大，使用捲軸移動影像。").grid(row=2, column=2, columnspan=5, sticky="w")
        self.status_label = ttk.Label(root, textvariable=self.status, padding=(20, 5),
                                      style="FootHint.TLabel", wraplength=1100)
        self.status_label.pack(fill="x")
        self.canvas_frame = ttk.Frame(root)
        self.canvas_frame.pack(fill="both", expand=True, padx=20)
        self.canvas_frame.rowconfigure(0, weight=1)
        self.canvas_frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.canvas_frame, background="#EAECE7", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        xbar = ttk.Scrollbar(self.canvas_frame, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        xbar.grid(row=1, column=0, sticky="ew")
        ybar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.bind("<Configure>", lambda event: self.redraw())
        self.canvas.bind("<Button-1>", self.click)
        self.summary_label = ttk.Label(root, textvariable=self.summary, padding=(20, 6),
                                        wraplength=1100, style="FootSummary.TLabel")
        self.summary_label.pack(fill="x")
        root.bind("<Configure>", lambda event: self._wrap_labels(event))
        self.confirmation_check = ttk.Checkbutton(
            root, variable=self.confirmed,
            text="我已確認：是 10 元硬幣、相機近乎垂直，且硬幣直徑與腳長端點／輪廓正確。"
        )
        self.confirmation_check.pack(anchor="w", padx=20, pady=(0, 14))
        self.refresh_ports()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_timer = root.after(75, self.poll)

    def _wrap_labels(self, event):
        if event.widget == self.root:
            for label in (self.status_label, self.summary_label):
                label.configure(wraplength=max(300, event.width - 60))

    def _style(self):
        from PIL import ImageDraw
        self.root.configure(background="#F6F5F2")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft JhengHei", 12, "bold"), foreground="#353B36")
        # Entry widgets and combobox popups use Tk font options rather than only ttk styles.
        for widget in ("TEntry", "TCombobox"):
            self.root.option_add(f"*{widget}*font", ("Microsoft JhengHei", 12, "bold"))
        self.root.option_add("*TCombobox*Listbox.font", ("Microsoft JhengHei", 12, "bold"))
        style.configure("TFrame", background="#F6F5F2")
        style.configure("FootCard.TFrame", background="#FFFFFF")
        style.configure("TLabel", background="#FFFFFF", foreground="#535B54")
        style.configure("FootTitle.TLabel", background="#F6F5F2", foreground="#2E352F",
                        font=("Microsoft JhengHei", 22, "bold"))
        style.configure("FootHint.TLabel", background="#F6F5F2", foreground="#6D746C")
        style.configure("FootSummary.TLabel", background="#F6F5F2", foreground="#3E4840",
                        font=("Microsoft JhengHei", 13, "bold"))
        style.configure("TCheckbutton", background="#F6F5F2", foreground="#5E665F")
        style.map("TCheckbutton", background=[("active", "#F6F5F2")])
        for kind in ("TEntry", "TCombobox"):
            style.configure(kind, padding=6, fieldbackground="#F8F8F5", background="#F0F1EC",
                            bordercolor="#DADDD5", lightcolor="#DADDD5", darkcolor="#DADDD5",
                            arrowcolor="#697166", selectbackground="#DCE2D7", selectforeground="#303B30")
        for kind in ("Horizontal.TScrollbar", "Vertical.TScrollbar"):
            style.configure(kind, background="#D7DBD2", troughcolor="#F6F5F2", borderwidth=0, arrowsize=12)
        self.button_images = []
        for name, palette, fg in (
            ("TButton", ("#EDF0E8", "#E1E6DA", "#D4DDCD", "#F2F3EF"), "#414D3E"),
            ("FootPrimary.TButton", ("#4C5B48", "#3C4C38", "#303F2D", "#E9ECE5"), "#FFFFFF"),
        ):
            images = []
            for index, color in enumerate((*palette, palette[0])):
                tile = Image.new("RGBA", (120, 120))
                draw = ImageDraw.Draw(tile)
                draw.rounded_rectangle((2, 2, 117, 117), radius=30, fill=color)
                if index == 4:
                    draw.rounded_rectangle((4, 4, 115, 115), radius=28, outline="#87947D", width=6)
                images.append(ImageTk.PhotoImage(tile.resize((40, 40), Image.Resampling.LANCZOS), master=self.root))
            self.button_images.extend(images)
            element = "FootRounded" + name
            style.element_create(element, "image", images[0], ("disabled", images[3]),
                                 ("pressed", images[2]), ("focus", images[4]), ("active", images[1]),
                                 border=11, sticky="nsew")
            style.layout(name, [(element, {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
            style.configure(name, foreground=fg, background="white", padding=(12, 5), anchor="center")
            style.map(name, foreground=[("disabled", "#91988B")])

    def refresh_ports(self):
        try:
            self.port_box["values"] = [p.device for p in ports()]
            if not self.port.get():
                self.port.set(default_port())
        except OSError as error:
            self.status.set(str(error))

    def job(self, function, callback):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state="disabled")

        def worker():
            try:
                self.events.put((callback, function(), None))
            except Exception as error:
                self.events.put((callback, None, str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            callback, result, error = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button in self.buttons:
                button.configure(state="normal")
            if error:
                self.status.set("操作失敗：" + error)
                messagebox.showerror("操作失敗", error)
            else:
                callback(result)
        self.poll_timer = self.root.after(75, self.poll)

    def set_image(self, image, source, folder=None, frame=None):
        self.image, self.display = image, image.copy()
        self.source, self.folder, self.frame = source, folder, frame
        self.result = self.mask = None
        self.points, self.manual = [], False
        self.actual.set("")
        self.zoom.set("適合視窗")
        self.confirmed.set(False)
        self.summary.set("選擇自動量測，或點『手動四點』依序選硬幣直徑兩端、腳跟與最長腳趾。")
        self.redraw()

    def capture(self):
        port = self.port.get().strip()
        if not port:
            messagebox.showinfo("選擇 COM", "請接上開發板、更新埠清單並選擇 COM 埠。")
            return
        self.status.set("正在接收 1280×720 快照，115200 baud 可能需要數秒至數十秒，請保持不動。")

        def work():
            try:
                if self.camera is None or self.camera.port != port:
                    if self.camera:
                        self.camera.close()
                    self.camera = FootCamera(port)
                if self.closed:
                    self.camera.close()
                    return None
                frame = self.camera.capture()
                folder = new_folder(self.output)
                (folder / "original.jpg").write_bytes(frame.jpeg)
                try:
                    status = self.camera.acknowledge(frame)
                except Exception as error:
                    raise OSError(f"原圖已存於 {folder / 'original.jpg'}，但板端接收確認失敗：{error}") from error
                source = {"kind": "ameba_camera", "image": "original.jpg", "transfer_id": frame.transfer_id,
                          "jpeg_fnv1a32": frame.checksum, "board_receipt_at_capture": status}
                (folder / "capture.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
                return frame.decode(), source, folder, frame
            except Exception:
                if self.camera:
                    self.camera.close()
                    self.camera = None
                raise

        def done(value):
            self.set_image(*value)
            self.status.set("已保存原圖；擷取時板端回報 BLUE=ON（約 3 秒後熄滅）。請檢查畫面並量測。")
        self.job(work, done)

    def open_path(self, path):
        self.set_image(read_image(path), {"kind": "local_image", "original_path": str(Path(path).resolve())})
        self.status.set("已開啟本機照片。離線量測不會控制開發板燈號。")

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("照片", "*.jpg *.jpeg *.png"), ("所有檔案", "*.*")])
        if path:
            try:
                self.open_path(path)
            except (OSError, ValueError) as error:
                messagebox.showerror("無法開啟", str(error))

    def invalidate_result(self):
        self.result = self.mask = None
        self.confirmed.set(False)
        self.points = []
        self.display = None if self.image is None else self.image.copy()
        self.redraw()

    def automatic(self):
        if self.image is None:
            return
        self.manual = False
        self.invalidate_result()
        try:
            result, mask = measure_auto(self.image, float(self.threshold.get()))
            self.mask = mask
            self.show_result(result)
        except (ValueError, cv2.error) as error:
            self.summary.set("自動量測未成功：" + str(error) + "\n可以改用手動四點，先驗證換算。")

    def start_manual(self):
        if self.image is None:
            return
        self.invalidate_result()
        self.manual = True
        self.summary.set("第 1 點：硬幣邊緣。第 2 點要選通過圓心的另一端；第 3 點腳跟；第 4 點最長腳趾。")

    def click(self, event):
        if not self.manual or self.busy or self.image is None:
            return
        x = (self.canvas.canvasx(event.x) - self.offset[0]) / self.scale[0]
        y = (self.canvas.canvasy(event.y) - self.offset[1]) / self.scale[1]
        h, w = self.image.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            return
        self.points.append([x, y])
        self.redraw()
        hints = ["", "第 2 點：通過硬幣圓心的對側邊緣。", "第 3 點：腳跟最後端。", "第 4 點：最長腳趾前端。"]
        if len(self.points) < 4:
            self.summary.set(hints[len(self.points)])
        else:
            self.manual = False
            try:
                self.show_result(measure_manual(self.image, self.points))
            except ValueError as error:
                self.summary.set(str(error) + " 請按手動四點重新標記。")

    def show_result(self, result):
        self.result = result
        self.display = annotate(self.image, result)
        self.points = []
        width = result["silhouette_width_mm"]
        width_text = "" if width is None else f"；輪廓最大寬 {width:.1f} mm"
        self.summary.set(f'腳長估計：{result["foot_length_mm"]:.1f} mm（{result["foot_length_mm"] / 10:.2f} cm）{width_text}\n'
                         f'硬幣直徑 {result["coin_diameter_px"]:.1f} px；比例 {result["mm_per_pixel"]:.4f} mm/px。'
                         f'硬幣直徑若差 1 px，腳長約差 {result["coin_1px_error_effect_mm_approx"]:.1f} mm（非完整誤差範圍）。\n'
                         + " ".join(result["warnings"]))
        self.redraw()

    def redraw(self):
        if self.display is None:
            return
        h, w = self.display.shape[:2]
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        scale = min(cw / w, ch / h) if self.zoom.get() == "適合視窗" else float(self.zoom.get()[:-1]) / 100
        dw, dh = max(1, round(w * scale)), max(1, round(h * scale))
        self.scale = (dw / w, dh / h)
        self.offset = (max(0, (cw - dw) // 2), max(0, (ch - dh) // 2))
        self.canvas.configure(scrollregion=(0, 0, max(cw, dw), max(ch, dh)))
        # A previous 100%/200% inspection may have left the view scrolled.  In
        # "fit" mode always return to the complete image rather than showing a
        # cropped corner of it.
        if self.zoom.get() == "適合視窗":
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
        image = Image.fromarray(cv2.cvtColor(self.display, cv2.COLOR_BGR2RGB)).resize((dw, dh))
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(*self.offset, image=self.photo, anchor="nw")
        for i, (x, y) in enumerate(self.points, 1):
            px, py = self.offset[0] + x * self.scale[0], self.offset[1] + y * self.scale[1]
            self.canvas.create_oval(px - 5, py - 5, px + 5, py + 5, fill="#ffdd00")
            self.canvas.create_text(px + 12, py - 10, text=str(i), fill="white")

    def save(self):
        if self.result is None:
            messagebox.showinfo("尚未量測", "先完成自動或手動量測。")
            return
        if not self.confirmed.get():
            messagebox.showinfo("檢查量測", "請先檢查輪廓／端點、硬幣面額與拍攝角度，再勾選下方確認。")
            return
        try:
            actual = float(self.actual.get()) if self.actual.get().strip() else None
            if actual is not None and (not math.isfinite(actual) or actual <= 0):
                raise ValueError()
        except ValueError:
            messagebox.showerror("單位 mm", "實測腳長請輸入正數，例如 260；不知道可留白。")
            return
        result, image, mask = self.result, self.image, self.mask

        def work():
            if self.folder is None:
                self.folder = new_folder(self.output)
                # Store a lossless working copy; preserve the original path as provenance.
                write_png(self.folder / "original.png", image)
                self.source["image"] = "original.png"
            path = save_result(self.folder, image, result, dict(self.source), actual, mask)
            note = "離線照片，不更新板端燈號。"
            if self.frame is not None and self.camera is not None:
                try:
                    status = self.camera.report_measurement(self.frame)
                    path.with_suffix(".board.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
                    note = "板端回報 GREEN=ON（約 5 秒後熄滅），表示電腦已確認並保存量測。"
                except Exception as error:
                    note = f"資料已存，但板端綠燈未確認：{error}"
            return path, note

        def done(value):
            path, note = value
            self.status.set(f"已儲存：{path}。{note}")
        self.job(work, done)

    def close(self):
        self.closed = True
        self.root.after_cancel(self.poll_timer)
        if self.camera:
            self.camera.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="10 元硬幣 26 mm 比例量腳長；不辨識面額、不輸出品牌鞋碼")
    parser.add_argument("--port", default="")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--output", type=Path, default=Path("foot_captures"))
    parser.add_argument("--demo", action="store_true", help="合成幾何示範，非實機量測")
    args = parser.parse_args()
    if args.image and args.demo:
        parser.error("--image 和 --demo 請擇一")
    root = tk.Tk()
    app = FootApp(root, args.output, args.port)
    if args.demo:
        app.set_image(demo_image(), {"kind": "synthetic_demo"})
        app.status.set("合成幾何示範：不是實際腳部或硬幣照片，不代表實機精度。")
    elif args.image:
        try:
            app.open_path(args.image)
        except (OSError, ValueError) as error:
            messagebox.showerror("無法開啟", str(error))
    root.mainloop()


if __name__ == "__main__":
    main()
