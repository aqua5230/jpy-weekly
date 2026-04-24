# 投資專案 Session 狀態

更新日期：2026-04-25

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

## 本 Session 完成（2026-04-25）
| # | 任務 | Commit |
|---|------|--------|
| 文件 | 建立 `CLAUDE.md`（啟動必讀順序、架構、硬規則、排程） | - |
| 安全 | 舊 TG_TOKEN 明文外洩於 `com.jpy.monitor.plist` → BotFather revoke + 輪替新 token 寫進 `.env` | - |
| 驗證 | 新 token `getMe` + 發送 `TG_TEST` 訊息雙重驗證通過 | - |
| 排程 | `launchctl unload com.jpy.monitor.plist`（止血 exit 78 錯發個人 user ID） | - |
| 排程 | `sudo pmset repeat wakeorpoweron M 06:55:00`（4/27 週一 launchd 保險：系統先醒 5 分再讓 07:00 job 觸發） | - |

## 目前狀態
4/12 週報已產出並推送（公開 + VIP）。4/13 及 4/20 週一 07:00 均未觸發（排程問題，見下方）。

2026-04-17 已開始導入規格驅動開發：
- 新增 `AGENTS.md` 作為跨 agent 專案規則。
- 新增 `specs/mission.md`、`specs/tech-stack.md`、`specs/roadmap.md`。
- 新增 `specs/backlog.md` 與 feature spec 範本。
- 後續大型功能需先建立 feature spec，再實作。

2026-04-24 修復週報自動排程：
- 根因：cron 與 launchd 雙軌存在；launchd `com.jpy.weekly.plist` 缺 LANG、路徑含中文、log 也寫中文目錄；Mac 週一 07:00 睡眠時未被喚醒。
- 改走 launchd 單軌，crontab 裡的重複週報行已移除。
- plist 改用英文 symlink `~/jpy-weekly -> /Users/lollapalooza/Desktop/投資`，加 `LANG=zh_TW.UTF-8`、`LC_ALL`、完整 `PATH`（含 python3.13）、`WakeForJob=true`、`RunAtLoad=false`。
- log 改為 `/tmp/jpy_weekly.log` + `/tmp/jpy_weekly.err`。
- 移除 plist 裡硬寫的 TG_TOKEN / TG_PUBLIC（錯用個人 user ID），統一靠 `run_weekly.sh` 自行 source `.env`。
- 舊 plist 備份於 `~/Library/LaunchAgents/com.jpy.weekly.plist.bak.20260424`。
- 下次觸發：2026-04-27（週一）07:00；若睡眠漏跑，launchd 會在下次喚醒補跑。

2026-04-25 token 輪替 + 排程保險：
- 發現 `com.jpy.monitor.plist` 內含舊 TG_TOKEN 明文（`8672356224:AAFY...`）與錯誤的 `TG_PUBLIC=788583690`（個人 user ID），視為外洩。
- BotFather `/revoke` 舊 token，`/token` 取得新 token，只寫入 `.env`，plist 不再硬編。
- 驗證：`getMe` 確認新 token 對應 `@JPY888_bot`；`sendMessage` 到 TG_TEST 頻道成功（message_id=32）。
- `launchctl unload com.jpy.monitor.plist`：runtime 層先卸載，停止每小時 exit 78 的無聲失敗與可能的個人訊息誤發；plist 檔案保留，M1 修復時統一重寫。
- 補 `sudo pmset repeat wakeorpoweron M 06:55:00`：系統在週一 06:55 主動喚醒，給 launchd 5 分鐘熱機後 07:00 觸發週報。`pmset -g sched` 已顯示 `wakepoweron at 6:55AM Monday`。
- 下次驗證窗口仍為 2026-04-27（週一）07:00。

## 尚未開始
| # | 任務 | 優先度 |
|---|------|--------|
| S1 | 測試基線整理與測試分類 | 中 |
| R1 | 重構 jpy_weekly_report.py → 多模組（已有計畫） | 低（目前 381 行可接受） |
| T1 | evaluate_jpy_direction 邊界測試補強 | 中 |
| M1 | 重寫 `com.jpy.monitor.plist`（已 runtime unload；待比照 weekly plist 加 WorkingDirectory/LANG/PATH、log 改 /tmp、token 走 `.env`） | 中 |
| V1 | 4/27 週一首次自動觸發驗證，檢查 `/tmp/jpy_weekly.log`（已補 pmset 保險） | 高 |

## 風險
- FRED API 偶爾 timeout（D1 fallback 已有三層，但首次跑無快取）
- 重構過程中 Telegram 發送不能中斷
- `.gh-pages` 是 embedded git repo，需注意
- `com.jpy.monitor.plist` 已 runtime unload；plist 檔案仍保留舊已失效 token 與錯誤 chat_id，M1 修復時一併清除（下次 OS 登入會重新 load，屆時又會 exit 78，所以 M1 在此之前要完成，或改為 `launchctl unload -w` 永久停用）

## Telegram 頻道
| 用途 | 環境變數 | ID |
|------|---------|-----|
| 公開 | TG_PUBLIC | -1003598327129 |
| VIP  | TG_VIP   | -1003801733194 |
| 測試 | TG_TEST  | -1003777384993 |

## 對外網址
- GitHub Pages：https://aqua5230.github.io/jpy-weekly/
- Telegraph：每次跑產新的（最近：https://telegra.ph/日圓週報-2026年03月28日-03-28-10）
