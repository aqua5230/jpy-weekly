import html
import logging
from datetime import datetime

from config import TG_TOKEN, TG_PUBLIC, TG_VIP, TG_DEV
from utils import http_post

logger = logging.getLogger(__name__)

TELEGRAM_DISCLAIMER = "\n\n⚠️ 本報告僅供參考，非投資建議。"


def append_telegram_disclaimer(text, parse_mode=None):
    base_text = str(text or "").rstrip()
    if parse_mode == "HTML":
        return f"{base_text}<br><br>⚠️ 本報告僅供參考，非投資建議。"
    return f"{base_text}{TELEGRAM_DISCLAIMER}"


def send_emergency_telegram(context, exc):
    message = (
        "JPY 週報系統緊急告警\n"
        f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"模組：{context}\n"
        f"錯誤：{type(exc).__name__}: {exc}"
    )
    try:
        http_post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_DEV, "text": append_telegram_disclaimer(message)},
            timeout=15,
        )
    except Exception as notify_exc:
        logger.exception("緊急 TG 通知失敗: %s", notify_exc)


def build_direction_summary(verdict, direction, change):
    summary_parts = []
    lines = [line.strip() for line in str(verdict).splitlines() if line.strip()]

    for line in lines:
        if line.startswith("【本週方向】"):
            summary_parts.append(line.replace("【本週方向】", "").strip())
            break

    for line in lines:
        if line.startswith("理由："):
            summary_parts.append(line.replace("理由：", "").strip())
            break

    if summary_parts:
        return "｜".join(summary_parts[:2])

    fallback_direction = f"本週偏向日圓{direction}"
    fallback_reason = f"USD/JPY 本週變動 {change:+.2f}"
    return f"{fallback_direction}｜{fallback_reason}"


def split_telegram_text(text, limit=3500):
    limit = max(1, limit - len(TELEGRAM_DISCLAIMER))
    chunks = []
    current = []
    current_len = 0

    for paragraph in str(text).split("\n"):
        addition = len(paragraph) + (1 if current else 0)
        if current and current_len + addition > limit:
            chunks.append("\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len += addition

    if current:
        chunks.append("\n".join(current))
    return chunks or [str(text)]


def send_photo_to_chat(chat_id, img_path, caption, parse_mode=None):
    with open(img_path, 'rb') as f:
        data = {"chat_id": chat_id, "caption": append_telegram_disclaimer(caption, parse_mode=parse_mode)}
        if parse_mode:
            data["parse_mode"] = parse_mode
        return http_post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
            data=data,
            files={"photo": f},
            timeout=30
        )


def send_public_report(img_path, summary):
    caption = f"💴 <b>日圓強弱卡</b>\n{html.escape(summary)}"
    return send_photo_to_chat(TG_PUBLIC, img_path, caption, parse_mode="HTML")


def send_vip_report(report_text, img_path, tg_url):
    if not TG_VIP:
        logger.info("TG_VIP 未設定，略過 VIP 發送")
        return

    for chunk in split_telegram_text(report_text):
        http_post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_VIP, "text": append_telegram_disclaimer(chunk)},
            timeout=30,
        )

    send_photo_to_chat(TG_VIP, img_path, "💴 日圓強弱卡")
    http_post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_VIP, "text": append_telegram_disclaimer(tg_url)},
        timeout=15,
    )
