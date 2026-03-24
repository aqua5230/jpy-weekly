# 💴 USD/JPY 日圓週報自動化系統

自動化的日圓投資監測系統，每週一早上自動執行、分析、發報告。

**Live Report → [aqua5230.github.io/jpy-weekly](https://aqua5230.github.io/jpy-weekly/)**

---

## 系統架構

```
macOS LaunchAgent（每週一 07:00）
        ↓
jpy_weekly_report.py（主程式）
        ↓ 平行抓取（ThreadPoolExecutor × 10）
┌────────────────────────────────────────┐
│ USD/JPY 即時價格    yfinance            │
│ CFTC COT 大戶持倉  CFTC ZIP 解析       │
│ Fed/BoJ 資產負債表  FRED API            │
│ 日銀 QE 類型        Gemini AI 分析      │
│ 財務省干預偵測      MOF CSV             │
│ Werner 信用框架     BIS + FRED          │
│ 國際收支資本外流    FRED BOP 數據       │
│ 技術面指標          RSI / MA20 / MA50   │
│ 經濟行事曆          ForexFactory API    │
│ 本週新聞摘要        Gemini AI           │
└────────────────────────────────────────┘
        ↓
build_html_report.py → GitHub Pages（行動裝置友好）
test_image.py        → PIL 圖片卡
        ↓
Telegram Bot sendPhoto + 完整報告連結
```

## 核心指標框架

### Werner 信用框架（Richard Werner 理論）
> 推動匯率的是**信用數量**，而非利率差

| 指標 | 數據來源 | 判斷邏輯 |
|------|---------|---------|
| 信用乖離率 ∆MF | BIS CRDQJPAPABIS vs JPNNGDP | 信用增速 > GDP 增速 → 非生產性泡沫信用風險 |
| 長期資本外流 | FRED JPNB6FATT01CXCUQ | 資本持續外流且擴大 → 日圓貶值壓力 |
| 民間信用/GDP | BIS vs FRED | 比率上升 → 信用擴張超前實體 |
| 製成品進口 | OECD XTIMVA01JPQ657S | 萎縮 → 內需弱、通縮壓力 |

### 多因子訊號一致性評分
- COT 52週百分位（大戶持倉極端值偵測）
- Fed vs BoJ 資產負債表擴縮比
- RSI(14) 超買超賣
- 技術面均線位置（MA20 / MA50）
- EUR/JPY 確認（排除美元單邊行情）

### 干預風險偵測
自動抓取財務省外匯干預歷史紀錄，計算距上次干預天數與目前匯率位置，在接近歷史干預區間時自動發出警告。

## 技術棧

- **Python 3.13** — 核心邏輯
- **yfinance** — 即時外匯數據
- **requests** — FRED / MOF / CFTC 數據抓取
- **PIL (Pillow)** — 圖片卡生成
- **Gemini CLI** — AI 新聞摘要與 QE 類型判斷
- **Telegram Bot API** — 報告推播
- **GitHub Pages** — HTML 報告托管（深色主題，手機友好）
- **macOS LaunchAgent** — 排程自動執行

## 回測結果

→ 見 `backtest.py` 輸出

## 專案結構

```
投資/
├── jpy_weekly_report.py   # 主程式：數據抓取 + 分析 + 發送
├── build_html_report.py   # HTML 報告生成 + GitHub Pages 推送
├── test_image.py          # PIL 圖片卡生成
├── backtest.py            # 訊號回測模組
├── config.py              # 環境變數讀取
├── run_weekly.sh          # 執行入口腳本
└── .cot_history.json      # COT 歷史資料快取
```

## 自動化設定

```xml
<!-- ~/Library/LaunchAgents/com.jpy.weekly.plist -->
<!-- 每週一 07:00 自動執行，睡眠中也會喚醒 -->
<key>StartCalendarInterval</key>
<dict>
  <key>Weekday</key><integer>1</integer>
  <key>Hour</key><integer>7</integer>
</dict>
```

---

*本報告僅供個人市場觀察，不構成投資建議*
