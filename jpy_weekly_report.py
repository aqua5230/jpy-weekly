#!/usr/bin/env python3
"""
日圓週報自動化系統
每週一早上執行，產出投資參考報告
"""
import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor
import yfinance as yf
import json
import re
import os
import html
from datetime import datetime, timedelta
from config import (
    DANGER_HIGH,
    DANGER_MID,
    TG_TOKEN_FILE,
    LOG_FILE,
    COT_HISTORY,
    BOJ_QE_CACHE,
    CALENDAR_CACHE,
    REPORT_CARD,
)
from data_provider import (
    fetch_fred_points,
    fetch_latest_jgb_curve_row,
    fetch_yfinance_history,
)
from test_image import draw_card
from test_telegraph import create_telegraph_account, publish_to_telegraph, build_nodes
from build_html_report import build_html, push_to_github_pages
from decision_engine import decide_jpy_direction, evaluate_jpy_direction
from telegram_sender import TELEGRAM_DISCLAIMER, append_telegram_disclaimer, send_emergency_telegram, split_telegram_text, build_direction_summary, send_photo_to_chat, send_public_report, send_vip_report
from utils import http_get, safe_last, safe_first, run_text_command, clean_gemini_output, extract_json_object, is_missing_result

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def collect_data_source_result(name, future, failures, validator=None):
    try:
        result = future.result()
        valid = validator(result) if validator is not None else not is_missing_result(result)
        if not valid:
            failures.append((name, "資料為空或不完整"))
            logger.warning("資料源 %s 失敗: 資料為空或不完整", name)
        else:
            logger.info("資料源 %s 成功", name)
        return result
    except Exception as exc:
        failures.append((name, f"{type(exc).__name__}: {exc}"))
        logger.exception("資料源 %s 失敗: %s", name, exc)
        return None


def send_data_health_alert(failures):
    if not failures:
        return

    message = (
        "JPY 週報資料源告警\n"
        f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "以下資料源抓取失敗：\n"
        + "\n".join(f"- {name}: {reason}" for name, reason in failures)
    )
    logger.warning("%s", message)


ALLOWED_TELEGRAM_HTML_PATTERN = re.compile(r"(</?(?:b|code|blockquote)>|<br>)")


def escape_html_preserving_allowed_tags(text):
    parts = ALLOWED_TELEGRAM_HTML_PATTERN.split(str(text or ""))
    escaped_parts = []
    for part in parts:
        if not part:
            continue
        if ALLOWED_TELEGRAM_HTML_PATTERN.fullmatch(part):
            escaped_parts.append(part)
        else:
            escaped_parts.append(html.escape(part))
    return "".join(escaped_parts)


def parse_tagged_blocks(text):
    blocks = []
    current_label = None
    current_lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if set(line) <= {"━"}:
            continue
        match = re.match(r"【(.+?)】(.*)", line)
        if match:
            if current_label is not None or current_lines:
                blocks.append({"label": current_label, "lines": current_lines})
            current_label = match.group(1).strip()
            current_lines = [match.group(2).strip()] if match.group(2).strip() else []
        else:
            current_lines.append(line)
    if current_label is not None or current_lines:
        blocks.append({"label": current_label, "lines": current_lines})
    return blocks


def extract_vip_highlights(verdict, signal_summary="", danger_zone="", mof_text="", calendar=""):
    highlights = []
    combined_text = "\n".join(str(part or "") for part in [verdict, signal_summary, danger_zone, mof_text, calendar])

    for block in parse_tagged_blocks(verdict):
        label = block.get("label")
        lines = [ln for ln in block.get("lines", []) if ln]
        if label == "數據觀察摘要" and lines:
            highlights.append(f"🎯 {lines[0]}")
        elif label == "本週方向" and lines:
            highlights.append(f"🧭 {lines[0]}")
        elif label == "這週要盯什麼" and lines:
            highlights.append(f"📅 {lines[0]}")

    signal_match = re.search(r"本週訊號一致性[:：]\s*(.+)", str(signal_summary or ""))
    if signal_match:
        highlights.append(f"📊 {signal_match.group(1).strip()}")

    if danger_zone:
        highlights.append(f"🚨 {str(danger_zone).strip().rstrip('。')}")
    elif "160" in combined_text:
        highlights.append("🚨 匯價逼近 160 干預紅線")

    if mof_text:
        first_line = next((ln.strip() for ln in str(mof_text).splitlines() if ln.strip()), "")
        if first_line:
            highlights.append(f"🏛 {first_line}")

    seen = set()
    unique = []
    for item in highlights:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:5]


def build_vip_report_html(report_text, verdict="", signal_summary="", danger_zone="", mof_text="", calendar=""):
    blocks = []
    highlights = extract_vip_highlights(verdict, signal_summary, danger_zone, mof_text, calendar)
    if highlights:
        bullets = "".join(f"<blockquote>{item}</blockquote>" for item in highlights[:5])
        blocks.append(f"<b>核心觀點</b>\n{bullets}")

    for raw_block in parse_tagged_blocks(report_text):
        label = raw_block.get("label")
        lines = [ln for ln in raw_block.get("lines", []) if ln]
        if not label and lines:
            blocks.append("<br>".join(lines))
            continue
        if not label:
            continue

        rendered_lines = [f"<b>{label}</b>"]
        for idx, line in enumerate(lines):
            if label == "數據觀察摘要" and idx == 0:
                rendered_lines.append(f"<code>{line}</code>")
            elif any(token in line for token in ["USD/JPY", "EUR/JPY", "RSI", "美日利差", "美國2Y", "日本2Y", "利差", "Fed 下次會議", "BOJ ", "報告日期"]):
                rendered_lines.append(f"<code>{line}</code>")
            elif re.search(r"\d", line):
                rendered_lines.append(f"<code>{line}</code>" if len(line) <= 80 else line)
            else:
                rendered_lines.append(line)
        blocks.append("<br>".join(rendered_lines))

    return escape_html_preserving_allowed_tags("\n\n".join(blocks))


def build_card_status_snapshot(cb_text="", spread_2y_data=None, price=None):
    spread_2y_data = spread_2y_data or {}

    fed_label = "Fed: 中性"
    cb_body = str(cb_text or "")
    if "偏向日圓升值" in cb_body:
        fed_label = "Fed: 偏鷹 🦅"
    elif "偏向日圓貶值" in cb_body:
        fed_label = "Fed: 偏鴿 🕊"

    spread_value = spread_2y_data.get("spread_2y")
    spread_label = "利差: 持平 ↔"
    if isinstance(spread_value, (int, float)):
        if spread_value >= 3.0:
            spread_label = "利差: 擴大 ↗️"
        elif spread_value <= 1.5:
            spread_label = "利差: 收斂 ↘️"

    red_line = 160.0
    current = float(price or 0)
    distance = red_line - current
    progress_ratio = 0.0
    if current > 0:
        progress_ratio = max(0.0, min(current / red_line, 1.0))
    distance_label = f"距 160 尚有 {distance:.2f}" if distance >= 0 else f"高於 160 {abs(distance):.2f}"

    return {
        "fed": fed_label,
        "spread": spread_label,
        "intervention_price": red_line,
        "intervention_progress": progress_ratio,
        "intervention_distance_label": distance_label,
    }


# ───────────────────────────────────────────────
# 資料取得
# ───────────────────────────────────────────────

def get_usdjpy():
    hist = fetch_yfinance_history("USDJPY=X", period="5d")
    close = hist.get("Close")
    current = safe_last(close, "USD/JPY Close")
    week_ago = safe_first(close, "USD/JPY Close")
    return current, current - week_ago


def load_cot_history():
    if os.path.exists(COT_HISTORY):
        with open(COT_HISTORY) as f:
            return json.load(f)
    return []

