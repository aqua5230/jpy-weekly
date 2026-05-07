# 投資專案 Session 狀態

更新日期：2026-05-08

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
| 驗證 | 建立遠端 one-shot routine `trig_012ykMYChfm4Xjzboz7cEmPi`，4/27 08:00 Asia/Taipei WebFetch GitHub Pages 驗證；prompt 結尾自帶刪除連結避免清單堆疊 | - |

## 本 Session 完成（2026-05-08）
| # | 任務 | Commit |
|---|------|--------|
| B1 | 修 `backtest_v1.py` 的 `resolve_pending_predictions` 週末 bug：1 週 / 8 週結算改為從目標日起往後找最多 7 天的第一個交易日，並記錄 `next_1w_resolved_date` / `next_8w_resolved_date` | - |
| B1 | 新增 feature spec：`specs/features/backtest-resolve-weekend-fallback.md` | - |
| B1 | 驗證：`python3 backtest_v1.py`、`python3 -m py_compile backtest_v1.py`、`python3 -m pytest test_decision_engine.py test_fred_fallback.py` 通過；`ruff` 未安裝故略過 | - |

## 目前狀態
**2026-05-04：GitHub Actions cron 首次自動觸發成功**（run 25294398452，1m19s 跑完，UTC 週日 23:51 觸發），V2 驗收通過。連同 5/2 手動觸發（25248212710）共兩次成功，雲端排程穩定。

**2026-05-02：週報排程已從本機 launchd 切換到 GitHub Actions cron**，雲端 workflow 首次手動觸發成功（run 25248212710，1m44s 跑完），TG 訊息／GitHub Pages／prediction log 三條輸出皆驗證通過。下次自動觸發：2026-05-04（週一）07:00 Asia/Taipei（UTC 週日 23:00）。

歷史漏跑紀錄：4/12 週報為最後一次本機成功跑（手動）；4/13、4/20、4/27 三個週一本機 launchd 在系統 awake 狀態下仍 0 次觸發（`runs=0`），確認 macOS user agent calendar trigger 不可靠，故全面雲端化。

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
| C1 | V2 已通過，可 `sudo pmset repeat cancel` 移除已無用的本機週一 wake | 低 |
| C2 | 月級資源回收：本機 `run_weekly.sh`、`com.jpy.weekly.plist`、`com.jpy.monitor.plist` 可在雲端穩定跑 4-6 週後刪除 | 低 |

## 風險
- FRED API 偶爾 timeout（D1 fallback 已有三層）；雲端 runner 首次跑無快取，但 `.cot_history.json` 等已 commit 進 main 由 `git-auto-commit-action` 跨 run 持久化，5/2 已驗證
- DeepSeek API 額度／網路：失敗回 fallback_text（保留報告 7 段格式），不會讓主流程掛掉
- gh-pages branch 由 peaceiris 強制覆蓋，**不要手動編輯 gh-pages branch**，所有改動會被下次 workflow 蓋掉
- main branch 會被 git-auto-commit-action push `data: weekly run YYYY-MM-DD [skip ci]` commit，本地長期不開機要 `git pull` 同步
- 本機 `com.jpy.weekly`、`com.jpy.monitor` 都已 `launchctl disable + bootout`；plist 檔案保留供日後參考，OS 重 login 不會自動回來

## Telegram 頻道
| 用途 | 環境變數 | ID |
|------|---------|-----|
| 公開 | TG_PUBLIC | -1003598327129 |
| VIP  | TG_VIP   | -1003801733194 |
| 測試 | TG_TEST  | -1003777384993 |

## 對外網址
- GitHub Pages：https://aqua5230.github.io/jpy-weekly/（5/2 改由 GitHub Actions / `peaceiris/actions-gh-pages@v3` 推到 gh-pages branch）
- GitHub repo：https://github.com/aqua5230/jpy-weekly
- Workflow：https://github.com/aqua5230/jpy-weekly/actions/workflows/jpy_weekly.yml
- Telegraph：每次跑產新的
