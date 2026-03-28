import html
import logging
import re

logger = logging.getLogger(__name__)


ALLOWED_TELEGRAM_HTML_PATTERN = re.compile(r"(</?(?:b|code|blockquote)>|<br>)")

def _format_verdict(text: str) -> str:
    replacements = {
        "【數據觀察摘要】": "\n▪️ 總結　",
        "【央行在做什麼】": "\n▪️ 央行　",
        "【利率差距說什麼】": "\n▪️ 利差　",
        "【大戶在做什麼】": "\n▪️ 大戶　",
        "【這週要盯什麼】": "\n▪️ 下週觀察　",
        "【本週指標整理】": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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


def build_full_report(now, usdjpy, direction, change, pct, danger_zone,
                      cot, news, calendar, levels_plain, levels_annotated, verdict,
                      us10y=None, jp10y=None, spread=None, spread_trend=None, rsi=None, rsi_signal=None,
                      cb_text=None, mof_text=None, lending_text=None,
                      boj_qe_text=None, eurjpy_text=None, signal_summary=None,
                      bop_text=None, fiscal_text=None, mfg_import_text=None,
                      werner_block=None, divergence_note=None, action_note=None, position_score=None):
    """純文字版，存檔用"""
    divergence_line = f"\n{divergence_note}" if divergence_note else ""
    if action_note:
        action_section = f'\n【行動建議】{action_note}\n【Position Score】{position_score:+g}\n'
    else:
        action_section = ''
    werner_section = (
        f"\n━━ 結構判斷（Werner 四原則）━━━━━━━━━━━━━━━━━━━━━━━━\n\n【結構判斷（Werner）】\n{werner_block}{divergence_line}{action_section}\n"
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
    trimmed_verdict = _format_verdict(verdict) if verdict else ""
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

━━ 本週重要事件 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{news}

━━ 下週行事曆 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{calendar}

━━ 技術面關鍵區間 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{levels_plain}

{levels_annotated}

━━ 短線觀察（技術 / COT）━━━━━━━━━━━━━━━━━━━━━━━━━

{trimmed_verdict}
{werner_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
本報告為個人市場觀察記錄，所有數字與內容僅供參考，不構成任何投資建議。讀者應自行判斷並承擔投資風險。"""
