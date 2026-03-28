## 任務目標
統一 report_builder.py 中 _format_verdict 的輸出格式。
不改內容，只改排版：所有段落統一為「▪️ 標題\n內容」格式。

## 目前問題
_format_verdict 現在輸出：
  ▪️ 總結　本週日圓偏弱   ← 標題與內容同一行（全形空格分隔）
  理由：利差擴大           ← inline 標籤，不是 ▪️ 格式
  風險：⚠️ 本段為公開數據整理  ← 同上

## 要求
修改 _format_verdict 函式（report_builder.py），改動如下：

1. 所有 replacements 的 target 改為 "\n▪️ 標題\n" 格式（標題後換行，不用全形空格）：
   "【數據觀察摘要】" → "\n▪️ 總結\n"
   "【央行在做什麼】"   → "\n▪️ 央行\n"
   "【利率差距說什麼】" → "\n▪️ 利差\n"
   "【大戶在做什麼】"   → "\n▪️ 大戶\n"
   "【這週要盯什麼】"   → "\n▪️ 下週觀察\n"
   "【本週指標整理】"   → ""（保持空字串，內容保留）

2. 在 replacements 之後，加上這兩個替換（處理 inline 標籤）：
   text = re.sub(r'理由：', '\n▪️ 理由\n', text)
   text = re.sub(r'風險：', '\n▪️ 風險\n', text)

3. 保留現有的 re.sub(r'\n{3,}', '\n\n', text) 清除多餘空行
4. 保留 return text.strip()

## 禁止
- 不改其他函式
- 不改 signal_analyzer.py
- 不改 telegram_sender.py
- 不改 decision_engine.py

## 驗收條件
python3 -c "
from report_builder import _format_verdict
t = '【數據觀察摘要】本週日圓偏弱\n理由：利差擴大\n風險：⚠️ 本段為公開數據整理\n【央行在做什麼】縮表\n【這週要盯什麼】注意160'
r = _format_verdict(t)
assert '▪️ 總結\n' in r, '總結格式錯誤'
assert '▪️ 理由\n' in r, '理由格式錯誤'
assert '▪️ 風險\n' in r, '風險格式錯誤'
assert '▪️ 央行\n' in r, '央行格式錯誤'
assert '▪️ 下週觀察\n' in r, '下週觀察格式錯誤'
print('PASS')
print(r)
"

## Codex 結果
狀態：完成
