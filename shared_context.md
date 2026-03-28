## 任務目標
在 backtest_v1.py 新增 R6：持有型回測（Holding Backtest）函式。
不改原有任何函式，只新增。

## 規格

新增函式 `holding_backtest(records: list) -> dict`，加在 backtest_v1.py 最底部。

入參：
- records：list of dict，從 load_prediction_log 讀出來的記錄，已按 date 排序
  每筆有：date, position_score, close_price

邏輯（按照 date 順序逐筆執行）：
- position = 0（無持倉）
- entry_price = None
- trades = []

for 每筆 record：
  score = record["position_score"]
  price = record["close_price"]

  if score == 1 and position == 0:
      position = 1
      entry_price = price

  elif position == 1 and score < 0:
      ret = (entry_price - price) / entry_price  # 日圓升值 = USD/JPY 下跌
      trades.append({"entry": entry_price, "exit": price, "return": ret, "correct": ret > 0})
      position = 0
      entry_price = None

  # score == 0 且已有持倉 → 繼續持有（不動）
  # score == 1 且已有持倉 → 繼續持有（不動）

回傳 dict：
{
  "trades": trades,           # list of {entry, exit, return, correct}
  "total": len(trades),
  "win_rate": 勝率（float，0.0 若無交易）,
  "avg_return": 平均報酬（float，0.0 若無交易）,
}

## 禁止
- 不改 log_prediction / resolve_pending_predictions / load_prediction_log
- 不接 API
- 不改 decision_engine.py
- 不新增新檔案

## 驗收條件
python3 -c "
from backtest_v1 import holding_backtest
records = [
  {'date': '2026-01-01', 'position_score': 1,    'close_price': 150.0},
  {'date': '2026-01-08', 'position_score': 1,    'close_price': 149.0},
  {'date': '2026-01-15', 'position_score': 0,    'close_price': 148.5},
  {'date': '2026-01-22', 'position_score': -0.5, 'close_price': 151.0},
  {'date': '2026-01-29', 'position_score': 1,    'close_price': 149.5},
  {'date': '2026-02-05', 'position_score': -0.5, 'close_price': 147.0},
]
r = holding_backtest(records)
assert r['total'] == 2, f'expected 2 trades, got {r[\"total\"]}'
print('PASS', r)
"

## Codex 結果
狀態：完成
