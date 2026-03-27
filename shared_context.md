## 任務目標
審查剛才對投資專案的程式碼修改，確認正確性與範圍。

## 變更清單

### 1. decision_engine.py（1行改動）
- 原：`"leader": "P1"` （P3/P4 衝突時）
- 改：`"leader": "CONFLICT"`

### 2. jpy_weekly_report.py（5處修改）

**Import 新增（第26行後）：**
```python
from decision_engine import decide_jpy_direction
```

**build_full_report 簽名新增參數：**
```python
werner_block=None
```

**build_full_report 函式體新增（在 eurjpy_line 前）：**
```python
werner_section = (
    f"\n━━ Werner 四原則方向判斷 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{werner_block}\n"
    if werner_block else ""
)
```

**報告模板新增（在 verdict 後）：**
```
{werner_section}
```

**main() 新增（在 get_weekly_verdict 呼叫前）：**
4個 parse helper 函式 + decide_jpy_direction 呼叫 + werner_block 組裝：
```python
def _w_parse_p1(text): ...  # 從 cb_text 解析 升/貶/中性
def _w_parse_p2(text): ...  # 從 mof_text 解析干預效果
def _w_parse_p3(boj_text, lend_text): ...  # 從 boj_qe_text/lending_text 解析
def _w_parse_p4(text): ...  # 從 bop_text 解析資本流方向

w_p1 = _w_parse_p1(cb_text)
w_p2 = _w_parse_p2(mof_text)
w_p3 = _w_parse_p3(boj_qe_text, lending_text)
w_p4 = _w_parse_p4(bop_text)
w_result = decide_jpy_direction(w_p1, w_p2, w_p3, w_p4)
werner_block = f"主導原則：{w_result['leader']}　最終方向：{w_result['direction']}　..."
```

**build_full_report 呼叫新增：**
```python
werner_block=werner_block
```

## 分工順序
Gemini（正確性審查）→ Codex（範圍審查）

## Gemini 結果
[待填寫]
狀態：進行中

## Codex 結果
- 通過/不通過：不通過
- 修改範圍：依目前目錄檔案時間戳與現檔內容判斷，修改只限於 `decision_engine.py`、`jpy_weekly_report.py`
- 越界風險：有（未使用 Git 或其他版本差異基準，無法做提交級別的絕對比對；但從目前可見證據看，`data_provider.py`、`build_html_report.py` 未出現本次異動，且 `telegram_sender` 檔案不存在）

補充：第 3 點不成立。`decision_engine.py` 的 `decide_jpy_direction()` 在 P3/P4 衝突或無明確方向時，既有分支的 `leader` 回傳值已由 `"P1"` 改成 `"CONFLICT"`，這屬於既有函式主要邏輯／既有行為變更，不是單純新增。
狀態：完成