def get_cot_with_history():
    """直接抓 CFTC 官方 CSV，計算日圓非商業淨部位"""
    import csv
    import io
    import zipfile

    def parse_int(value):
        return int(str(value).strip().replace(",", ""))

    def normalize_history(items):
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            date_str = item.get("date")
            raw_net = item.get("net_short", item.get("net"))
            if not date_str or raw_net is None:
                continue
            try:
                normalized.append({
                    "date": date_str,
                    "net_short": int(raw_net),
                })
            except (TypeError, ValueError):
                continue
        normalized.sort(key=lambda x: x["date"])
        deduped = []
        for item in normalized:
            if deduped and deduped[-1]["date"] == item["date"]:
                deduped[-1] = item
            else:
                deduped.append(item)
        return deduped

    def fetch_weekly_row():
        r = http_get("https://www.cftc.gov/dea/newcot/FinFutWk.txt", timeout=20)
        reader = csv.reader(io.StringIO(r.text))
        return next(
            row for row in reader
            if len(row) > 10 and "JAPANESE YEN" in row[0].upper()
        )

    def fetch_52_week_history(report_date, current_net):
        def normalize_header(value):
            return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

        def find_index(header_map, *candidates):
            for candidate in candidates:
                idx = header_map.get(candidate)
                if idx is not None:
                    return idx
            return None

        history_map = {}
        for year in (report_date.year - 1, report_date.year):
            url = f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
            try:
                resp = http_get(url, timeout=20)
                archive = zipfile.ZipFile(io.BytesIO(resp.content))
                data_name = next(
                    name for name in archive.namelist()
                    if name.lower().endswith((".csv", ".txt"))
                )
                with archive.open(data_name) as f:
                    text = io.TextIOWrapper(f, encoding="utf-8-sig", newline="")
                    reader = csv.reader(text)
                    header_map = None
                    debug_printed = False
                    for row in reader:
                        if not row:
                            continue
                        if header_map is None:
                            normalized = [normalize_header(col) for col in row]
                            if "market_and_exchange_names" in normalized:
                                header_map = {name: idx for idx, name in enumerate(normalized)}
                            continue
                        if "JAPANESE YEN" not in " | ".join(row).upper():
                            continue
                        if not debug_printed and os.getenv("COT_DEBUG"):
                            logger.info("[COT_DEBUG] history_header=%s", header_map)
                            logger.info("[COT_DEBUG] japanese_yen_row=%s", row)
                            debug_printed = True
                        report_date_idx = find_index(
                            header_map,
                            "report_date_as_yyyy_mm_dd",
                            "as_of_date_in_form_yyyy_mm_dd",
                            "report_date_as_mm_dd_yyyy",
                        )
                        nc_long_idx = find_index(
                            header_map,
                            "noncommercial_positions_long_all",
                            "noncommercial_long",
                            "lev_money_positions_long_all",
                        )
                        nc_short_idx = find_index(
                            header_map,
                            "noncommercial_positions_short_all",
                            "noncommercial_short",
                            "lev_money_positions_short_all",
                        )
                        if report_date_idx is None or nc_long_idx is None or nc_short_idx is None:
                            continue
                        try:
                            raw_date = row[report_date_idx].strip()
                            if re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date):
                                row_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
                            else:
                                row_date = datetime.strptime(raw_date, "%m/%d/%Y").strftime("%Y-%m-%d")
                            row_net = parse_int(row[nc_long_idx]) - parse_int(row[nc_short_idx])
                        except (ValueError, IndexError):
                            continue
                        history_map[row_date] = {"date": row_date, "net_short": row_net}
            except Exception:
                continue

        history = [history_map[k] for k in sorted(history_map)]
        if report_date.strftime("%Y-%m-%d") not in history_map:
            history.append({
                "date": report_date.strftime("%Y-%m-%d"),
                "net_short": current_net,
            })
            history.sort(key=lambda x: x["date"])
        return history[-52:]

    row = fetch_weekly_row()
    report_date = datetime.strptime(row[2].strip(), "%Y-%m-%d")
    report_date_str = report_date.strftime("%Y-%m-%d")
    nc_long = parse_int(row[8])
    nc_short = parse_int(row[9])
    net = nc_long - nc_short   # 正 = 淨多頭（看漲日圓），負 = 淨空頭（看跌日圓）

    fallback_history = normalize_history(load_cot_history())
    history = fetch_52_week_history(report_date, net)
    if not history:
        history = fallback_history

    history = [h for h in history if h["date"] != report_date_str]
    history.append({"date": report_date_str, "net_short": net})
    history = normalize_history(history)[-52:]
    with open(COT_HISTORY, 'w') as f:
        json.dump(history, f)

    values = [h["net_short"] for h in history]
    prev_net = history[-2]["net_short"] if len(history) >= 2 else net
    weekly_change = net - prev_net
    percentile = round(sum(1 for v in values if v <= net) / len(values) * 100) if values else 50

    if percentile >= 80:
        percentile_text = "大家幾乎都在看漲，位置擁擠，反而要小心大跌"
    elif percentile >= 60:
        percentile_text = "看漲的人偏多，對日圓有支撐"
    elif percentile >= 40:
        percentile_text = "偏向看漲，但沒特別極端"
    elif percentile >= 20:
        percentile_text = "偏向看跌，但沒特別極端"
    else:
        percentile_text = "大家幾乎都在看跌，位置擁擠，反而要小心反彈"

    if percentile >= 50:
        position_summary = (
            f"52週定位：近一年當中有 {percentile}% 的時間比現在更空"
            f"（代表大家目前偏看多日圓，位置不低）"
        )
    else:
        position_summary = (
            f"52週定位：近一年當中只有 {percentile}% 的時間比現在更空"
            f"（代表大家目前偏看空日圓，位置不高）"
        )

    direction = "淨多頭" if net > 0 else "淨空頭"
    analysis = (
        f"報告日期 {report_date_str}　非商業{direction} {abs(net):,} 口，較上週 {weekly_change:+,} 口\n"
        f"多頭 {nc_long:,}　空頭 {nc_short:,}\n"
        f"{position_summary}\n"
        f"{percentile_text}"
    )

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

    if percentile >= 80 or percentile < 20:
        analysis += "\n⚠️ 注意：目前持倉過度集中在同一邊，歷史上這種情況常出現在行情反轉前"

    return analysis, history


def get_tff_data():
    """抓 CFTC TFF Disaggregated 報告中的日圓 Leveraged Funds 淨部位。失敗時靜默降級。"""
    import csv
    import io
    import zipfile

    def parse_int(value):
        return int(str(value).strip().replace(",", ""))

    def normalize_header(value):
        return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

    def find_index(header_map, *candidates):
        for candidate in candidates:
            idx = header_map.get(candidate)
            if idx is not None:
                return idx
        return None

    history_map = {}
    years = sorted({datetime.now().year - 1, datetime.now().year})

    try:
        for year in years:
            url = f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
            resp = http_get(url, timeout=20)
            archive = zipfile.ZipFile(io.BytesIO(resp.content))
            data_name = next(
                name for name in archive.namelist()
                if name.lower().endswith((".csv", ".txt"))
            )
            with archive.open(data_name) as f:
                text = io.TextIOWrapper(f, encoding="utf-8-sig", newline="")
                reader = csv.reader(text)
                header_map = None
                for row in reader:
                    if not row:
                        continue
                    if header_map is None:
                        normalized = [normalize_header(col) for col in row]
                        if "market_and_exchange_names" in normalized:
                            header_map = {name: idx for idx, name in enumerate(normalized)}
                        continue

                    market_name_idx = find_index(header_map, "market_and_exchange_names")
                    code_idx = find_index(
                        header_map,
                        "cftc_contract_market_code",
                        "cftc_market_code",
                        "contract_market_code",
                    )
                    report_date_idx = find_index(
                        header_map,
                        "report_date_as_yyyy_mm_dd",
                        "as_of_date_in_form_yyyy_mm_dd",
                        "report_date_as_mm_dd_yyyy",
                    )
                    lev_long_idx = find_index(header_map, "lev_money_positions_long_all")
                    lev_short_idx = find_index(header_map, "lev_money_positions_short_all")
                    if None in (market_name_idx, report_date_idx, lev_long_idx, lev_short_idx):
                        continue

                    market_name = row[market_name_idx].upper() if len(row) > market_name_idx else ""
                    contract_code = row[code_idx].strip() if code_idx is not None and len(row) > code_idx else ""
                    if "YEN" not in market_name and contract_code != "097741":
                        continue

                    try:
                        raw_date = row[report_date_idx].strip()
                        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date):
                            row_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
                        else:
                            row_date = datetime.strptime(raw_date, "%m/%d/%Y").strftime("%Y-%m-%d")
                        lev_long = parse_int(row[lev_long_idx])
                        lev_short = parse_int(row[lev_short_idx])
                    except (ValueError, IndexError):
                        continue

                    history_map[row_date] = {
                        "date": row_date,
                        "lev_net": lev_long - lev_short,
                    }
    except Exception:
        logger.exception("TFF 資料抓取失敗")
        return {}

    history = [history_map[k] for k in sorted(history_map)]
    if not history:
        return {}

    latest = history[-1]
    values = [item["lev_net"] for item in history[-52:]]
    if not values:
        return {}

    percentile = round(sum(1 for value in values if value <= latest["lev_net"]) / len(values) * 100)
    return {
        "tff_lev_net": latest["lev_net"],
        "tff_lev_pct": percentile,
        "tff_report_date": latest["date"],
    }


