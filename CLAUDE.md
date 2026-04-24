# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 啟動必讀順序

1. `SESSION.md` — 目前狀態、本輪已完成、下一步、禁區
2. `AGENTS.md` — 跨 agent 共用規則（不自動 push、不自動刪檔、不碰無關檔案）
3. `specs/mission.md`、`specs/tech-stack.md`、`specs/roadmap.md` — 專案憲法
4. `specs/features/*.md`（若有對應功能）
5. 才讀實作程式碼

未讀 `SESSION.md` 不得改程式。結束 session / context 快滿前必須回寫 `SESSION.md` 與 `TASK_LOG.md`。

## 常用指令

```bash
# 跑整個週報主流程（會實際發 Telegram、推 GitHub Pages、寫 prediction log）
python3 jpy_weekly_report.py

# 正式排程入口（由 launchd 呼叫，source .env、寫 .report.log、失敗告警到 TG_DEV）
./run_weekly.sh

# 測試
python3 -m pytest                   # 優先
python3 test_decision_engine.py     # 判斷引擎 6 個邊界 case
python3 test_fred_fallback.py       # FRED 三層 fallback
python3 tests/test_combined.py      # 圖片卡片 + Telegraph（會真的發訊息）

# 單跑一個 pytest 測試
python3 -m pytest test_decision_engine.py::TestEvaluateJpyDirection::test_case_1_p1_strong_rise_all_support
```

Python 版本：3.13（跟 launchd plist 內 PATH 對齊）。

## 高階架構

主流程是 `jpy_weekly_report.py`（約 380 行），單一 `main()` 以 `ThreadPoolExecutor` 平行抓約 14 個資料源，再依 Werner 四原則做判斷、組報告、發送：

```
jpy_weekly_report.main()
├─ data_fetcher.*              抓資料（USD/JPY、COT、TFF、FRED、BoJ、MOF、行事曆、利差、RSI、央行資產負債表…）
│   └─ data_provider.*         底層 provider（FRED 三層 fallback、yfinance、MOF 解析）
├─ decision_engine
│   ├─ decide_jpy_direction()  舊投票制（保留相容）
│   └─ evaluate_jpy_direction() 主力 hierarchical：P1 主導、P2 永不主導、輸出 supporting/opposing/score
├─ signal_analyzer.get_weekly_verdict()   Gemini CLI 短線觀察（輔助、非主判斷）
├─ report_builder.*            組 Telegram 公開版 / VIP 版 HTML，走白名單 escape
├─ test_image.draw_card        產報告卡片 PNG（.report_card.png）
├─ test_telegraph.*            發 Telegraph 長文
├─ build_html_report.*         產 HTML + 推 GitHub Pages（.gh-pages 是 embedded git repo）
├─ telegram_sender.*           發公開 / VIP / 緊急
├─ backtest_v1.*               log_prediction、resolve_pending_predictions（60 天 yfinance 歷史回補價格）
└─ utils.check_compliance      關鍵字合規偵測、clean_gemini_output 白名單
```

`config.py` 集中所有 env、路徑、關鍵價位（`DANGER_HIGH=162 / DANGER_MID=160 / DANGER_WARN=156`）。`.env` 至少要有 `TG_TOKEN`、`TG_PUBLIC`（啟動即檢查），可選 `TG_VIP`、`TG_TEST`、`TG_DEV`。

### Werner 四原則心智模型

- P1：信用創造速度 — **唯一可作主方向的因子**
- P2：干預是否沖銷 — 短期轉折，**永不主導**，只加減分
- P3：信用品質 — 僅 supporting / opposing
- P4：資本流 vs 經常帳 — 強反對時額外扣 1 分
- `evaluate_jpy_direction()` 結論固定以 P1 方向為主，只有 P1 弱且 P2/P3/P4 全反對才翻成中性。改動這個函式前務必跑 `test_decision_engine.py` 六個 case。

### 資料源 fallback

`collect_data_source_result()` 把所有 future 失敗收到 `data_failures`，最後由 `send_data_health_alert()` 處理；FRED 走三層 fallback，首次執行無快取時特別脆弱。

## 專案硬規則（不要破壞）

- **發送管線不能在重構途中中斷**：Telegram / Telegraph / GitHub Pages / prediction log 四條輸出都屬於對外承諾
- **`.gh-pages` 是 embedded git repo**，操作前先確認狀態；它已在 `.gitignore`
- **P2 不可成為主導因子**，`evaluate_jpy_direction()` 結論必須跟著 P1
- **AI 短線觀察不是主判斷**，`signal_analyzer` 只是輔助欄位
- **真實發送前先用 `TG_TEST`**（ID 在 `SESSION.md`，不要寫進公開文件／commit）
- `.env`、token、頻道 ID 不得入 commit（`.gitignore` 已擋 `.env`、`.telegraph_token`）
- 大型重構要先在 `specs/features/` 寫 feature spec，不臨時起意

## 排程

由 launchd 單軌管理（cron 已移除週報條目）：

- plist：`~/Library/LaunchAgents/com.jpy.weekly.plist`（`WakeForJob=true`、`LANG=zh_TW.UTF-8`）
- 執行入口：英文 symlink `~/jpy-weekly -> /Users/lollapalooza/Desktop/投資`（避開中文路徑）
- log：`/tmp/jpy_weekly.log` + `/tmp/jpy_weekly.err`
- 觸發：每週一 07:00；若睡眠漏跑會在下次喚醒補跑
- 憑證靠 `run_weekly.sh` 自己 source `.env`，**不要**把 token 硬寫進 plist
- 另有 `com.jpy.monitor` 目前壞的（last exit 78，TG_PUBLIC 寫成個人 user ID），修它前對照 `com.jpy.weekly.plist` 的修法

## 跟 Claude 協作的本地約定

- 寫程式交給 Codex，研究交給 Gemini，文案交給 ChatGPT（見使用者全域 CLAUDE.md）
- 派 Codex 前寫任務書（角色／目標／位置／禁區／停損／成功標準／自我審查）並**輸出給使用者自己貼**，不要用 Bash 自動 `codex exec`
- 禁止用 `Agent` 工具派 Codex / Gemini（雙倍計費）
- 完成一個功能後同步檢查：`SESSION.md` / `TASK_LOG.md` / `specs/roadmap.md` / 對應 `specs/features/*.md`
