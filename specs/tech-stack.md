# Tech Stack

## 語言與執行環境

- Python 3。
- Shell wrapper：`run_weekly.sh`。
- 本機排程或手動執行週報流程。

## 主要 Python 套件

- `pandas`：表格資料處理。
- `requests`：HTTP 抓取與 Telegram API。
- `yfinance`：匯率與價格資料。
- `python-dotenv`：讀取 `.env`。
- `Pillow`：報告卡片圖片。
- `pytest` / `unittest`：測試。

## 外部資料源

- yfinance：USD/JPY、EUR/JPY、歷史價格、技術面資料。
- CFTC：COT / TFF。
- FRED：Fed、國際收支、財政與製造業相關資料。
- BoJ / MOF：日銀與日本財務省資料。
- Gemini CLI：短線消息與文字分析。
- ForexFactory 或既有快取：重要行事曆。

## 輸出管線

- Telegram 公開頻道。
- Telegram VIP 頻道。
- Telegram 測試頻道。
- Telegraph 長文。
- GitHub Pages HTML。
- 本機文字週報與報告預覽。

## 架構邊界

- `jpy_weekly_report.py`：主流程編排。
- `data_fetcher.py`：資料抓取與資料語意整理。
- `data_provider.py`：底層資料 provider、FRED/yfinance/MOF 等解析。
- `decision_engine.py`：Werner 四原則判斷引擎。
- `report_builder.py`：報告內容組裝與 Telegram HTML 安全格式。
- `signal_analyzer.py`：AI 短線觀察。
- `telegram_sender.py`：Telegram 發送。
- `build_html_report.py`：HTML 報告與 GitHub Pages。
- `backtest_v1.py` / `backtest.py`：回測與 prediction log。
- `utils.py`：共用工具與文字清理。
- `config.py`：環境變數、路徑與關鍵價位。

## 不可隨意改動的選擇

- Werner 四原則仍是主判斷框架。
- `evaluate_jpy_direction()` 是主力判斷；舊 `decide_jpy_direction()` 保留相容。
- P1 是主因，P2 不可成為主導因子。
- Telegram 發送管線不能因重構中斷。
- `.env`、token、頻道 ID 不應寫入規格或 commit。
- `.gh-pages` 是 embedded git repo，處理時要小心。

## 測試與驗證

優先使用：

```bash
python3 -m pytest
```

必要時可單跑：

```bash
python3 test_decision_engine.py
python3 test_fred_fallback.py
python3 tests/test_combined.py
```

涉及真實發送前，先用 `TG_TEST`。

涉及外部資料源時，要接受網路不穩定，並檢查 fallback 或快取行為。

## 技術債

- `jpy_weekly_report.py` 仍偏大，但目前可接受。
- 測試覆蓋集中在判斷引擎與部分 fallback。
- 部分測試檔同時像測試與手動工具，需要後續整理命名。
- 外部資料源解析容易受網站格式變動影響。