def get_news_from_gemini():
    prompt = (
        f"今天是{datetime.now().strftime('%Y年%m月%d日')}。"
        "請直接列出本週影響日圓USD/JPY最重要的3個事件，格式：\n"
        "1. 事件標題：一句話說明市場如何反應、方向如何\n"
        "2. 事件標題：...\n"
        "3. 事件標題：...\n"
        "語氣像市場觀察，不要有任何前言，直接從1.開始。繁體中文。"
    )
    fallback = (
        "1. 本週 AI 新聞摘要暫時無法取得：請優先觀察聯準會、日銀與美元兌日圓走勢\n"
        "2. 匯率關鍵事件仍以經濟數據與央行訊號為主：留意高影響力行事曆\n"
        "3. 本次改用備援文字繼續產出報告：下次執行會再嘗試更新摘要"
    )
    result = run_text_command(['gemini', '-p', prompt, '--yolo'], timeout=180, fallback_text=fallback)
    return clean_gemini_output(result)


def get_economic_calendar():
    """從 ForexFactory JSON 抓本週 JPY + USD 重要事件（有真實日期）"""
    cache_path = CALENDAR_CACHE
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                cached = json.load(f)
            if cached.get("date") == today:
                return cached.get("text", "行事曆資料暫時無法取得")
    except Exception:
        pass
    try:
        r = http_get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=15)
        if not r.text.strip():
            return "行事曆資料暫時無法取得"
        events = r.json()
    except Exception:
        err_msg = "行事曆本週資料暫時無法取得"
        logger.exception("行事曆資料抓取失敗")
        try:
            with open(cache_path, "w") as f:
                json.dump({"date": today, "text": err_msg}, f, ensure_ascii=False)
        except Exception:
            pass
        return err_msg

    high_impact = [
        e for e in events
        if e.get("country") in ("JPY", "USD") and e.get("impact") == "High"
    ]
    if not high_impact:
        high_impact = [e for e in events if e.get("country") in ("JPY", "USD") and e.get("impact") == "Medium"]

    lines = []
    for e in high_impact[:5]:
        dt = datetime.fromisoformat(e["date"])
        date_str = dt.strftime("%m/%d")
        flag = "🇯🇵" if e["country"] == "JPY" else "🇺🇸"
        title = e["title"]
        forecast = f"　預測：{e['forecast']}" if e.get("forecast") else ""
        impact_text = ""
        title_upper = title.upper()
        country = e.get("country")

        if country == "JPY" and ("CPI" in title_upper or "INFLATION" in title_upper):
            impact_text = "　→ 若高於預測，利多日圓"
        elif country == "JPY" and "GDP" in title_upper:
            impact_text = "　→ 若高於預測，利多日圓"
        elif country == "JPY" and ("RATE" in title_upper or "INTEREST" in title_upper):
            impact_text = "　→ 若偏鷹或升息，利多日圓"
        elif country == "USD" and any(keyword in title_upper for keyword in ("UNEMPLOYMENT", "JOBS", "NFP", "PAYROLL")):
            impact_text = "　→ 若低於預測（就業強），利空日圓"
        elif country == "USD" and ("CPI" in title_upper or "INFLATION" in title_upper):
            impact_text = "　→ 若高於預測，利空日圓"
        elif country == "USD" and "PMI" in title_upper:
            impact_text = "　→ 若高於預測，利空日圓"

        lines.append(f"{date_str} {flag} {title}{forecast}{impact_text}")

    result = "\n".join(lines) if lines else "本週無高影響事件"
    try:
        with open(cache_path, "w") as f:
            json.dump({"date": today, "text": result}, f, ensure_ascii=False)
    except Exception:
        pass
    return result

def get_rate_differential():
    """美日利差：美國 10Y（yfinance）vs 日本 10Y（財務省 CSV）"""
    us_hist = fetch_yfinance_history("^TNX", period="5d")
    us10y = round(float(safe_last(us_hist.get("Close"), "^TNX Close")), 3)
    latest_curve = fetch_latest_jgb_curve_row()
    raw = latest_curve.get("10年", "") or "0"
    jp10y = round(float(raw), 3)

    spread = round(us10y - jp10y, 3)
    trend = (
        "擴大中（市場感受上有貶值壓力，但歷史顯示利差並非可靠的匯率預測指標）"
        if spread > 2.0 else
        "收窄中（市場感受上有升值空間，但歷史顯示利差並非可靠的匯率預測指標）"
    )
    return us10y, jp10y, spread, trend


def get_us2y_jp2y_spread():
    """抓美日短端利差，優先用 ^IRX 代理美國 2Y，日方優先抓 2 年 JGB。"""
    us2y = None
    jp2y = 0.5

    def latest_close(ticker):
        hist = fetch_yfinance_history(ticker, period="5d")
        return float(safe_last(hist.get("Close"), f"{ticker} Close"))

    try:
        us2y = latest_close("^IRX")
    except Exception:
        try:
            # SHY 本身是價格，不是殖利率；若基金頁面提供 yield 欄位則優先採用。
            shy = yf.Ticker("SHY")
            info = getattr(shy, "info", {}) or {}
            for key in ("yield", "dividendYield", "trailingAnnualDividendYield"):
                value = info.get(key)
                if value:
                    us2y = float(value) * 100
                    break
            if us2y is None:
                shy_close = latest_close("SHY")
                if 0 < shy_close < 20:
                    us2y = shy_close
        except Exception:
            us2y = None

    if us2y is None:
        try:
            us10y, _, _, _ = get_rate_differential()
            us2y = us10y * 0.85
        except Exception:
            us2y = 3.5

    try:
        latest_curve = fetch_latest_jgb_curve_row()
        raw_jp2y = latest_curve.get("2年")
        if raw_jp2y not in (None, "", "-"):
            jp2y = float(raw_jp2y)
    except Exception:
        pass

    us2y = round(float(us2y), 2)
    jp2y = round(float(jp2y), 2)
    spread_2y = round(us2y - jp2y, 2)
    text = f"美國2Y {us2y:.2f}%　日本2Y {jp2y:.2f}%　利差 {spread_2y:.2f}%（短端）"
    return {
        "us2y": us2y,
        "jp2y": jp2y,
        "spread_2y": spread_2y,
        "text": text,
    }


def get_next_meeting_countdown():
    """回傳今年剩餘 Fed / BOJ 會議最近一場的倒數。"""
    fed_meetings = [
        "2026-03-18/19",
        "2026-05-06/07",
        "2026-06-17/18",
        "2026-07-28/29",
        "2026-09-15/16",
        "2026-10-27/28",
        "2026-12-09/10",
    ]
    boj_meetings = [
        "2026-03-18/19",
        "2026-04-30/05-01",
        "2026-06-16/17",
        "2026-07-30/31",
        "2026-09-18/19",
        "2026-10-28/29",
        "2026-12-18/19",
    ]
    today = datetime.now().date()

    def next_meeting(meetings):
        future = []
        for item in meetings:
            start = datetime.strptime(item.split("/")[0], "%Y-%m-%d").date()
            if start >= today:
                future.append((start, item))
        if future:
            next_date, raw_text = future[0]
        else:
            next_date, raw_text = datetime.strptime(meetings[-1].split("/")[0], "%Y-%m-%d").date(), meetings[-1]
        return next_date, raw_text

    fed_date_obj, fed_date = next_meeting(fed_meetings)
    boj_date_obj, boj_date = next_meeting(boj_meetings)
    fed_days = (fed_date_obj - today).days
    boj_days = (boj_date_obj - today).days
    text = f"Fed 下次會議 {fed_date}（{fed_days}天後）　BOJ {boj_date}（{boj_days}天後）"
    return {
        "fed_days": fed_days,
        "boj_days": boj_days,
        "fed_date": fed_date,
        "boj_date": boj_date,
        "text": text,
    }


