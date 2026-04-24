# Roadmap

## 原則

- 每次只做一個清楚階段。
- 規格階段和實作階段分開。
- 大改動先寫 feature spec。
- 完成功能後同步檢查 spec、測試與 roadmap。
- 不自動 push。

## Phase 0：專案憲法補齊

狀態：進行中。

目標：

- 建立 `specs/mission.md`。
- 建立 `specs/tech-stack.md`。
- 建立 `specs/roadmap.md`。
- 建立 `specs/backlog.md`。
- 建立 feature spec 範本。

驗收：

- 新 session 可先讀 `SESSION.md` 與 `specs/` 了解專案。
- 不需要讀完整歷史對話就能知道下一步。

## Phase 1：測試基線整理

狀態：待開始。

目標：

- 確認目前 `python3 -m pytest` 是否穩定。
- 記錄需要真實環境變數或網路的測試。
- 區分單元測試、整合測試、手動發送測試。

驗收：

- 有一份清楚的測試指令清單。
- 不會把會發 Telegram 的流程誤當一般單元測試。
- 測試失敗時能判斷是程式錯、環境缺、還是外部資料源錯。

## Phase 2：evaluate_jpy_direction 邊界測試補強

狀態：待開始。

目標：

- 補強 Werner 四原則主力模型的邊界測試。
- 特別覆蓋 P1 中性、P1 弱、P4 強反對、P2 不可主導等情境。

驗收：

- 新增測試能明確保護 `evaluate_jpy_direction()` 的設計。
- 不改變現有報告輸出，除非 spec 先更新。

## Phase 3：主流程重構評估

狀態：低優先。

目標：

- 評估是否需要再拆 `jpy_weekly_report.py`。
- 只在降低維護成本明顯時才重構。
- 重構不可中斷 Telegram、Telegraph、GitHub Pages 與 prediction log。

驗收：

- 先有 feature spec。
- 每次只拆一組功能。
- 每一步都能跑測試或用測試頻道驗證。

## Phase 4：資料源可靠性強化

狀態：待排程。

目標：

- 統一資料源失敗格式。
- 明確標記 fallback_used。
- 補強首次無快取時的錯誤訊息。

驗收：

- 資料源失敗不會造成報告靜默污染。
- 告警能指出失敗資料源與原因。

## Phase 5：回測報告化

狀態：待排程。

目標：

- 將 prediction log 的結果整理成可讀摘要。
- 區分 1 週、8 週、持有型回測。
- 避免回測結果干擾當週主判斷。

驗收：

- 回測結果可被週報引用或人工審查。
- 仍保留投資風險提示。
