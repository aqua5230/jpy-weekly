# Feature

名稱：`resolve_pending_predictions` 週末結算日 fallback

## 背景

`backtest_v1.py` 的 `resolve_pending_predictions()` 目前直接用 `record_date + 7d` 與 `record_date + 56d` 當查價鍵。

當 `record_date` 落在週六或週日，對應的 +7 天或 +56 天也可能落在週末；而 `price_lookup` 只含交易日，會造成預測永遠維持 `pending`。

這會讓 prediction log 的 1 週與 8 週結算失真，影響 `mission.md` 中「投資判斷需要可回測」的要求。

## Feature Plan

1. 在 module-level 新增 helper，從目標日往後找第一個存在於 `price_lookup` 的交易日價格。
2. 在 `resolve_pending_predictions()` 的 1 週與 8 週結算改用 helper，並記錄實際結算日。
3. 在 `__main__` 補一個週末 `record_date` 案例，驗證 fallback 會 resolve。

## Requirements

- 必須：`resolve_pending_predictions()` 對外 signature 與回傳結構不變。
- 必須：1 週與 8 週目標日若落在週末，最多往後搜尋 7 天找第一個交易日。
- 必須：找到價格時才新增 `next_1w_resolved_date` / `next_8w_resolved_date`。
- 必須：找不到資料時維持 `pending`，行為與現況一致。
- 暫時不做：回填既有 `backtest_predictions.json`。
- 暫時不做：修改週報主流程或其他 backtest 模組。

## Constraints

- 不改無關檔案。
- 不擴大功能範圍。
- 涉及 Telegram 發送時，先用 `TG_TEST`。
- 涉及資料源時，要說明 fallback 行為。

## Validation

可用指令：

```bash
python3 backtest_v1.py
python3 -m py_compile backtest_v1.py
python3 -m pytest test_decision_engine.py test_fred_fallback.py
```

人工驗證：

- 原 5 筆多筆回測統計輸出不變。
- `record_date=2026-04-12` 的週末案例可用 `2026-04-20` 作為 +7 天的 fallback 結算。

## Done Criteria

- 符合 requirements。
- 通過 validation。
- 更新必要文件。
- 回報改了哪些檔案與如何驗證。
