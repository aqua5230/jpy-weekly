# Task Log

## Step 0｜初始化 2026-03-28

### 完成項目
| # | 任務 | 狀態 |
|---|------|------|
| 1 | 建立 decision_engine.py（投票制） | ✅ |
| 2 | 整合 Werner 判斷進週報流程 | ✅ |
| 3 | Git repo 初始化 + .gitignore | ✅ |
| 4 | 改為 hierarchical model | ✅ |
| 5 | 補強強度數值化（STRENGTH_VALUE） | ✅ |
| 6 | Gemini 雙層審查（含 bug 修正） | ✅ |

---

## Step 1｜Phase 1 重構 + 回測框架 2026-03-28

### 完成項目
| # | 任務 | 狀態 |
|---|------|------|
| P1 | jpy_weekly_report.py 拆分 → 6 個模組 | ✅ |
| D1 | FRED timeout 三層 fallback | ✅ |
| D1.1 | test_fred_fallback.py | ✅ |
| T1 | test_decision_engine.py 邊界測試（6 cases） | ✅ |
| R2 | 決策輸出統一（Werner 主 / signal 輔） | ✅ |
| R3 | 行動建議層（Action Layer） | ✅ |
| R4 | Position Scoring | ✅ |
| R5 | 最小回測框架 v1 | ✅ |
| R5.2 | 多筆回測 + 統計 | ✅ |
| R5.3 | Prediction Log | ✅ |
| R5.4 | resolve_pending_predictions | ✅ |
| R5.5 | 自動結算 + 自動記錄整合進主流程 | ✅ |
| R5.7 | 多週期回測（1週 + 8週） | ✅ |
| R6 | 持有型回測 holding_backtest | ✅ |

---

## Step 2｜報告優化 + Bug 修正 2026-03-28

### 完成項目
| # | 任務 | 狀態 |
|---|------|------|
| TG_TEST | 測試頻道設定 + 驗證 | ✅ |
| BUG | now.strftime / date 參數名 / TG_VIP import / HTML br | ✅ |
| 精簡 | 移除訊號一致性 + 短線觀察重複段 | ✅ |
| 合規 | check_compliance 關鍵詞偵測 | ✅ |
| 格式 | 短線觀察 ▪️ 標記 + 換行統一 | ✅ |
| COT | 近8週趨勢改文字格式 | ✅ |
| 污染 | clean_gemini_output 改白名單策略 | ✅ |

---

## Step 3｜規格驅動整理 2026-04-17

### 完成項目
| # | 任務 | 狀態 |
|---|------|------|
| SDD | 建立 Project Constitution：mission / tech-stack / roadmap | ✅ |
| SDD | 建立 backlog，收納暫不進 roadmap 的想法 | ✅ |
| SDD | 建立 feature spec 範本 | ✅ |
| SDD | 建立 AGENTS.md，讓不同 AI agent 可依同一規則啟動 | ✅ |

### 尚未開始
| # | 任務 | 優先度 |
|---|------|--------|
| S1 | 測試基線整理與測試分類 | 中 |
| R1 | 重構 jpy_weekly_report.py → 多模組 | 低 |
| T1 | evaluate_jpy_direction 邊界測試補強 | 中 |

---

## Step 4｜排程修復 2026-04-24

### 背景
- 4/13、4/20 兩個週一 07:00 週報均未觸發，無報告產出、無 TG 發送。
- 診斷結果：cron 與 launchd 雙軌存在；其他 cron job（539、obsidian）昨晚有成功觸發 → cron daemon 正常；`/tmp/投資_weekly.log` 不存在 + `pmset -g sched` 空白 → 主因為 Mac 週一早上 07:00 在睡眠。
- 另發現 launchd plist `com.jpy.weekly.plist` 有 4 個問題：缺 `LANG`、路徑含中文、log 寫中文目錄、硬寫 `TG_PUBLIC=788583690`（個人 user ID）。

### 完成項目
| # | 任務 | 狀態 |
|---|------|------|
| SCH | 建立英文 symlink `~/jpy-weekly -> /Users/lollapalooza/Desktop/投資` | ✅ |
| SCH | 重寫 `com.jpy.weekly.plist`：加 `LANG`/`LC_ALL`/`PATH`、log 改 `/tmp/jpy_weekly.{log,err}`、移除硬寫 TG 憑證、`RunAtLoad=false`、保留 `WakeForJob=true` | ✅ |
| SCH | 備份舊 plist 為 `com.jpy.weekly.plist.bak.20260424` | ✅ |
| SCH | `launchctl unload` + `launchctl load -w` 重新註冊 | ✅ |
| SCH | 移除 crontab 裡的日圓週報重複條目（保留 539/obsidian） | ✅ |

### 尚未開始
| # | 任務 | 優先度 |
|---|------|--------|
| M1 | 修 `com.jpy.monitor`（last exit 78；同樣需 source `.env`、TG_PUBLIC 改頻道 ID） | 中 |
| V1 | 2026-04-27 週一首次自動觸發驗證 | 高 |

---

## Step 5｜Token 輪替 + 排程保險 2026-04-25

### 背景
- 檢視 launchd 狀態時發現 `com.jpy.monitor.plist` 明文硬寫 TG_TOKEN 與 `TG_PUBLIC=788583690`（個人 user ID），等同 token 外洩。
- `launchctl list` 顯示 `com.jpy.monitor` last exit 78；`com.jpy.weekly` last exit 0。
- `pmset -g sched` 空白 → 無系統 wake schedule，只靠 plist 的 `WakeForJob=true`，是 4/13、4/20 漏跑的殘留風險。

### 完成項目
| # | 任務 | 狀態 |
|---|------|------|
| SEC | BotFather `/revoke` 舊 token、`/token` 取得新 token，寫進 `.env`（`com.jpy.weekly` 靠 `run_weekly.sh` source 自動生效） | ✅ |
| SEC | `getMe` 驗證新 token（bot=`@JPY888_bot`）、`sendMessage` 到 TG_TEST 成功（message_id=32） | ✅ |
| SCH | `launchctl unload ~/Library/LaunchAgents/com.jpy.monitor.plist`，止血每小時 exit 78 與個人 ID 誤發 | ✅ |
| SCH | `sudo pmset repeat wakeorpoweron M 06:55:00`，系統週一 06:55 主動喚醒 | ✅ |
| SCH | `pmset -g sched` 確認顯示 `wakepoweron at 6:55AM Monday` | ✅ |
| DOC | 建立 `CLAUDE.md`：啟動必讀順序、常用指令、高階架構、Werner 四原則、排程設定、硬規則 | ✅ |

### 尚未開始
| # | 任務 | 優先度 |
|---|------|--------|
| V1 | 2026-04-27 週一首次自動觸發驗證 | 高 |
| M1 | 重寫 `com.jpy.monitor.plist`（加 WorkingDirectory / LANG / PATH、log 改 /tmp、token 走 `.env`）。下次 OS 登入 plist 會重新被 load，屆時又會 exit 78；若未及時修，改用 `launchctl unload -w` 永久停用 | 中 |
