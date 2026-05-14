# 日圓週報自動化系統

每週自動整合匯率、市場部位、央行資產負債表、國際收支、財政融資、技術面與短線消息，
依 Werner 四原則框架產生 USD/JPY 方向研判報告，並自動發佈。

> 投資研究與參考工具，不提供保證獲利訊號，不自動下單。

---

## 功能特色

- **多源資料整合** — 平行抓取約 14 個資料源（USD/JPY、EUR/JPY、COT、TFF、FRED、BoJ、MOF、經濟行事曆、利差、技術指標等）。
- **Werner 四原則判斷引擎** — P1 信用創造速度為唯一主導因子，P2/P3/P4 為支持/反對，輸出方向、信心與支持/反對來源。
- **資料源容錯** — FRED 三層 fallback、快取與資料源失效告警。
- **多通道發佈** — Telegram 公開版 / VIP 版、報告卡片圖、Telegraph 長文、GitHub Pages HTML。
- **預測回測** — prediction log 與 1 週 / 8 週回測，驗證判斷是否有效。

---

## 技術棧

| 項目 | 技術 |
|---|---|
| 語言 | Python 3.13 |
| 並行 | ThreadPoolExecutor |
| 資料源 | FRED · yfinance · COT · TFF · BoJ · MOF |
| 發佈 | Telegram · Telegraph · GitHub Pages |
| 排程 | GitHub Actions（cron）|

---

## 主流程

```
jpy_weekly_report.main()
├─ data_fetcher      平行抓取約 14 個資料源
├─ decision_engine   Werner 四原則 hierarchical 判斷
├─ signal_analyzer   短線觀察（輔助欄位，非主判斷）
├─ report_builder    組公開版 / VIP 版報告
├─ 發佈              Telegram / Telegraph / GitHub Pages 卡片與長文
└─ backtest          prediction log 與回測回補
```

---

## 執行

```bash
python3 jpy_weekly_report.py    # 跑完整週報主流程
python3 -m pytest               # 測試
```

排程由 GitHub Actions cron 管理（每週一台北時間 07:00）。

---

## Werner 四原則

| 原則 | 角色 |
|---|---|
| P1 信用創造速度 | 唯一可主導方向的因子 |
| P2 干預是否沖銷 | 短期轉折，永不主導，只加減分 |
| P3 信用品質 | 僅支持 / 反對 |
| P4 資本流 vs 經常帳 | 強反對時額外扣分 |