def get_cb_balance_sheets():
    """比較 Fed 與日銀近 3 個月資產負債表變化，白話解讀相對信用創造"""
    def pct_change(points, min_days):
        latest_date, latest_value = points[-1]
        anchor_idx = None
        for i in range(len(points) - 2, -1, -1):
            if (latest_date - points[i][0]).days >= min_days:
                anchor_idx = i
                break
        if anchor_idx is None:
            anchor_idx = 0
        anchor_date, anchor_value = points[anchor_idx]
        if anchor_value == 0:
            raise ValueError("基期不能為 0")
        change_pct = ((latest_value - anchor_value) / anchor_value) * 100
        return latest_date, latest_value, anchor_date, anchor_value, change_pct

    try:
        fed_points = fetch_fred_points("WALCL")
        boj_points = fetch_fred_points("JPNASSETS")

        # 用近 3 個月百分比變化來比較擴表速度，避免美元與日圓單位不同無法直接比。
        fed_latest_date, fed_latest, fed_anchor_date, fed_anchor, fed_change = pct_change(fed_points, 84)
        boj_latest_date, boj_latest, boj_anchor_date, boj_anchor, boj_change = pct_change(boj_points, 84)

        fed_delta = fed_latest - fed_anchor
        boj_delta = boj_latest - boj_anchor

        if fed_delta < 0 and boj_delta < 0:
            if fed_change < boj_change:
                qt_winner = "美元"
                direction = "偏向日圓升值"
            elif fed_change > boj_change:
                qt_winner = "日圓"
                direction = "偏向日圓貶值"
            else:
                qt_winner = "兩邊差不多"
                direction = "方向不明"
            detail = (
                f"兩國央行都在縮表（回收市場資金），要看誰縮得更快。目前{qt_winner}相對收縮更多，"
                f"資金相對減少，{direction}。"
            )
        elif fed_change > boj_change:
            direction = "偏向日圓升值"
            detail = "聯準會近期擴表速度快於日銀，美元供給增加快於日圓，長期來看對日圓升值有利。"
        elif fed_change < boj_change:
            direction = "偏向日圓貶值"
            detail = "日銀近期擴表速度快於聯準會，日圓供給增加快於美元，長期來看對日圓貶值有壓力。"
        else:
            direction = "方向不明"
            detail = "Fed 和日銀近 3 個月擴縮幅度相近，單看這個指標還無法判斷方向，需參考其他訊號。"

        return (
            f"Fed 總資產：{fed_latest:,.0f} 百萬美元（{fed_latest_date:%Y-%m-%d}，較 {fed_anchor_date:%Y-%m-%d} "
            f"{fed_change:+.2f}%）\n"
            f"日銀總資產：{boj_latest:,.0f} 百萬日圓（{boj_latest_date:%Y-%m-%d}，較 {boj_anchor_date:%Y-%m-%d} "
            f"{boj_change:+.2f}%）\n"
            f"方向：{direction}\n"
            f"解讀：{detail}"
        )
    except Exception as exc:
        logger.exception("央行資產負債表抓取失敗: %s", exc)
        return None


