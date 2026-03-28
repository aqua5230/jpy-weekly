## 任務目標
優化 report_builder.py 中「短線觀察」的閱讀格式。
不改內容邏輯，只改 _trim_verdict → _format_verdict。

## 規格

在 report_builder.py 中：

1. 移除 _REDUNDANT_VERDICT_TAGS 和 _trim_verdict 函式

2. 新增 _format_verdict(text: str) -> str 函式（替換位置相同）：
   - 把 verdict 文字中的【...】標籤換成 ▪️ 標記
   - 對應表：
     【數據觀察摘要】 → 換成 "\n▪️ 總結　"
     【央行在做什麼】 → 換成 "\n▪️ 央行　"
     【利率差距說什麼】 → 換成 "\n▪️ 利差　"
     【大戶在做什麼】 → 換成 "\n▪️ 大戶　"
     【這週要盯什麼】 → 換成 "\n▪️ 下週觀察　"
     【本週指標整理】 → 換成 "" (空字串，省略此標籤，內容保留)
   - 最後 re.sub(r'\n{3,}', '\n\n', text) 清除多餘空行
   - return text.strip()

3. build_full_report 中：
   - 把 trimmed_verdict = _trim_verdict(verdict) if verdict else ""
   - 改成 trimmed_verdict = _format_verdict(verdict) if verdict else ""

## 禁止
- 不改 signal_analyzer.py（prompt 不動）
- 不改 telegram_sender.py
- 不改 decision_engine.py
- 不改其他任何函式

## 驗收條件
- python3 -m py_compile report_builder.py 通過
- python3 -c "
from report_builder import _format_verdict
t = '【數據觀察摘要】偏弱\n理由：利差\n風險：⚠️\n【央行在做什麼】縮表\n【這週要盯什麼】160關口'
print(_format_verdict(t))
" 輸出包含 ▪️ 總結 和 ▪️ 央行 和 ▪️ 下週觀察

## Codex 結果
狀態：完成
