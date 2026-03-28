## 任務目標
在 jpy_weekly_report.py 報告發送前加入最小法律合規檢查。

## 規格
1. 新增函式 `check_compliance(report_text: str) -> None`
   - 放在 utils.py 的最底部（不新增檔案）
   - 關鍵詞清單：["建議做多", "建議做空", "買進", "賣出", "布局", "目標價", "停損", "進場"]
   - 若 report_text 中出現任何一個關鍵詞，用 logger 印出：
     ⚠️ Compliance Warning: possible investment advice detected
   - 不拋出例外、不中斷流程、不修改 report 內容

2. 在 jpy_weekly_report.py 中：
   - import check_compliance from utils
   - 在 report 變數組好之後、send_public_report 之前，呼叫 check_compliance(report)
   - 不改其他任何邏輯

## 禁止
- 不改 report_builder.py
- 不改 telegram_sender.py
- 不改 decision_engine.py
- 不新增新檔案

## 驗收條件
- python3 -c "from utils import check_compliance; check_compliance('買進日圓')" 執行不報錯
- python3 -m py_compile jpy_weekly_report.py 通過

## Codex 結果
狀態：完成
