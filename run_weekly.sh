#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=${0:A:h}
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/.report.log"
touch "$LOG_FILE"
exec >> "$LOG_FILE" 2>&1

if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

send_failure_alert() {
python3 - <<'PY'
from datetime import datetime
import requests
from config import TG_TOKEN, TG_DEV

msg = (
    "JPY 週報 shell 緊急告警\n"
    f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    "模組：run_weekly.sh\n"
    "錯誤：jpy_weekly_report.py 執行失敗"
)

requests.post(
    f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
    json={"chat_id": TG_DEV, "text": msg},
    timeout=15,
)
PY
}

trap 'status=$?; if [ "$status" -ne 0 ]; then echo "$(date "+%Y-%m-%d %H:%M:%S") ERROR run_weekly.sh failed with status $status"; send_failure_alert || true; fi' EXIT

echo "$(date "+%Y-%m-%d %H:%M:%S") INFO run_weekly.sh start"

python3 jpy_weekly_report.py

# Mac 通知
osascript -e 'display notification "本週日圓投資週報已產出" with title "📊 投資週報" sound name "Glass"'
echo "$(date "+%Y-%m-%d %H:%M:%S") INFO run_weekly.sh completed"
