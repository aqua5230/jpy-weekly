#!/usr/bin/env python3
"""
日圓週報自動化系統
每週一早上執行，產出投資參考報告
"""
import logging
from concurrent.futures import ThreadPoolExecutor
import re
import os
from datetime import datetime
from config import (
    DANGER_HIGH,
    DANGER_MID,
    TG_TOKEN_FILE,
    LOG_FILE,
    REPORT_CARD,
)
from data_fetcher import (
    collect_data_source_result,
    get_usdjpy, load_cot_history, get_cot_with_history,
    get_tff_data, get_news_from_gemini, get_economic_calendar,
    get_rate_differential, get_us2y_jp2y_spread, get_next_meeting_countdown,
    get_cb_balance_sheets, get_boj_qe_type, get_mof_intervention,
    get_japan_bank_lending, get_bop_analysis, get_fiscal_financing,
    get_manufactured_imports, get_eurjpy, get_rsi, get_entry_exit_levels,
)
from test_image import draw_card
from test_telegraph import create_telegraph_account, publish_to_telegraph, build_nodes
from build_html_report import build_html, push_to_github_pages
from decision_engine import decide_jpy_direction, evaluate_jpy_direction
from report_builder import (
    ALLOWED_TELEGRAM_HTML_PATTERN,
    escape_html_preserving_allowed_tags,
    parse_tagged_blocks,
    extract_vip_highlights,
    build_vip_report_html,
    build_card_status_snapshot,
    build_full_report,
)
from signal_analyzer import get_weekly_verdict
from telegram_sender import TELEGRAM_DISCLAIMER, append_telegram_disclaimer, send_emergency_telegram, split_telegram_text, build_direction_summary, send_photo_to_chat, send_public_report, send_vip_report

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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

    # ── R2：分歧偵測 ────────────────────────────────────
    def _parse_signal_direction(text):
        """從 signal_analyzer 的 verdict 文字中，提取方向傾向"""
        t = str(text or "")
        if any(k in t for k in ["偏向日圓升值", "偏強", "升值空間", "走升"]):
            return "升"
        if any(k in t for k in ["偏向日圓貶值", "偏弱", "貶值壓力", "走貶"]):
            return "貶"
        return "中性"

    signal_dir = _parse_signal_direction(verdict)
    werner_dir = w_result["direction"]
    divergence_note = (
        "→ 結構與短線分歧"
        if signal_dir != "中性" and werner_dir != "中性" and signal_dir != werner_dir
        else ""
    )

    # 存純文字檔
    report = build_full_report(now, usdjpy, direction, change, pct, danger_zone,
                               cot, news, calendar, levels_plain, levels_annotated, verdict,
                               us10y, jp10y, spread, spread_trend, rsi, rsi_signal, cb_text, mof_text, lending_text,
                               boj_qe_text, eurjpy_text, signal_summary, bop_text=bop_text, fiscal_text=fiscal_text, mfg_import_text=mfg_import_text,
                               werner_block=werner_block, divergence_note=divergence_note)
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
