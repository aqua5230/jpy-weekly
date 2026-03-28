## 任務目標
修改 data_fetcher.py 中「近8週趨勢」的顯示格式。
不改其他邏輯，只改這一段輸出文字。

## 目前程式碼位置
data_fetcher.py，get_cot_with_history 函式內，近第 249–260 行：

```python
recent = history[-8:]
if recent:
    SPARKS = "▁▂▃▄▅▆▇█"
    vals = [item["net_short"] for item in recent]
    min_v, max_v = min(vals), max(vals)
    if max_v == min_v:
        spark = "▄" * len(vals)
    else:
        indices = [int((v - min_v) / (max_v - min_v) * 7) for v in vals]
        spark = "".join(SPARKS[idx] for idx in indices)

    latest_val = history[-1]["net_short"]
    direction_label = "多頭" if latest_val > 0 else "空頭"
    analysis += f"\n近8週趨勢：{spark}  本週 {direction_label} {abs(latest_val):,} 口"
```

## 要求
將上面這段改為：

```python
recent = history[-8:]
if recent:
    bullish_weeks = sum(1 for item in recent if item["net_short"] > 0)
    if bullish_weeks >= 6:
        trend_label = "多頭趨勢"
    elif bullish_weeks >= 3:
        trend_label = "震盪"
    else:
        trend_label = "空頭趨勢"
    analysis += f"\n近8週：{bullish_weeks}週看多 → {trend_label}"
```

## 禁止
- 不改其他函式
- 不改 report_builder.py
- 不改 decision_engine.py
- 不動 SPARKS 相關任何其他使用（只改 get_cot_with_history 這一段）

## 驗收條件
python3 -m py_compile data_fetcher.py 通過

## Codex 結果
狀態：完成
