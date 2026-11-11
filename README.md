# Ameba 智慧尺碼量測系統

本專題以 AMB82-MINI 的相機擷取影像，透過 Wi-Fi RTSP 串流傳送至電腦端。電腦端使用 YOLOv8 進行硬幣與穿襪足部辨識，再以硬幣的實際直徑建立比例尺，估算足長並儲存量測紀錄。

## 系統流程

```text
AMB82-MINI 相機
  → Wi-Fi RTSP 串流
  → 電腦端 YOLOv8 推論
  → 10 元或 50 元硬幣面額
  → 穿襪足部遮罩
  → 幾何換算腳長
  → 網頁顯示與量測紀錄
```

## 影像辨識模型

| 項目 | 模型 | 類別 | 用途 |
|---|---|---|---|
| 硬幣偵測 | YOLOv8n 偵測模型 | 10 元、50 元 | 取得硬幣面額與比例尺 |
| 足部辨識 | YOLOv8n-seg 分割模型 | 穿襪足部 | 取得足部遮罩與輪廓 |
| 腳長估算 | 幾何換算 | - | 以硬幣直徑換算足長 |

模型權重已放在 `models/`：

- `coin_10_50_best.pt`：10 元與 50 元硬幣偵測模型
- `socked_foot_seg_best.pt`：穿襪足部分割模型

## 專案結構

```text
.
├─ firmware/ameba_foot_wifi/   # AMB82-MINI Wi-Fi RTSP 韌體
├─ models/                     # 已部署的模型權重
├─ web_dashboard/              # 網頁介面前端
├─ training/                   # 可重現的資料準備與訓練腳本
├─ tests/                      # 量測與辨識的自動測試
├─ web_dashboard.py            # 本機網站伺服器
├─ foot_ai_integration.py      # 足部與硬幣辨識整合
├─ foot_geometry.py            # 腳長幾何換算
└─ foot_measure_live.py        # 桌面版即時量測介面
```

## 硬體與軟體需求

- AMB82-MINI 與相機模組
- 可供電的 USB 線
- 與電腦位於同一網路的 Wi-Fi
- Windows 電腦與 Python 3.10 以上
- Arduino IDE 2.x，並安裝 Realtek AmebaPro2 的 AMB82-MINI 開發板支援

## 安裝與啟動

### 1. 安裝電腦端套件

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 設定並上傳 Ameba 韌體

1. 將 `firmware/ameba_foot_wifi/wifi_secrets.example.h` 複製為 `wifi_secrets.h`
2. 填入 Wi-Fi 名稱與密碼。`wifi_secrets.h` 已被 `.gitignore` 排除，不會上傳
3. 以 Arduino IDE 開啟 `firmware/ameba_foot_wifi/ameba_foot_wifi.ino`
4. 選擇 `AMB82-MINI`、正確 COM 埠與相機感測器後上傳
5. 開啟 Serial Monitor，鮑率設為 `115200`，重設後確認畫面出現 `READY,AMEBA_FOOT_WIFI` 與 `RTSP_URL=rtsp://...:554`

### 3. 啟動網頁量測介面

```powershell
python web_dashboard.py --port 8000
```

在瀏覽器開啟 <http://127.0.0.1:8000>，輸入 Serial Monitor 顯示的 RTSP 位址，按下「開始即時預覽」。

### 4. 同一個 Wi-Fi 的手機／其他電腦展示

此專案的 AI 模型在執行網站的 Windows 電腦上運算；手機或其他電腦只需開啟瀏覽器。

1. 讓展示裝置、Windows 電腦與 Ameba 相機連上同一個 Wi-Fi
2. 在 Windows 電腦的 PowerShell 執行：

```powershell
.\start_lan_dashboard.ps1
```

3. 第一次啟動若 Windows 跳出防火牆提示，請選擇允許「私人網路」
4. 終端機會列出網址，例如 `http://192.168.1.23:8000`
5. 在手機或其他電腦的瀏覽器輸入該網址即可操作

> `127.0.0.1` 只能由執行網站的同一台電腦開啟；展示時請分享終端機列出的 `192.168.x.x` 網址。此模式不適合直接暴露在公網。

## 操作方式

1. 將穿襪的單腳與一枚 10 元或 50 元硬幣放在同一平面
2. 讓足部與硬幣完整入鏡，硬幣需靠近鏡頭且不可被遮住
3. 等候網頁同時顯示硬幣與襪子腳辨識結果
4. 按下「凍結分析畫面」再按「自動計算腳長」
5. 視需要填寫姓名、編號與備註，按下「儲存量測紀錄」

## 測試

```powershell
python -m unittest discover -s tests -v
```

## 已知限制

- 足部的角度、襪口與小腿交界、畫面裁切都會影響遮罩與足長估算
- 10 元與 50 元硬幣必須在畫面中具有足夠大小；鏡頭距離過遠可能造成漏檢或誤判
- 本系統為影像式尺碼估算工具，不作為醫療或精密量測儀器

## 展示影片

<https://youtu.be/fnlz0Hy8Pi8?si=oJ6F20qnQoDN1Wuv>
