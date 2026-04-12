# 投資專案 Session 狀態

更新日期：2026-04-12

## 專案目標
日圓週報自動化系統 + Werner 四原則判斷引擎

## 已完成模組
- `jpy_weekly_report.py`：週報主流程（381行）
- `decision_engine.py`：Werner 四原則判斷引擎
  - `decide_jpy_direction()`：舊投票制（保留）
  - `evaluate_jpy_direction()`：新 hierarchical model（主力）
- `data_provider.py`：FRED / yfinance 資料抓取（含 fallback_used 標記）
- `data_fetcher.py`：20 個資料抓取函式（含 D1 FRED 三層 fallback）
- `build_html_report.py`：HTML 報告 + GitHub Pages 推送
- `telegram_sender.py`：Telegram 發送（公開 / VIP / 緊急）
- `report_builder.py`：報告組裝（含 ▪️ 格式短線觀察、_format_verdict）
- `signal_analyzer.py`：ChatGPT 短線觀察
- `utils.py`：共用工具（含 check_compliance、clean_gemini_output 白名單）
- `backtest_v1.py`：回測框架（週回測 1w+8w + R6 持有型回測）
- `config.py`：集中設定（含 TG_TEST）
- Git repo（多 commits）
- TG_TEST 測試頻道（ID: -1003777384993）

## 本 Session 完成
| # | 任務 | Commit |
|---|------|--------|
| Bug | jpy_weekly_report.py syntax error（3行被錯誤 comment） | 37db5d9 |
| 設定 | config.py 補上 TG_TEST | 37db5d9 |
| 新增 | backtest_predictions.json 初始化納入 git 追蹤 | 37db5d9 |
| Bug | Gemini 呼叫補 --model gemini-2.5-pro（修逾時） | - |
| Bug | price_lookup 補 60 天歷史，回測結算不再永遠 0 筆 | - |

## 目前狀態
4/12 週報已產出並推送（公開 + VIP）。兩個功能性 bug 已修，尚未 commit。

## 尚未開始
| # | 任務 | 優先度 |
|---|------|--------|
| R1 | 重構 jpy_weekly_report.py → 多模組（已有計畫） | 低（目前 381 行可接受） |
| T1 | evaluate_jpy_direction 邊界測試補強 | 中 |

## 風險
- FRED API 偶爾 timeout（D1 fallback 已有三層，但首次跑無快取）
- 重構過程中 Telegram 發送不能中斷
- `.gh-pages` 是 embedded git repo，需注意

## Telegram 頻道
| 用途 | 環境變數 | ID |
|------|---------|-----|
| 公開 | TG_PUBLIC | -1003598327129 |
| VIP  | TG_VIP   | -1003801733194 |
| 測試 | TG_TEST  | -1003777384993 |

## 對外網址
- GitHub Pages：https://aqua5230.github.io/jpy-weekly/
- Telegraph：每次跑產新的（最近：https://telegra.ph/日圓週報-2026年03月28日-03-28-10）
