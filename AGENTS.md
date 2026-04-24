# 投資專案 Agent 規則

## 啟動順序

1. 先讀 `SESSION.md`。
2. 再讀 `specs/mission.md`、`specs/tech-stack.md`、`specs/roadmap.md`。
3. 若要做單一功能，先建立或讀取 `specs/features/*.md`。
4. 最後才讀相關程式碼。

## 工作規則

- 使用繁體中文回報。
- 先理解規格，再改程式。
- 不碰無關檔案。
- 不自動 push。
- 不自動刪檔。
- 大改動先寫 feature spec。
- 規格階段和實作階段分開。
- 每次改完要回報改了哪些檔案與如何驗證。

## 專案核心

- 專案目標：日圓週報自動化系統。
- 主判斷框架：Werner 四原則。
- 主力函式：`evaluate_jpy_direction()`。
- 主流程：`jpy_weekly_report.py`。

## 發送與風險

- 真實 Telegram 發送前，優先使用 `TG_TEST`。
- 不要把 `.env`、token 或頻道 ID 寫進公開文件。
- `.gh-pages` 是 embedded git repo，操作前先確認狀態。
- 外部資料源可能 timeout，要保留 fallback 與告警設計。

## 文件同步

完成一個功能後，檢查是否需要更新：

- `SESSION.md`
- `TASK_LOG.md`
- `specs/roadmap.md`
- 對應 `specs/features/*.md`
- 測試或使用說明
