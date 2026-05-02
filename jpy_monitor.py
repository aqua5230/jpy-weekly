#!/usr/bin/env python3
"""
日圓即時監控系統
每小時自動檢查，突破關鍵價位時發 Mac 通知 + Telegram
"""
import yfinance as yf
import subprocess
import json
import os
import logging
import requests
from datetime import datetime
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import TG_TOKEN, TG_PUBLIC as TG_CHAT_ID, TG_DEV, ALERT_LEVELS

BASE_DIR = Path(os.environ.get("JPY_BASE_DIR", Path(__file__).resolve().parent))
STATE_FILE = BASE_DIR / ".last_state.json"
LOG_FILE = BASE_DIR / ".report.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
TELEGRAM_DISCLAIMER = "\n\n⚠️ 本報告僅供參考，非投資建議。"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def http_post(url, **kwargs):
    resp = requests.post(url, **kwargs)
    resp.raise_for_status()
    return resp


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def get_history_with_retry(symbol, **kwargs):
    hist = yf.Ticker(symbol).history(**kwargs)
    if hist is None or hist.empty:
        raise ValueError(f"{symbol} 無歷史資料")
    return hist


def safe_last(series, label):
    try:
        if series is None:
            raise ValueError(f"{label} 缺少序列")
        cleaned = series.dropna()
        if cleaned.empty:
            raise ValueError(f"{label} 無有效資料")
        return cleaned.iloc[-1]
    except Exception as exc:
        raise ValueError(f"{label} 讀取失敗: {exc}") from exc


def send_emergency_telegram(context, exc):
    message = (
        "JPY 監控系統緊急告警\n"
        f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"模組：{context}\n"
        f"錯誤：{type(exc).__name__}: {exc}"
    ) + TELEGRAM_DISCLAIMER
    try:
        http_post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_DEV, "text": message},
            timeout=15,
        )
    except Exception as notify_exc:
        logger.exception("緊急 TG 通知失敗: %s", notify_exc)

def notify(title, message):
    """發送 Mac 原生通知 + Telegram"""
    # Mac 通知
    script = f'display notification "{message}" with title "{title}" sound name "Ping"'
    subprocess.run(['osascript', '-e', script])
    # Telegram
    text = f"*{title}*\n{message}{TELEGRAM_DISCLAIMER}"
    try:
        http_post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as exc:
        logger.exception("TG 通知失敗: %s", exc)

def get_price():
    hist = get_history_with_retry("USDJPY=X", period="1d", interval="1h")
    return round(float(safe_last(hist.get("Close"), "USD/JPY Close")), 2)

def load_state():
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(STATE_FILE):
        try:
            if os.path.getsize(STATE_FILE) == 0:
                raise ValueError("state file is empty")
            with open(STATE_FILE) as f:
                state = json.load(f)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("STATE_FILE 損毀或為空，重設為空狀態: %s", exc)
            state = {"alerted": {}, "date": today}
        # 跨日自動重置警報
        if state.get("date") != today:
            state["alerted"] = {}
            state["date"] = today
        return state
    return {"alerted": {}, "date": today}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def main():
    price = get_price()
    if not price:
        logger.warning("無法取得匯率")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info("[%s] USD/JPY：%s", now, price)

    state = load_state()
    alerted = state.get("alerted", {})

    # 檢查每個關鍵價位
    for name, level in ALERT_LEVELS.items():
        key = f"{name}_{level}"

        if name == "干預紅線" and price >= level:
            if key not in alerted:
                notify(
                    "JPY 週報",
                    f"USD/JPY {price:.2f}　突破 {level} 關口\n日本財務省干預機率上升，留意"
                )
                alerted[key] = price
                logger.info("觸發警報：%s %s", name, level)

        elif name == "加碼訊號" and price <= level:
            if key not in alerted:
                notify(
                    "JPY 週報",
                    f"USD/JPY {price:.2f}　跌破 {level}\n日圓走升，風險報酬比在改善"
                )
                alerted[key] = price
                logger.info("觸發機會：%s %s", name, level)

        elif name == "停損警告" and price >= level:
            if key not in alerted:
                notify(
                    "JPY 週報",
                    f"USD/JPY {price:.2f}　升破 {level}\n日圓持續走貶，這個位置需要重新評估"
                )
                alerted[key] = price
                logger.info("觸發警告：%s %s", name, level)

        # 價位恢復正常，重置警報
        elif name == "干預紅線" and price < level - 0.3:
            alerted.pop(key, None)
        elif name == "加碼訊號" and price > level + 0.3:
            alerted.pop(key, None)
        elif name == "停損警告" and price < level - 0.3:
            alerted.pop(key, None)

    state["alerted"] = alerted
    state["last_price"] = price
    state["last_check"] = datetime.now().isoformat()
    save_state(state)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logger.exception("jpy_monitor.py 執行崩潰: %s", exc)
        send_emergency_telegram("jpy_monitor.py", exc)
        raise
