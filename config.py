"""
集中設定檔
"""
import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ── Telegram ──────────────────────────────────
TG_TOKEN   = os.environ.get("TG_TOKEN")
if not TG_TOKEN:
    raise RuntimeError("請設定環境變數 TG_TOKEN")

TG_PUBLIC  = os.environ.get("TG_PUBLIC")
if not TG_PUBLIC:
    raise RuntimeError("請設定環境變數 TG_PUBLIC")

TG_VIP     = os.environ.get("TG_VIP", "")
TG_DEV     = os.environ.get("TG_DEV", TG_PUBLIC)

# ── 關鍵價位（兩支程式共用）──────────────────────
ALERT_LEVELS = {
    "加碼訊號": 156.00,   # 日圓升值到這裡可加碼
    "干預紅線": 160.00,   # 突破此處，財務省干預機率上升
    "停損警告": 162.00,   # 日圓持續大貶，考慮出場
}

# danger_zone 判斷門檻（與 ALERT_LEVELS 一致）
DANGER_HIGH  = ALERT_LEVELS["停損警告"]   # 162
DANGER_MID   = ALERT_LEVELS["干預紅線"]   # 160
DANGER_WARN  = ALERT_LEVELS["加碼訊號"]   # 156

# ── 路徑 ──────────────────────────────────────
TG_TOKEN_FILE    = BASE_DIR / ".telegraph_token"
LOG_FILE         = BASE_DIR / ".report.log"
COT_HISTORY      = BASE_DIR / ".cot_history.json"
BOJ_QE_CACHE     = BASE_DIR / ".boj_qe_cache.json"
CALENDAR_CACHE   = BASE_DIR / ".calendar_cache.json"
REPORT_CARD      = BASE_DIR / ".report_card.png"
