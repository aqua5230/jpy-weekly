# Backlog

此檔放暫時不進 roadmap 的想法。

避免臨時研究污染當前功能。

## 待整理

- 整理測試檔命名（語意化）：`test_image.py` → `card_renderer.py`、`test_telegraph.py` → `telegraph_publisher.py`。pytest 預設不會誤抓（已驗證），純語意化；rename 會動 `jpy_weekly_report.py:30-31` 與 `tests/test_combined.py:9-10` 主流程 import，動前先評估時機（建議避開雲端 cron 跑前後）。
- `evaluate_jpy_direction()` 中 P1=「中性」時，所有非中性的 P2/P3/P4 會被歸入 `opposing`（因為實作以 `direction == p1_direction` 判斷支持，「升 != 中性」「貶 != 中性」一律走 else 分支）。語意上「中性」沒有支持/反對可言，是否要把 P1 中性視為例外、`supporting / opposing` 都回空陣列待釐清。動實作前先寫 feature spec；現行行為已被 `test_case_7_p1_neutral_keeps_neutral_conclusion` 鎖定。
- 為 Gemini CLI 呼叫建立更清楚的 timeout、模型與 fallback 規格。
- 檢查 `.gh-pages` embedded repo 的安全操作流程。
- 將資料源健康狀態做成週報附錄或內部 debug 摘要。
- 將回測統計做成獨立報告，不一定放進公開週報。
- 研究是否要加入 changelog，但先不要引入太重流程。
- `test_decision_engine.py` 補強（Gemini 2026-05-08 審查建議）：補「貶」方向的鏡像 case；`test_case_8` 移除冗餘的 `len(opposing)==2` 斷言；`test_case_10` 把 `assertIn("P2", opposing)` 改成 `assertEqual(opposing, ["P2"])` 以鎖定 P3/P4 中性時不該入 opposing。

## 暫不做

- 自動交易。
- 大型資料庫。
- 多使用者後台。
- Web app 化。
- 更換整套報告發送平台。
