import csv
import io
import json
import logging
import os
import re
import zipfile
from datetime import datetime, timedelta

import yfinance as yf

from config import (
    BOJ_QE_CACHE,
    CALENDAR_CACHE,
    COT_HISTORY,
    FRED_BOP_CACHE,
    FRED_CB_CACHE,
    FRED_FISCAL_CACHE,
    FRED_LENDING_CACHE,
    FRED_MFG_CACHE,
)
from data_provider import fetch_fred_points, fetch_latest_jgb_curve_row, fetch_yfinance_history
from utils import (
    clean_gemini_output,
    extract_json_object,
    http_get,
    http_post,
    is_missing_result,
    load_text_cache,
    run_text_command,
    safe_first,
    safe_last,
    save_text_cache,
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
        bullish_weeks = sum(1 for item in recent if item["net_short"] > 0)
        if bullish_weeks >= 6:
            trend_label = "多頭趨勢"
        elif bullish_weeks >= 3:
            trend_label = "震盪"
        else:
            trend_label = "空頭趨勢"
        analysis += f"\n近8週：{bullish_weeks}週看多 → {trend_label}"

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
    result = run_text_command(['gemini', '-p', prompt, '--model', 'gemini-2.5-pro', '--yolo'], timeout=180, fallback_text=fallback)
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

        result = (
            f"Fed 總資產：{fed_latest:,.0f} 百萬美元（{fed_latest_date:%Y-%m-%d}，較 {fed_anchor_date:%Y-%m-%d} "
            f"{fed_change:+.2f}%）\n"
            f"日銀總資產：{boj_latest:,.0f} 百萬日圓（{boj_latest_date:%Y-%m-%d}，較 {boj_anchor_date:%Y-%m-%d} "
            f"{boj_change:+.2f}%）\n"
            f"方向：{direction}\n"
            f"解讀：{detail}"
        )
        save_text_cache(FRED_CB_CACHE, result)
        return result
    except Exception as exc:
        logger.exception("央行資產負債表抓取失敗: %s", exc)
        cached = load_text_cache(FRED_CB_CACHE)
        if cached:
            return cached + "\n⚠️ [fallback_used=True] 本段資料來自上次快取，非即時數據"
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
        result = run_text_command(['gemini', '-p', prompt, '--model', 'gemini-2.5-pro', '--yolo'], timeout=180, fallback_text=fallback)
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
        amount_raw = last_record[6].strip().replace(",", "").replace('\"', "")
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

        result = (
            f"民間信用年增：{credit_yoy:+.1f}%（BIS，{credit_label}）\n"
            f"名目 GDP 年增：{gdp_yoy:+.1f}%（{gdp_label}）\n"
            f"解讀：{interpretation}\n"
            f"信用乖離率 ∆MF：{diff:+.1f}% → 解讀 {diff_interpretation}"
        )
        save_text_cache(FRED_LENDING_CACHE, result)
        return result

    except Exception as exc:
        logger.exception("日本信用資料抓取失敗: %s", exc)
        cached = load_text_cache(FRED_LENDING_CACHE)
        if cached:
            return cached + "\n⚠️ [fallback_used=True] 本段資料來自上次快取，非即時數據"
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

        result = (
            f"金融帳近4季：{capital_flow_4q/1e9:.0f}B USD（正＝流出）\n"
            f"經常帳：{ca_pct:.1f}% of GDP\n"
            f"解讀：{interpretation}"
        )
        save_text_cache(FRED_BOP_CACHE, result)
        return result
    except Exception as exc:
        logger.exception("國際收支資料抓取失敗: %s", exc)
        cached = load_text_cache(FRED_BOP_CACHE)
        if cached:
            return cached + "\n⚠️ [fallback_used=True] 本段資料來自上次快取，非即時數據"
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

        result = (
            f"民間信用/GDP：{credit_to_gdp:.1f}%（YoY {yoy_delta:+.1f} ppt）\n"
            f"解讀：{interpretation}"
        )
        save_text_cache(FRED_FISCAL_CACHE, result)
        return result
    except Exception as exc:
        logger.exception("財政融資資料抓取失敗: %s", exc)
        cached = load_text_cache(FRED_FISCAL_CACHE)
        if cached:
            return cached + "\n⚠️ [fallback_used=True] 本段資料來自上次快取，非即時數據"
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

        result = (
            f"製成品進口季增（最新）：{latest_val:+.2f}%\n"
            f"近4季累計：{sum_4q:.1f}%\n"
            f"解讀：{interpretation}"
        )
        save_text_cache(FRED_MFG_CACHE, result)
        return result
    except Exception as exc:
        logger.exception("製成品進口資料抓取失敗: %s", exc)
        cached = load_text_cache(FRED_MFG_CACHE)
        if cached:
            return cached + "\n⚠️ [fallback_used=True] 本段資料來自上次快取，非即時數據"
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