def get_boj_qe_type():
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(BOJ_QE_CACHE):
        try:
            with open(BOJ_QE_CACHE, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("date") == today and cache.get("text"):
                return cache["text"]
        except Exception:
            pass

    try:
        prompt = (
            "請用一段話（繁體中文，50字以內）說明：日本銀行（BoJ）目前（2026年）的資產購買計畫，"
            "主要買什麼？是否還在買ETF或REIT？是否已停止買股票型ETF？"
            "最後用以下格式分類：【類型：QE2／QE3／縮表】"
            "QE2=買非銀行資產（ETF、REIT、商業票據），QE3=只買JGB公債，縮表=在減少資產。"
            "不要廢話，直接輸出。"
        )
        fallback = (
            "BoJ 當前操作類型：資料暫時無法判定\n"
            "AI 摘要逾時或失敗，暫以既有官方資料與市場觀察為主。\n"
            "解讀：本段改用備援文字，不中斷整體報告流程。"
        )
        result = run_text_command(['gemini', '-p', prompt, '--yolo'], timeout=180, fallback_text=fallback)
        # 清除 Gemini 廢話前言
        result = '\n'.join(
            line for line in result.split('\n')
            if not any(line.strip().startswith(p) for p in ['我將', '我会', '讓我', '首先', 'I will', 'I am', 'Let me', '根據以下', '我需要'])
        ).strip()
        if 'QE2' in result:
            qe_type = 'QE2（真實量化寬鬆）'
            qe_note = '日銀向非銀行部門購買資產，根據Werner框架，這是真正能推動實體信用創造的QE，對日圓有實質影響。'
        elif '縮表' in result or 'QT' in result.upper():
            qe_type = '縮表（量化緊縮）'
            qe_note = '日銀正在減少資產，信用收縮，Werner框架下偏向日圓升值壓力。'
        else:
            qe_type = 'QE3（假量化寬鬆）'
            qe_note = '日銀主要購買JGB公債（向銀行買良性資產），Werner框架指出這種QE對實體經濟拉動有限，效果不如預期。'
        summary = result.split('【類型')[0].strip()[:100] if '【類型' in result else result[:100]
        text = f"BoJ 當前操作類型：{qe_type}\n{summary}\n解讀：{qe_note}"
        try:
            with open(BOJ_QE_CACHE, 'w', encoding='utf-8') as f:
                json.dump({"date": today, "text": text}, f, ensure_ascii=False)
        except Exception:
            pass
        return text
    except Exception as exc:
        logger.exception("BoJ QE 類型判斷失敗: %s", exc)
        return None


def get_mof_intervention(cb_text=None):
    """抓財務省外匯干預 CSV，並與日銀資產負債表交叉比對判斷沖銷"""
    try:
        url = "https://www.mof.go.jp/english/policy/international_policy/reference/feio/foreign_exchange_intervention_operations.csv"
        resp = http_get(url, timeout=20)
        text = resp.content.decode("shift-jis")

        # 解析：欄位 index 3=Year(str), 4=Month(str), 5=Day(str),
        #        6=Amount(str, 100M JPY), 8=英文說明
        # 只取有個別日期的干預行（index 3 是4位數年份且 index 5 是數字）
        last_record = None
        import csv, io
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 9:
                continue
            year_str = row[3].strip()
            day_str  = row[5].strip()
            if not (len(year_str) == 4 and year_str.isdigit()):
                continue
            if not day_str.isdigit():
                continue
            last_record = row

        if not last_record:
            # 無任何個別干預行（例如 2025 全年皆無）
            # 嘗試從任何有數字的 summary 行取最後一筆顯示用年份
            last_year_seen = None
            for row in csv.reader(io.StringIO(text)):
                if len(row) >= 4:
                    y = row[3].strip()
                    if len(y) == 4 and y.isdigit():
                        last_year_seen = y
            note = f"（最近已記錄年份：{last_year_seen}）" if last_year_seen else ""
            return f"近三個月無財務省外匯干預紀錄{note}\n解讀：市場目前未觸發財務省動作，日圓處於自然波動區間"

        year  = int(last_record[3].strip())
        month_str = last_record[4].strip()
        day   = int(last_record[5].strip())
        amount_raw = last_record[6].strip().replace(",", "").replace('"', "")
        description = last_record[8].strip() if len(last_record) > 8 else ""

        # 月份（英文縮寫）
        month_map = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                     "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
        month = month_map.get(month_str[:3], None)
        if month is None:
            try:
                month = int(month_str)
            except ValueError:
                month = 1
        intervention_date = datetime(year, month, day)
        days_ago = (datetime.now() - intervention_date).days

        try:
            amount_100m = int(float(amount_raw))
        except (ValueError, TypeError):
            amount_100m = 0

        # 判斷干預方向
        desc_upper = description.upper()
        if "US DOLLAR (SOLD)" in desc_upper or "JAPANESE YEN (BOUGHT)" in desc_upper:
            action = "賣出美元買入日圓（阻升操作）"
            sold_usd = True
            sold_jpy = False
        elif "US DOLLAR (BOUGHT)" in desc_upper or "JAPANESE YEN (SOLD)" in desc_upper:
            action = "賣出日圓買入美元（阻貶操作）"
            sold_usd = False
            sold_jpy = True
        else:
            action = description if description else "干預方向不明"
            sold_usd = False
            sold_jpy = True

        amount_display = f"{amount_100m:,} 億日圓" if amount_100m else "金額不明"
        date_display = intervention_date.strftime("%Y年%m月%d日")

        # 交叉比對 BoJ 資產負債表方向
        cb_direction = ""
        if cb_text:
            if "偏向日圓升值" in cb_text:
                cb_direction = "偏向日圓升值"
            elif "偏向日圓貶值" in cb_text:
                cb_direction = "偏向日圓貶值"

        # 判斷沖銷
        if sold_usd:
            # 賣美元（阻升）
            if cb_direction == "偏向日圓升值":
                effect_note = "✅ BoJ 配合 — 日銀資產負債表方向一致（偏向日圓升值）"
                plain_note = "財務省出手阻升，且日銀方向一致，干預較可能有效"
            else:
                effect_note = "干預有效性：BoJ 方向未確認，需持續觀察"
                plain_note = "財務省買入日圓阻升，日銀方向無法確認"
        else:
            # 賣日圓（阻貶）
            if cb_direction == "偏向日圓貶值":
                effect_note = "✅ BoJ 配合 — 日銀資產負債表方向一致，干預可能有效"
                plain_note = "財務省出手阻貶，日銀方向相同，根據《日圓王子》框架，未沖銷干預效果較持久"
            elif cb_direction == "偏向日圓升值":
                effect_note = "⚠️ 疑似沖銷 — 日銀資產負債表同期呈收縮，干預資金可能被日銀收回"
                plain_note = "財務省出手阻貶，但日銀方向相反。根據《日圓王子》的歷史案例，這種沖銷操作往往使干預失效，甚至讓日圓反轉升值"
            else:
                effect_note = "日銀資產方向無法確認，干預有效性存疑"
                plain_note = "財務省出手干預，但無法確認日銀是否配合，效果存疑"

        if days_ago > 90:
            return (
                f"近三個月無財務省外匯干預紀錄（上次干預：{date_display}）\n"
                f"解讀：市場目前未觸發財務省動作，日圓處於自然波動區間"
            )
        else:
            return (
                f"最近一次干預：{date_display}（{action}，{amount_display}）\n"
                f"干預有效性：{effect_note}\n"
                f"白話解讀：{plain_note}"
            )

    except Exception as exc:
        logger.exception("財務省干預資料抓取失敗: %s", exc)
        return None


def get_japan_bank_lending():
    """Werner 框架：日本民間信用 YoY（BIS）vs 名目 GDP YoY，判斷信用創造速度"""
    try:
        credit_rows = fetch_fred_points("CRDQJPAPABIS")
        gdp_rows = fetch_fred_points("JPNNGDP")

        def calc_yoy(rows):
            latest_date, latest_val = rows[-1]
            # 取 4 個季度前（與最新季 index 相差 4）
            if len(rows) < 5:
                raise ValueError("資料點不足以計算 YoY")
            prev_val = rows[-5][1]
            if prev_val == 0:
                raise ValueError("基期為 0")
            yoy = (latest_val - prev_val) / prev_val * 100
            q = (latest_date.month - 1) // 3 + 1
            label = f"{latest_date.year}-Q{q}"
            return yoy, label

        credit_yoy, credit_label = calc_yoy(credit_rows)
        gdp_yoy,    gdp_label    = calc_yoy(gdp_rows)

        diff = credit_yoy - gdp_yoy

        if credit_yoy > gdp_yoy + 5:
            interpretation = (
                f"⚠️ 信用擴張過快（超 GDP 增速 5% 以上），Werner 框架下需注意非生產性泡沫信用"
            )
        elif credit_yoy < -3:
            interpretation = "銀行信用萎縮（YoY 負成長），Werner 框架：信用收縮 → 日圓偏向升值壓力"
        else:
            interpretation = "民間信用與 GDP 增速相近，信用擴張屬正常範圍"

        if diff > 5:
            diff_interpretation = "投機性非生產信用過剩，泡沫風險↑"
        elif diff < -3:
            diff_interpretation = "信用萎縮超過 GDP 降速，日圓升值壓力↑"
        else:
            diff_interpretation = "信用增速與實體經濟相符"

        return (
            f"民間信用年增：{credit_yoy:+.1f}%（BIS，{credit_label}）\n"
            f"名目 GDP 年增：{gdp_yoy:+.1f}%（{gdp_label}）\n"
            f"解讀：{interpretation}\n"
            f"信用乖離率 ∆MF：{diff:+.1f}% → 解讀 {diff_interpretation}"
        )

    except Exception as exc:
        logger.exception("日本信用資料抓取失敗: %s", exc)
        return None


def get_bop_analysis():
    try:
        financial_account_rows = fetch_fred_points("JPNB6FATT01CXCUQ")
        current_account_rows = fetch_fred_points("JPNB6BLTT02STSAQ")
        if len(financial_account_rows) < 8:
            raise ValueError("資料點不足（JPNB6FATT01CXCUQ）")

        capital_flow_4q = sum(value for _, value in financial_account_rows[-4:])
        capital_flow_prev_4q = sum(value for _, value in financial_account_rows[-8:-4])
        yoy_delta = capital_flow_4q - capital_flow_prev_4q
        ca_pct = current_account_rows[-1][1]

        if capital_flow_4q > 0 and yoy_delta > 1e10:
            interpretation = (
                f"長期資本外流擴大（YoY +{yoy_delta/1e9:.0f}B USD），Werner：資金持續流出 → 日圓貶值壓力↑"
            )
        elif capital_flow_4q > 0 and abs(yoy_delta) <= 1e10:
            interpretation = "長期資本外流穩定，對日圓無明顯新壓力"
        elif capital_flow_4q < 0:
            interpretation = "資本淨流入日本 → 日圓升值支撐"
        else:
            interpretation = "金融帳資料不足"

        return (
            f"金融帳近4季：{capital_flow_4q/1e9:.0f}B USD（正＝流出）\n"
            f"經常帳：{ca_pct:.1f}% of GDP\n"
            f"解讀：{interpretation}"
        )
    except Exception as exc:
        logger.exception("國際收支資料抓取失敗: %s", exc)
        return None


def get_fiscal_financing():
    try:
        credit_rows = fetch_fred_points("CRDQJPBPABIS")
        gdp_rows = fetch_fred_points("JPNNGDP")

        credit_to_gdp = credit_rows[-1][1] / gdp_rows[-1][1] * 100
        credit_to_gdp_prev = credit_rows[-5][1] / gdp_rows[-5][1] * 100
        yoy_delta = credit_to_gdp - credit_to_gdp_prev

        if yoy_delta > 5:
            interpretation = (
                f"信用/GDP 年增 {yoy_delta:.1f} ppt，信用擴張快於實體，Werner：非生產性信用風險↑"
            )
        elif yoy_delta < -3:
            interpretation = (
                f"信用/GDP 年減 {abs(yoy_delta):.1f} ppt，信用收縮 → 貨幣緊縮效應，日圓升值傾向↑"
            )
        else:
            interpretation = f"信用/GDP 比率穩定，{yoy_delta:+.1f} ppt YoY"

        return (
            f"民間信用/GDP：{credit_to_gdp:.1f}%（YoY {yoy_delta:+.1f} ppt）\n"
            f"解讀：{interpretation}"
        )
    except Exception as exc:
        logger.exception("財政融資資料抓取失敗: %s", exc)
        return None


def get_manufactured_imports():
    try:
        import_rows = fetch_fred_points("XTIMVA01JPQ657S")
        latest_val = import_rows[-1][1]
        sum_4q = sum(value for _, value in import_rows[-4:])

        if sum_4q < -5:
            interpretation = f"近4季製成品進口累計萎縮 {sum_4q:.1f}%，通縮壓力加劇，日圓購買力下滑"
        elif sum_4q > 10:
            interpretation = f"近4季製成品進口擴張 {sum_4q:.1f}%，內需強勁，進口型通脹風險↑"
        else:
            interpretation = f"製成品進口穩定（近4季累計 {sum_4q:.1f}%），結構性通縮壓力平穩"

        return (
            f"製成品進口季增（最新）：{latest_val:+.2f}%\n"
            f"近4季累計：{sum_4q:.1f}%\n"
            f"解讀：{interpretation}"
        )
    except Exception as exc:
        logger.exception("製成品進口資料抓取失敗: %s", exc)
        return None


def get_eurjpy():
    try:
        hist = fetch_yfinance_history("EURJPY=X", period="5d")
        close = hist.get("Close")
        current = safe_last(close, "EUR/JPY Close")
        week_ago = safe_first(close, "EUR/JPY Close")
        change = current - week_ago
        return round(current, 2), round(change, 2)
    except Exception as exc:
        logger.exception("EUR/JPY 取得失敗: %s", exc)
        return None, None


def get_rsi(period=14):
    """計算 USD/JPY RSI(14)"""
    hist = fetch_yfinance_history("USDJPY=X", period="60d")
    close = hist.get("Close")
    if close is None or close.dropna().empty:
        raise ValueError("USD/JPY Close 無法計算 RSI")
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    rsi = round(float(safe_last(100 - 100 / (1 + rs), "RSI")), 1)
    if rsi >= 70:
        signal = "漲太多了，短線可能會回跌"
    elif rsi <= 30:
        signal = "跌太多了，短線可能會反彈"
    elif rsi >= 55:
        signal = "短線略偏強，但還不到過熱"
    elif rsi <= 45:
        signal = "短線略偏弱，但還不到超賣"
    else:
        signal = "短線方向不明，等待訊號"
    return rsi, signal


def get_entry_exit_levels(usdjpy_rate):
    """從 yfinance 歷史資料算 MA + 20日高低點 + RSI"""
    hist = fetch_yfinance_history("USDJPY=X", period="60d")
    close = hist.get("Close")
    if close is None or close.dropna().empty:
        raise ValueError("USD/JPY Close 無法計算技術面")
    ma20 = round(float(safe_last(close.rolling(20).mean(), "MA20")), 2)
    ma50 = round(float(safe_last(close.rolling(50).mean(), "MA50")), 2) if len(close.dropna()) >= 50 else None
    high20 = round(float(safe_last(close.rolling(20).max(), "20日高點")), 2)
    low20 = round(float(safe_last(close.rolling(20).min(), "20日低點")), 2)

    cur = round(usdjpy_rate, 2)
    levels = []
    if low20 < cur:
        levels.append((low20, "20日低點  近期支撐", "🟢"))
    if ma50 and ma50 < cur:
        levels.append((ma50, "MA50      中期均線", "🟡"))
    if ma20 < cur:
        levels.append((ma20, "MA20      短期均線", "🟡"))
    levels.append((cur, "現價", "▶️"))
    if high20 > cur:
        levels.append((high20, "20日高點  近期阻力", "🟠"))
    if ma20 > cur:
        levels.append((ma20, "MA20      短期均線", "🟠"))
    if ma50 and ma50 > cur:
        levels.append((ma50, "MA50      中期均線", "🔴"))

    plain = " / ".join(str(l[0]) for l in levels)
    if cur > ma20 and ma50 is not None and ma20 > ma50:
        position_parts = ["目前站在短中期均線之上，短線偏多"]
    elif cur > ma20 and (ma50 is None or cur > ma50):
        position_parts = ["目前站在短期均線之上，短線偏多"]
    elif ma50 is not None and ma20 > cur > ma50:
        position_parts = ["跌破短期均線（MA20），但仍在中期均線之上，短線轉弱"]
    elif cur < ma20 and (ma50 is None or cur < ma50):
        position_parts = ["短中期均線都在上方，短線偏空"]
    else:
        position_parts = ["目前卡在均線附近，短線方向不明"]

    if high20 and abs(cur - high20) / high20 < 0.005:
        position_parts.append("接近近期高點，上方壓力大")
    if low20 and abs(cur - low20) / low20 < 0.005:
        position_parts.append("接近近期低點，下方有支撐")

    position_text = "位置解讀：" + "；".join(position_parts)
    annotated = "\n".join(f"{icon} {price:.2f}  {label}" for price, label, icon in levels) + f"\n{position_text}"
    tech_levels = {
        "ma20": ma20,
        "ma50": ma50,
        "high20": high20,
        "low20": low20,
    }
    return plain, annotated, tech_levels


def get_weekly_verdict(usdjpy_rate, change, cot_text, news_text, us10y, jp10y, spread, rsi, rsi_signal, cb_text=None, mof_text=None, lending_text=None, boj_qe_text=None, signal_summary=None, bop_text=None, fiscal_text=None, mfg_import_text=None):
    """用 ChatGPT 寫本週判斷，納入利差與 RSI，並解釋 COT 方向"""
    direction = "走升" if change < 0 else "走貶"
    cb_prompt = f"央行資產負債表：{cb_text[:350]}\n" if cb_text else ""
    mof_prompt = f"財務省干預偵測：{mof_text[:200]}\n" if mof_text else ""
    signal_strength = 0
    signal_direction = "方向不明"
    if signal_summary:
        strength_match = re.search(r'偏向日圓升值（(\d+)/(\d+) 個訊號）', signal_summary)
        if strength_match:
            signal_strength = int(strength_match.group(1))
            signal_direction = "偏向日圓升值"
        else:
            strength_match = re.search(r'偏向日圓貶值（(\d+)/(\d+) 個訊號）', signal_summary)
            if strength_match:
                signal_strength = int(strength_match.group(1))
                signal_direction = "偏向日圓貶值"
            else:
                strength_match = re.search(r'方向分歧（各 (\d+)/(\d+) 個訊號）', signal_summary)
                if strength_match:
                    signal_strength = int(strength_match.group(1))
    cot_crowded = any(k in str(cot_text) for k in ["擁擠", "過度", "小心大跌", "小心反彈"])
    cot_crowded_text = "有，理由句尾請加上「但注意 COT 擁擠風險」" if cot_crowded else "無"
    context_parts = []
    if lending_text:
        context_parts.append(f"銀行放款速度：{lending_text[:200]}")
    if bop_text:
        context_parts.append(f"國際收支分析：{bop_text}")
    if fiscal_text:
        context_parts.append(f"財政融資結構：{fiscal_text}")
    if mfg_import_text:
        context_parts.append(f"製成品進口：{mfg_import_text}")
    if boj_qe_text:
        context_parts.append(f"BoJ QE類型：{boj_qe_text[:150]}")
    if signal_summary:
        context_parts.append(f"訊號一致性：{signal_summary}")
    context_prompt = "\n".join(context_parts)
    if context_prompt:
        context_prompt += "\n"
    prompt = (
        f"以下是本週日圓市場完整數據，請改用白話、像在跟台灣投資人解釋的方式，寫出本週判斷：\n\n"
        f"USD/JPY：{usdjpy_rate:.2f}，本週日圓{direction} {abs(change):.2f}\n"
        f"美日利差：美國10Y {us10y}% - 日本10Y {jp10y}% = {spread}%\n"
        f"RSI(14)：{rsi}（{rsi_signal}）\n"
        f"{cb_prompt}"
        f"{mof_prompt}"
        f"{context_prompt}"
        f"COT持倉：{cot_text[:250]}\n"
        f"本週事件：{news_text[:300]}\n\n"
        f"訊號強度：{signal_strength}\n"
        f"訊號方向：{signal_direction}\n"
        f"COT 擁擠警告：{cot_crowded_text}\n\n"
        "請將以下資訊整理成公開數據摘要，可以根據數據給出偏強、偏弱或方向分歧等判斷，但不要提供操作建議，也不得生成任何具體做多、做空、進出場、停損停利、目標價或部位配置建議：\n"
        "1. 先整理 Fed 與日銀資產負債表的相對變化\n"
        "2. 再整理 COT 大戶持倉現況與是否擁擠\n"
        "3. 補充 RSI 與技術面位置代表的市場狀態\n"
        "4. 最後交代美日利差目前數值與其限制\n\n"
        "若不同指標彼此矛盾，可以直接指出分歧，並說明為何暫時不能下單一結論。\n"
        "禁止使用任何交易指令語氣，例如建議買進、賣出、加碼、減碼、做多、做空，以及任何停損、目標價、進場點位或部位配置建議。\n\n"
        "請嚴格按照以下格式輸出，每一段都要白話、短、直接：\n"
        "【數據觀察摘要】第一行請用一句話整理本週重點數據狀態，可以直接寫偏強、偏弱、分歧或方向傾向\n"
        "理由：第二行寫 20 字以內白話理由；若有 COT 擁擠警告，這句尾端一定要補「但注意 COT 擁擠風險」\n"
        "風險：第三行固定寫「⚠️ 本段為公開數據整理，僅供風險辨識參考」\n"
        "摘要邏輯：根據本週各項指標數值與現象整理重點，允許延伸成日圓偏強、偏弱或分歧的方向判斷，但不能延伸成具體交易建議\n"
        "【央行在做什麼】先用白話總結 Fed 和日銀資產負債表近期變化，說明目前看到的數據現象\n"
        "【本週指標整理】用一句白話整理本週主要指標數值與現象，不用術語，可以補一句整體偏向\n"
        "【利率差距說什麼】美國利率比日本高 X%，代表什麼意思，並補一句這只是市場常見看法、不能單獨拿來判斷匯率\n"
        "【大戶在做什麼】用白話說明 COT 大戶部位現在的配置狀態，以及數量多代表什麼含義，要提醒是否過度擁擠\n"
        "【這週要盯什麼】最重要的一個事件或數字，用一句話說為什麼重要\n\n"
        "請用台灣投資人看得懂的語氣，每個專有名詞後面用括號解釋，例如：RSI（技術指標，衡量超買超賣）、COT（美國商品期貨委員會的大戶持倉報告），整段不超過320字，不要用英文縮寫。"
    )
    fallback = (
        "【數據觀察摘要】目前可整理的資料包括匯價、利差、技術指標與持倉變化\n"
        "理由：AI 判讀逾時，暫以既有數據交叉確認\n"
        "風險：⚠️ 本段為公開數據整理，僅供風險辨識參考\n"
        "【央行在做什麼】本次 AI 摘要未完成，請以 Fed 與日銀資產負債表變化為主\n"
        "【本週指標整理】本次 AI 摘要未完成，請先參考各項原始數據變化\n"
        "【利率差距說什麼】利差仍可參考，但不能單獨判斷匯率方向\n"
        "【大戶在做什麼】本次未取得完整 AI 解讀，請搭配 COT 原始數據判讀\n"
        "【這週要盯什麼】優先看央行訊號與高影響力經濟數據"
    )
    return run_text_command(['chatgpt', '-p', prompt], timeout=180, fallback_text=fallback)


# ───────────────────────────────────────────────
# 組合報告
# ───────────────────────────────────────────────

def build_full_report(now, usdjpy, direction, change, pct, danger_zone,
                      cot, news, calendar, levels_plain, levels_annotated, verdict,
                      us10y=None, jp10y=None, spread=None, spread_trend=None, rsi=None, rsi_signal=None,
                      cb_text=None, mof_text=None, lending_text=None,
                      boj_qe_text=None, eurjpy_text=None, signal_summary=None,
                      bop_text=None, fiscal_text=None, mfg_import_text=None,
                      werner_block=None):
    """純文字版，存檔用"""
    werner_section = (
        f"\n━━ Werner 四原則方向判斷 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{werner_block}\n"
        if werner_block else ""
    )
    eurjpy_line = f"EUR/JPY 確認　{eurjpy_text}\n" if eurjpy_text else ""
    rate_line = (f"美日利差　{us10y}% - {jp10y}% = {spread}%　{spread_trend}\n"
                 f"RSI(14)　{rsi}　{rsi_signal}\n") if us10y else ""
    cb_block = f"\n━━ 央行資產負債表 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{cb_text}\n" if cb_text else ""
    boj_qe_block = f"\n━━ BoJ QE 類型（Werner框架）━━━━━━━━━━━━━━━━━━━━━━━\n\n{boj_qe_text}\n" if boj_qe_text else ""
    mof_block = f"\n━━ 財務省干預偵測 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{mof_text}\n" if mof_text else ""
    lending_block = f"\n━━ 日本銀行放款速度 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{lending_text}\n" if lending_text else ""
    bop_block = f"\n【🌊 國際收支】\n{bop_text}" if bop_text else ""
    fiscal_block = f"\n【🏛 財政融資結構】\n{fiscal_text}" if fiscal_text else ""
    mfg_import_block = f"\n【📦 製成品進口】\n{mfg_import_text}" if mfg_import_text else ""
    signal_block = f"\n━━ 訊號一致性 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{signal_summary}\n" if signal_summary else ""
    return f"""日圓週報　{now}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ 聲明：本報告為自動化數據整理系統，內容由 AI 根據公開數據生成，未經人工審核，不代表任何投資立場，不構成任何投資建議。使用者應自行判斷，投資有風險。

USD/JPY　{usdjpy:.2f}　　本週日圓{direction} {abs(change):.2f}（{pct:.2f}%）
{danger_zone}
{eurjpy_line}{rate_line}━━ 大戶持倉（CFTC COT）━━━━━━━━━━━━━━━━━━━━━━━━━

{cot}
{cb_block}
{boj_qe_block}
{mof_block}
{lending_block}
{bop_block}
{fiscal_block}
{mfg_import_block}
{signal_block}

━━ 本週重要事件 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{news}

━━ 下週行事曆 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{calendar}

━━ 技術面關鍵區間 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{levels_plain}

{levels_annotated}

━━ 本週數據指向 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{verdict}
{werner_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
本報告為個人市場觀察記錄，所有數字與內容僅供參考，不構成任何投資建議。讀者應自行判斷並承擔投資風險。"""
# ───────────────────────────────────────────────
# 主程式
# ───────────────────────────────────────────────

def main():
    logger.info("正在產生本週日圓投資報告")

    data_failures = []

    usdjpy_data = None
    try:
        usdjpy_data = get_usdjpy()
        logger.info("資料源 USD/JPY 成功")
    except Exception as exc:
        data_failures.append(("USD/JPY", f"{type(exc).__name__}: {exc}"))
        logger.exception("資料源 USD/JPY 失敗: %s", exc)
        raise

    usdjpy, change = usdjpy_data
    direction = "升值" if change < 0 else "貶值"
    pct = abs(change) / usdjpy * 100
    now = datetime.now().strftime("%Y年%m月%d日")

    if usdjpy >= DANGER_HIGH:
        danger_zone = f"目前位置已突破 {DANGER_HIGH} 停損警戒線，需重新評估部位。"
    elif usdjpy >= DANGER_MID:
        danger_zone = f"接近 {DANGER_MID} 干預紅線，上方空間受限，留意財務省動向。"
    else:
        danger_zone = ""

    logger.info("平行查詢本週消息、COT、行事曆、利差與央行資產負債表中")
    with ThreadPoolExecutor(max_workers=10) as executor:
        news_future     = executor.submit(get_news_from_gemini)
        cot_future      = executor.submit(get_cot_with_history)
        tff_future      = executor.submit(get_tff_data)
        calendar_future = executor.submit(get_economic_calendar)
        rate_future     = executor.submit(get_rate_differential)
        spread_2y_future = executor.submit(get_us2y_jp2y_spread)
        meeting_future  = executor.submit(get_next_meeting_countdown)
        cb_future       = executor.submit(get_cb_balance_sheets)
        rsi_future      = executor.submit(get_rsi)
        lending_future  = executor.submit(get_japan_bank_lending)
        bop_future      = executor.submit(get_bop_analysis)
        fiscal_future   = executor.submit(get_fiscal_financing)
        mfg_import_future = executor.submit(get_manufactured_imports)
        boj_qe_future   = executor.submit(get_boj_qe_type)
        news = collect_data_source_result("Gemini 本週消息", news_future, data_failures) or ""
        cot_result = collect_data_source_result(
            "CFTC COT",
            cot_future,
            data_failures,
            validator=lambda value: isinstance(value, tuple) and len(value) == 2 and bool(value[0]) and bool(value[1]),
        )
        if cot_result:
            cot, cot_history = cot_result
        else:
            cot, cot_history = "COT 資料暫時無法取得", []
        tff_data = collect_data_source_result("CFTC TFF", tff_future, data_failures) or {}
        calendar = collect_data_source_result("ForexFactory 行事曆", calendar_future, data_failures) or "行事曆資料暫時無法取得"
        rate_result = collect_data_source_result(
            "美日 10Y 利差",
            rate_future,
            data_failures,
            validator=lambda value: isinstance(value, tuple) and len(value) == 4 and all(item is not None for item in value[:3]),
        )
        if rate_result:
            us10y, jp10y, spread, spread_trend = rate_result
        else:
            us10y, jp10y, spread, spread_trend = 0.0, 0.0, 0.0, "資料暫時無法取得"
        spread_2y_data = collect_data_source_result("美日 2Y 利差", spread_2y_future, data_failures) or {}
        meeting_data = collect_data_source_result("央行會議倒數", meeting_future, data_failures) or {}
        cb_text = collect_data_source_result("Fed/BoJ 資產負債表", cb_future, data_failures)
        rsi_result = collect_data_source_result(
            "USD/JPY RSI",
            rsi_future,
            data_failures,
            validator=lambda value: isinstance(value, tuple) and len(value) == 2 and value[0] is not None,
        )
        if rsi_result:
            rsi, rsi_signal = rsi_result
        else:
            rsi, rsi_signal = 50.0, "資料暫時無法取得"
        lending_text = collect_data_source_result("日本銀行放款", lending_future, data_failures)
        bop_text = collect_data_source_result("日本國際收支", bop_future, data_failures)
        fiscal_text = collect_data_source_result("日本財政融資", fiscal_future, data_failures)
        mfg_import_text = collect_data_source_result("日本製成品進口", mfg_import_future, data_failures)
        boj_qe_text = collect_data_source_result("BoJ QE 類型", boj_qe_future, data_failures)

    try:
        mof_text = get_mof_intervention(cb_text)
        if mof_text:
            logger.info("資料源 MOF 干預紀錄 成功")
        else:
            data_failures.append(("MOF 干預紀錄", "資料為空或不完整"))
            logger.warning("資料源 MOF 干預紀錄 失敗: 資料為空或不完整")
    except Exception as exc:
        mof_text = None
        data_failures.append(("MOF 干預紀錄", f"{type(exc).__name__}: {exc}"))
        logger.exception("資料源 MOF 干預紀錄 失敗: %s", exc)

    try:
        eurjpy, eurjpy_change = get_eurjpy()
        if eurjpy is not None:
            logger.info("資料源 EUR/JPY 成功")
        else:
            data_failures.append(("EUR/JPY", "資料為空或不完整"))
            logger.warning("資料源 EUR/JPY 失敗: 資料為空或不完整")
    except Exception as exc:
        eurjpy, eurjpy_change = None, None
        data_failures.append(("EUR/JPY", f"{type(exc).__name__}: {exc}"))
        logger.exception("資料源 EUR/JPY 失敗: %s", exc)

    send_data_health_alert(data_failures)

    if eurjpy is not None:
        eurjpy_dir = "升值" if eurjpy_change < 0 else "貶值"
        if (change < 0) == (eurjpy_change < 0):
            confirm = "方向一致 → 日圓整體走勢，非美元單邊事件"
        else:
            confirm = "方向不一致 → 可能只是美元單邊波動，日圓整體方向待觀察"
        eurjpy_text = (
            f"EUR/JPY {eurjpy:.2f}　本週日圓{eurjpy_dir} {abs(eurjpy_change):.2f}\n"
            f"與 USD/JPY 比對：{confirm}"
        )
    else:
        eurjpy_text = None

    logger.info("計算技術面區間中")
    levels_plain, levels_annotated, tech_levels = get_entry_exit_levels(usdjpy)

    # 計算訊號一致性
    signals_bullish = []
    signals_bearish = []

    if cb_text and '偏向日圓升值' in cb_text:
        signals_bullish.append('央行資產負債表')
    elif cb_text and '偏向日圓貶值' in cb_text:
        signals_bearish.append('央行資產負債表')

    pct_match = re.search(r'有\s*(\d+)%\s*的時間', cot)
    if pct_match:
        cot_pct = int(pct_match.group(1))
        if cot_pct >= 60:
            signals_bullish.append('COT大戶持倉')
        elif cot_pct <= 40:
            signals_bearish.append('COT大戶持倉')

    if rsi <= 45:
        signals_bullish.append('RSI技術指標')
    elif rsi >= 55:
        signals_bearish.append('RSI技術指標')

    if usdjpy > (tech_levels.get('ma20') or 0) and usdjpy > (tech_levels.get('ma50') or 0):
        signals_bearish.append('技術面均線位置')
    elif usdjpy < (tech_levels.get('ma20') or 999) and usdjpy < (tech_levels.get('ma50') or 999):
        signals_bullish.append('技術面均線位置')

    if eurjpy_change is not None:
        if (change < 0) == (eurjpy_change < 0):
            if change < 0:
                signals_bullish.append('EUR/JPY確認')
            else:
                signals_bearish.append('EUR/JPY確認')

    total_signals = len(signals_bullish) + len(signals_bearish)
    if total_signals > 0:
        if len(signals_bullish) > len(signals_bearish):
            dominant = f"偏向日圓升值（{len(signals_bullish)}/{total_signals} 個訊號）"
            dominant_detail = "、".join(signals_bullish)
        elif len(signals_bearish) > len(signals_bullish):
            dominant = f"偏向日圓貶值（{len(signals_bearish)}/{total_signals} 個訊號）"
            dominant_detail = "、".join(signals_bearish)
        else:
            dominant = f"方向分歧（各 {len(signals_bullish)}/{total_signals} 個訊號）"
            dominant_detail = f"升值：{'、'.join(signals_bullish)}；貶值：{'、'.join(signals_bearish)}"
        signal_summary = f"本週訊號一致性：{dominant}\n看漲訊號：{'、'.join(signals_bullish) or '無'}　看跌訊號：{'、'.join(signals_bearish) or '無'}"
    else:
        signal_summary = "本週訊號方向不明"

    # ── Werner 四原則判斷 ──────────────────────────────────
    def _w_parse_p1(text):
        if text and "偏向日圓升值" in text:
            return {"direction": "升", "strength": "中"}
        if text and "偏向日圓貶值" in text:
            return {"direction": "貶", "strength": "中"}
        return {"direction": "中性", "strength": "弱"}

    def _w_parse_p2(text):
        if not text or "近三個月無" in text:
            return {"direction": "中性", "strength": "弱"}
        if "疑似沖銷" in text or ("沖銷" in text and "未沖銷" not in text and "BoJ 配合" not in text):
            return {"direction": "中性", "strength": "弱"}
        if "阻貶" in text or "賣出日圓" in text:
            return {"direction": "貶", "strength": "中"}
        if "阻升" in text or "賣出美元" in text:
            return {"direction": "升", "strength": "中"}
        return {"direction": "中性", "strength": "弱"}

    def _w_parse_p3(boj_text, lend_text):
        if boj_text and "縮表" in boj_text:
            return {"direction": "升", "strength": "中"}
        if boj_text and "QE2" in boj_text:
            return {"direction": "貶", "strength": "中"}
        if lend_text and ("信用萎縮" in lend_text or "負成長" in lend_text):
            return {"direction": "升", "strength": "中"}
        if lend_text and ("泡沫" in lend_text or "信用擴張過快" in lend_text):
            return {"direction": "貶", "strength": "中"}
        return {"direction": "中性", "strength": "弱"}

    def _w_parse_p4(text):
        if not text:
            return {"direction": "中性", "strength": "弱"}
        if "資本淨流入" in text:
            return {"direction": "升", "strength": "中"}
        if "資本外流擴大" in text or "外流擴大" in text:
            return {"direction": "貶", "strength": "中"}
        return {"direction": "中性", "strength": "弱"}

    w_p1 = _w_parse_p1(cb_text)
    w_p2 = _w_parse_p2(mof_text)
    w_p3 = _w_parse_p3(boj_qe_text, lending_text)
    w_p4 = _w_parse_p4(bop_text)
    w_result = evaluate_jpy_direction(w_p1, w_p2, w_p3, w_p4)
    werner_block = (
        f"主導原則：{w_result['leader']}　最終方向：{w_result['direction']}　信心：{w_result['confidence']}\n"
        f"支持：{'、'.join(w_result['supporting']) or '無'}　反對：{'、'.join(w_result['opposing']) or '無'}\n"
        f"P1 信用速度={w_p1['direction']}({w_p1['strength']})　"
        f"P2 干預={w_p2['direction']}({w_p2['strength']})　"
        f"P3 信用質={w_p3['direction']}({w_p3['strength']})　"
        f"P4 資本流={w_p4['direction']}({w_p4['strength']})"
    )
    logger.info("Werner判斷：%s", w_result)

    logger.info("產生本週判斷中")
    verdict = get_weekly_verdict(usdjpy, change, cot, news, us10y, jp10y, spread, rsi, rsi_signal, cb_text, mof_text, lending_text, boj_qe_text, signal_summary, bop_text=bop_text, fiscal_text=fiscal_text, mfg_import_text=mfg_import_text)

    # 存純文字檔
    report = build_full_report(now, usdjpy, direction, change, pct, danger_zone,
                               cot, news, calendar, levels_plain, levels_annotated, verdict,
                               us10y, jp10y, spread, spread_trend, rsi, rsi_signal, cb_text, mof_text, lending_text,
                               boj_qe_text, eurjpy_text, signal_summary, bop_text=bop_text, fiscal_text=fiscal_text, mfg_import_text=mfg_import_text,
                               werner_block=werner_block)
    output_path = os.path.expanduser(f"~/Desktop/投資/日圓週報_{datetime.now().strftime('%Y%m%d')}.txt")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)

    logger.info("報告內容如下\n%s", report)
    logger.info("報告已存到：%s", output_path)

    # 發 Telegram（圖片卡片 + Telegraph 完整報告）
    logger.info("發送 Telegram 中")
    card_status = build_card_status_snapshot(cb_text, spread_2y_data, usdjpy)
    card_data = {
        'date': now, 'price': usdjpy, 'change': change, 'pct': pct,
        'danger': danger_zone, 'cot': cot, 'cot_history': cot_history, 'news': news, 'verdict': verdict,
        'calendar': calendar,
        'tech': tech_levels,
        'cb': cb_text,
        'mof': mof_text,
        'signal_summary': signal_summary,
        'boj_qe': boj_qe_text,
        'spread_2y_text': spread_2y_data.get('text', ''),
        'meeting_countdown': meeting_data,
        'lending': lending_text,
        'bop': bop_text,
        'fiscal': fiscal_text,
        'mfg_import': mfg_import_text,
        'tff_lev_net': tff_data.get('tff_lev_net'),
        'tff_lev_pct': tff_data.get('tff_lev_pct'),
        'status_tags': card_status,
    }

    try:
        # Telegraph token 快取
        if os.path.exists(TG_TOKEN_FILE):
            with open(TG_TOKEN_FILE) as f:
                tg_ph_token = f.read().strip()
        else:
            tg_ph_token = create_telegraph_account()
            with open(TG_TOKEN_FILE, 'w') as f:
                f.write(tg_ph_token)

        # 生成圖片
        img = draw_card(card_data)
        img_path = REPORT_CARD
        img.save(img_path, quality=95)

        # 保留 GitHub Pages 產出，不影響既有報告流程
        html_report = build_html(card_data)
        gh_url = push_to_github_pages(html_report, now)
        logger.info("GitHub Pages 已更新 %s", gh_url)

        # 發佈 Telegraph，供 VIP 取得完整網址
        tg_nodes = build_nodes(card_data)
        telegraph_url = publish_to_telegraph(tg_ph_token, f"日圓週報　{now}", tg_nodes)

        summary = build_direction_summary(verdict, direction, change)

        public_result = send_public_report(img_path, summary)
        if public_result.json().get('ok'):
            logger.info("公開 Telegram 已送出")
        else:
            logger.error("公開 Telegram 發送失敗：%s", public_result.json())

        send_vip_report(report, img_path, telegraph_url)
        if TG_VIP:
            logger.info("VIP Telegram 已送出 %s", telegraph_url)
    except Exception as exc:
        logger.exception("發送失敗：%s", exc)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logger.exception("jpy_weekly_report.py 執行崩潰: %s", exc)
        send_emergency_telegram("jpy_weekly_report.py", exc)
        raise
