"""Local-only Wi-Fi credential editor and ASCII-path Arduino sketch preparation."""
from pathlib import Path
import shutil
import tempfile
import tkinter as tk
from tkinter import messagebox, ttk


def credential_header(ssid, password):
    if not ssid or len(ssid.encode("utf-8")) > 32 or "\0" in ssid or "\0" in password:
        raise ValueError("Wi-Fi 名稱必須是 1–32 UTF-8 bytes，且不能含 NUL。")
    if password and not 8 <= len(password.encode("utf-8")) <= 63:
        raise ValueError("此設定工具支援空密碼或 8–63 bytes 的 WPA/WPA2 密碼。")
    # Encode as explicit UTF-8 bytes; no C++ escaping ambiguities for quotes/backslashes.
    def array(name, value):
        return f"char {name}[] = {{" + ",".join(f"(char)0x{byte:02x}" for byte in value.encode("utf-8")) + ("," if value else "") + "0};\n"
    return "#pragma once\n" + array("FOOT_WIFI_SSID", ssid) + array("FOOT_WIFI_PASS", password)


def main():
    root = tk.Tk()
    root.title("Ameba Wi-Fi 設定（僅保存在本機）")
    root.geometry("760x420")
    panel = ttk.Frame(root, padding=18)
    panel.pack(fill="both", expand=True)
    ssid, password = tk.StringVar(), tk.StringVar()
    ttk.Label(panel, text="請輸入 Ameba 要連接的 Wi-Fi；電腦也需在同一區域網路。", wraplength=700).pack(anchor="w")
    ttk.Label(panel, text="Wi-Fi 名稱（SSID）").pack(anchor="w", pady=(15, 2))
    ttk.Entry(panel, textvariable=ssid, width=60).pack(fill="x")
    ttk.Label(panel, text="Wi-Fi 密碼").pack(anchor="w", pady=(10, 2))
    ttk.Entry(panel, textvariable=password, show="●", width=60).pack(fill="x")
    ttk.Label(panel, text="設定會寫入本機 wifi_secrets.h（已排除 Git），並複製到英文暫存路徑供 Arduino 開啟。\n密碼會以可還原內容存在該檔案及韌體中，請勿分享含設定的草稿。",
              wraplength=700).pack(anchor="w", pady=12)
    output = tk.Text(panel, height=6, wrap="word")

    def save():
        try:
            header = credential_header(ssid.get(), password.get())
            sketch = Path(__file__).resolve().parent / "firmware" / "ameba_foot_wifi"
            (sketch / "wifi_secrets.h").write_text(header, encoding="ascii")
            destination = Path(tempfile.mkdtemp(prefix="ameba_foot_wifi_")) / "ameba_foot_wifi"
            destination.mkdir()
            for name in ("ameba_foot_wifi.ino", "wifi_secrets.h"):
                shutil.copy2(sketch / name, destination / name)
            output.delete("1.0", "end")
            output.insert("end", "設定已保存，尚未上傳。請在 Arduino IDE 開啟：\n" + str(destination / "ameba_foot_wifi.ino") +
                          "\n\n上傳後按 RESET，Serial Monitor 設 115200；複製 RTSP_URL= 後面的網址到量測介面。")
            password.set("")
        except (ValueError, OSError) as error:
            messagebox.showerror("設定未完成", str(error))

    ttk.Button(panel, text="保存設定並準備 Arduino 草稿", command=save).pack(anchor="w", pady=5)
    output.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
