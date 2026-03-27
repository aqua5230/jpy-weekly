# 投資專案 Skill 使用規則

## 何時開 Task
- 任務有 3 步以上（Codex → Gemini → commit）一律開
- 單一問答或查資料不開

## 何時呼叫 Skill
| 情境 | Skill |
|------|-------|
| 改完程式碼 | `/simplify` |
| 需要規劃重構 | `/plan` |

## 何時建議換 Session
- Context 接近滿時主動說
- 主題從「判斷引擎」跳到「週報格式」等大幅切換時

## 小弟分工（本專案）
| 任務類型 | 負責 |
|----------|------|
| 修改 Python 程式碼 | Codex |
| 查宏觀數據 / 確認資料日期 | Gemini |
| 正確性審查 | Gemini |
| 範圍審查 | Codex |

## 禁止事項
- Claude 不自己讀檔改程式
- 不跳過 Gemini 審查直接 commit
- 不在沒有 shared_context.md 的情況下呼叫 Codex
