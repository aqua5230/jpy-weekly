# 測試分類

## 動機

`tests/` 與 repo root 的 `test_*.py` 命名混雜：
- 有真正的 pytest 單元測試
- 有命名為 `test_*` 但實際是主流程依賴的工具模組
- 有會真的發送訊息的手動整合測試

本文件釐清各類用途與安全跑法，避免誤跑或誤刪。

## 1. 單元測試（Unit）— 安全自動跑

| 檔案 | 涵蓋 | 跑法 |
|---|---|---|
| `test_decision_engine.py` | `evaluate_jpy_direction()` 6 個邊界 case | `python3 -m pytest test_decision_engine.py` |
| `test_fred_fallback.py` | `get_cb_balance_sheets()` 三層 fallback（用 `mock.patch`） | `python3 -m pytest test_fred_fallback.py` |

`python3 -m pytest` 預設會收這兩檔（pytest 9.0.2 / 7 cases collected，2026-05-08 驗證）。無外部依賴、可放心進 CI。

## 2. 工具模組（誤命名為 `test_*`）— **不是測試**

| 檔案 | 真實用途 | 主流程引用 |
|---|---|---|
| `test_image.py` | 產報告卡片 PNG（`draw_card`） | `jpy_weekly_report.py:30` `from test_image import draw_card` |
| `test_telegraph.py` | Telegraph 發文 + 取連結 | `jpy_weekly_report.py:31` `from test_telegraph import create_telegraph_account, publish_to_telegraph, build_nodes` |

這兩檔是主流程依賴，**不是測試**。pytest 預設不會收（檔內無 `test_*` 函式或 `Test*` class），但檔名易誤導。

未來若 rename 為 `card_renderer.py` / `telegraph_publisher.py`，需同步改 `jpy_weekly_report.py:30-31` 與 `tests/test_combined.py:9-10` 的 import。視為 backlog（非急迫）。

## 3. 手動整合測試（會真發訊息）— **不可自動跑**

| 檔案 | 行為 | 跑法 |
|---|---|---|
| `tests/test_combined.py` | 產卡片圖 + 發 Telegraph + 發 Telegram TG_PUBLIC | `python3 tests/test_combined.py`（直接 run，不是用 pytest） |

**跑前務必把 `TG_PUBLIC` 暫時指向 `TG_TEST` 的 chat_id**，否則會送到正式公開頻道。

## CI 跑哪些

- GitHub Actions `jpy_weekly.yml` 跑的是 `jpy_weekly_report.py` 主流程，**不跑 pytest**。
- 主流程出錯由 `send_data_health_alert` 推 `TG_DEV` 告警。
- 本地開發跑 pytest：

```bash
# 全部單元測試（快、無外部依賴）
python3 -m pytest

# 單跑特定 case
python3 -m pytest test_decision_engine.py::TestEvaluateJpyDirection::test_case_1_p1_strong_rise_all_support
```

## 已知缺口

- 沒有整合測試覆蓋 `data_fetcher` 對真實外部 API 的呼叫（FRED / yfinance / Gemini）— 由 TG_TEST 人工驗證承擔風險
- 沒有 e2e 測試覆蓋 `jpy_weekly_report.main()` 完整路徑
- 沒有自動化覆蓋 `report_builder` / `build_html_report` 的 HTML 輸出
- backlog：`Gemini CLI 呼叫的 timeout / 模型 / fallback 規格`（見 `specs/backlog.md`）
