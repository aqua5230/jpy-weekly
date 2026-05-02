#!/usr/bin/env python3
"""生成 HTML 週報並 push 到 GitHub Pages"""
import json
import logging
import os
import re
from pathlib import Path

BASE_DIR = Path(os.environ.get("JPY_BASE_DIR", Path(__file__).resolve().parent))
REPO_DIR = BASE_DIR / ".gh-pages"
DIST_DIR = BASE_DIR / "dist"
COT_HISTORY_FILE = BASE_DIR / ".cot_history.json"
logger = logging.getLogger(__name__)


def _esc(s):
    if not s:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _percentile(values, percentile):
    if not values:
        return None
    sorted_values = sorted(values)
    index = int((len(sorted_values) - 1) * percentile)
    return sorted_values[index]


def _cot_rank_percentile(values, target):
    if not values:
        return 0
    return round(sum(1 for value in values if value <= target) / len(values) * 100)


def _normalize_cot_history_rows(items):
    rows = []
    for item in items or []:
        if isinstance(item, dict):
            date = item.get("date")
            value = item.get("net_short")
        else:
            date = None
            value = item
        if value is None:
            continue
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        rows.append({"date": str(date) if date else "", "net_short": value})
    return rows


def _load_cot_history_rows(cot_history=None):
    try:
        if COT_HISTORY_FILE.exists():
            with open(COT_HISTORY_FILE, encoding="utf-8") as f:
                file_rows = _normalize_cot_history_rows(json.load(f))
            if file_rows:
                return file_rows[-52:]
    except Exception:
        pass
    return _normalize_cot_history_rows(cot_history)[-52:]


def _color_line(text):
    """依關鍵字給行上色"""
    t = str(text)
    if any(k in t for k in ["升值", "偏強", "看漲", "支撐", "收縮"]):
        return "green"
    if any(k in t for k in ["貶值", "偏弱", "看跌", "外流", "壓力"]):
        return "red"
    if any(k in t for k in ["⚠", "警戒", "過度", "擁擠"]):
        return "orange"
    return ""


def _section(icon, title, body_html):
    return f"""
<section>
  <div class="sec-header">{icon} {_esc(title)}</div>
  <div class="sec-body">{body_html}</div>
</section>"""


def _parse_tagged_blocks(text):
    blocks = []
    current_label = None
    current_lines = []
    for raw_line in str(text or "").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r'【(.+?)】(.*)', line)
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


def _verdict_html(text, skip_labels=None):
    """把【標籤】內容 渲染成卡片區塊"""
    if not text:
        return "<span class='dim'>—</span>"
    skip_labels = set(skip_labels or [])
    out = []
    for block in _parse_tagged_blocks(text):
        label = block.get("label")
        lines = [ln for ln in block.get("lines", []) if ln]
        if label in skip_labels:
            continue
        if label:
            body = "<br>".join(_esc(ln) for ln in lines) if lines else ""
            body_text = " ".join(lines)
            c = _color_line(body_text)
            body_cls = f' class="{c}"' if c else ""
            out.append(
                f'<div class="verdict-block">'
                f'<span class="verdict-label">【{_esc(label)}】</span>'
                f'<span{body_cls}>{body}</span>'
                f'</div>'
            )
        else:
            for ln in lines:
                c = _color_line(ln)
                cls = f' class="{c}"' if c else ""
                out.append(f"<div{cls}>{_esc(ln)}</div>")
    return "\n".join(out) if out else "<span class='dim'>—</span>"


def _disclaimer_card_html():
    return (
        '<section class="disclaimer-card">'
        '<div class="sec-header">⚠️ 免責聲明</div>'
        '<div class="sec-body">'
        '<div>本報告根據公開數據與自動化流程整理，內容僅供參考，非投資建議。</div>'
        '<div>報告不提供具體做多、做空、進出場或部位配置建議，使用者應自行評估風險。</div>'
        '</div>'
        '</section>'
    )


def _lines_html(text, max_lines=99):
    if not text:
        return "<span class='dim'>—</span>"
    out = []
    for ln in str(text).split("\n")[:max_lines]:
        ln = ln.strip()
        if not ln:
            continue
        c = _color_line(ln)
        cls = f' class="{c}"' if c else ""
        out.append(f"<div{cls}>{_esc(ln)}</div>")
    return "\n".join(out) if out else "<span class='dim'>—</span>"


def _tech_table(tech, current_price):
    if not tech:
        return ""
    items = [
        ("ma20",   "MA20 短期均線"),
        ("ma50",   "MA50 中期均線"),
        ("high20", "20日高點"),
        ("low20",  "20日低點"),
    ]
    levels = []
    for key, label in items:
        p = tech.get(key)
        if p is None:
            continue
        if p < current_price:
            cls = "green"
        elif p > current_price:
            cls = "red"
        else:
            cls = "yellow"
        levels.append((p, f'<tr><td class="mono {cls}">{p:.2f}</td><td>{label}</td></tr>'))
    lower_levels = sorted((level for level in levels if level[0] < current_price), key=lambda x: x[0], reverse=True)
    upper_levels = sorted((level for level in levels if level[0] > current_price), key=lambda x: x[0], reverse=True)
    current_row = f'<tr class="current-row"><td class="mono blue">{current_price:.2f}</td><td>▶ 現價</td></tr>'
    all_rows = [row for _, row in upper_levels] + [current_row] + [row for _, row in lower_levels]
    return f"<div class='tech-table-wrap'><table class='tech-table'>{''.join(all_rows)}</table></div>"


def _cot_sparkline(cot_history):
    """CSS bar chart，不依賴 Unicode 方塊字元"""
    if not cot_history or len(cot_history) < 2:
        return ""
    display_history = cot_history[-8:] if len(cot_history) > 8 else cot_history
    if not display_history:
        return ""
    max_abs = max(abs(v) for v in display_history) or 1
    prev_value = display_history[-2] if len(display_history) >= 2 else None
    latest_value = display_history[-1] if display_history else None
    wow_ratio = 0
    if prev_value is not None and latest_value is not None:
        if prev_value == 0:
            if latest_value > 0:
                wow_ratio = float("inf")
            elif latest_value < 0:
                wow_ratio = float("-inf")
        else:
            wow_ratio = (latest_value - prev_value) / abs(prev_value)
    bars = ""
    for i, v in enumerate(display_history):
        bar_pct = int(abs(v) / max_abs * 100)
        is_last = i == len(display_history) - 1
        if is_last:
            if wow_ratio > 0.5:
                bg = "#f0883e"
            elif wow_ratio < -0.5:
                bg = "#f85149"
            else:
                bg = "#3fb950"
        else:
            bg = "var(--green)" if v > 0 else "var(--red)"
        opacity = "1" if is_last else "0.5"
        weeks_ago = len(display_history) - 1 - i
        value_label = f'{v/1000:+.0f}k'
        if is_last and wow_ratio > 0.5:
            value_label = f'⚠️ {value_label}'
        bars += (f'<div style="display:flex;align-items:center;gap:6px;margin:1px 0">'
                 f'<div style="font-size:10px;color:var(--dim);width:24px;text-align:right;line-height:1.1">'
                 f'{"本週" if is_last else f"-{weeks_ago}W"}</div>'
                 f'<div style="position:relative;flex:1;height:8px">'
                 f'<div style="position:absolute;left:0;top:0;bottom:0;width:1px;background:var(--border)"></div>'
                 f'<div style="height:8px;width:{max(bar_pct,2) if v else 0}%;background:{bg};opacity:{opacity};border-radius:2px"></div>'
                 f'</div>'
                 f'<div style="font-size:10px;line-height:1.1;color:{"var(--white)" if is_last else "var(--dim)"}">'
                 f'{value_label}</div>'
                 f'</div>')
    return (f'<div style="margin-top:10px">'
             f'<div style="font-size:12px;color:var(--dim);margin-bottom:2px">近8週持倉趨勢</div>'
             f'<div style="font-size:11px;color:var(--dim);margin-bottom:6px">（正值 = 大戶淨多頭口數，負值 = 淨空頭，數字越大代表方向越集中）</div>'
             f'{bars}'
            f'</div>')


def _werner_table(lending_text, bop_text, fiscal_text, mfg_text=None):
    tooltip_map = {
        "信用乖離率 ∆MF": "民間信用年增減去名目 GDP 年增，正值越大代表信用擴張快於實體活動。",
        "長期資本外流": "看金融帳近 4 季資金是否持續外流，外流擴大通常對日圓偏弱。",
        "民間信用/GDP": "觀察信用存量相對 GDP 是否升高，用來辨識槓桿是否持續累積。",
        "製成品進口": "製成品進口常反映內需與信用傳導，是 Werner 框架的輔助景氣指標。",
    }
    rows = []
    # 信用乖離率
    if lending_text:
        for ln in str(lending_text).split("\n"):
            if "∆MF" in ln or "信用乖離率" in ln:
                val = ln.strip()
                if "：" in val:
                    val = val.split("：", 1)[1].strip()
                val = val.replace("→ 解讀 ", "→ ")
                c = _color_line(ln)
                rows.append(("信用乖離率 ∆MF", "民間信用年增 vs 名目GDP年增", val, c))
                break
    # 長期資本外流
    if bop_text:
        lines = [line.strip() for line in str(bop_text).split("\n") if line.strip()]
        fa_line = lines[0] if lines else ""
        interp = next((line for line in lines if "解讀" in line), "")
        flow_match = re.search(r"金融帳近4季：\s*([0-9.+-]+B USD)", fa_line)
        flow_text = f"{flow_match.group(1)} 流出" if flow_match else fa_line.replace("金融帳近4季：", "").replace("（正＝流出）", "").strip()
        yoy_match = re.search(r"YoY\s*[+-]?[0-9.]+B(?:\s*USD)?", interp)
        interp = interp.replace("解讀：", "").strip()
        interp = re.sub(r"^長期資本外流擴大（", "", interp)
        interp = re.sub(r"^長期資本外流擴大\(", "", interp)
        interp = re.sub(r"^YoY\s*[+-]?[0-9.]+B(?:\s*USD)?[）)]?\s*[，、]?\s*", "", interp)
        interp = re.sub(r"\)$", "", interp)
        interp = re.sub(r"）", "", interp)
        interp = interp.replace("Werner：", "").replace("Werner:", "")
        if "→" in interp:
            interp = interp.split("→", 1)[0].strip()
        interp = interp.strip("，、 ")
        if yoy_match and interp:
            val = f"{flow_text}　{yoy_match.group(0).replace(' USD', '')}，{interp}"
        else:
            val = flow_text + ("　" + interp if interp else "")
        c = _color_line(interp)
        rows.append(("長期資本外流", "日本金融帳（季資料）", val, c))
    # 民間信用/GDP
    if fiscal_text:
        lines = [line.strip() for line in str(fiscal_text).split("\n") if line.strip()]
        val = lines[0] if lines else ""
        if "：" in val:
            val = val.split("：", 1)[1].strip()
        c = _color_line(" ".join(lines))
        rows.append(("民間信用/GDP", "民間信用 ÷ 名目GDP", val, c))
    # 製成品進口
    if mfg_text:
        lines = [line.strip() for line in str(mfg_text).split('\n') if line.strip()]
        val = lines[0] if lines else ''
        interp = next((line for line in lines if '解讀' in line), '')
        interp = interp.replace('解讀：', '')
        c = _color_line(interp)
        rows.append(('製成品進口', '日本進口季增率（OECD）', val + ('　' + interp if interp else ''), c))

    if not rows:
        return ""
    cards = "".join(
        f"<div class='werner-card'>"
        f"<div class='w-name'>{_esc(name)}"
        f' <span class="tooltip" tabindex="0">ⓘ<span class="tooltip-box">{_esc(tooltip_map.get(name, ""))}</span></span>'
        f' <span class="dim small">{_esc(src)}</span></div>'
        f"<div class='w-val {c or ''}'>{_esc(val)}</div>"
        f"</div>"
        for name, src, val, c in rows
    )
    return f"<div class='werner-list'>{cards}</div>"


def _extract_hero_strength(text):
    text = str(text or "")

    match = re.search(r"([1-5])\s*/\s*5", text)
    if match:
        return int(match.group(1))

    match = re.search(r"強度[^0-9]{0,6}([1-5])", text)
    if match:
        return int(match.group(1))

    match = re.search(r"([1-5])[^0-9]{0,6}強度", text)
    if match:
        return int(match.group(1))

    return 3


def _build_hero_signal_html(signal_summary, verdict, cot_warning=""):
    try:
        signal_text = str(signal_summary or "")
        verdict_text = str(verdict or "")
        combined = f"{signal_text}\n{verdict_text}"

        direction = "neutral"
        sig_match = re.search(r"訊號一致性[：:]\s*(.+)", signal_text)
        if sig_match:
            s = sig_match.group(1)
            if any(k in s for k in ["升值", "偏多", "看漲", "偏強"]):
                direction = "bullish"
            elif any(k in s for k in ["貶值", "偏空", "看跌", "偏弱"]):
                direction = "bearish"
        if direction == "neutral":
            direction_match = re.search(r"【方向】(.+)", verdict_text)
            if direction_match:
                d_text = direction_match.group(1).strip()
                if any(k in d_text for k in ["偏空", "貶值", "看跌", "偏弱", "看空"]):
                    direction = "bearish"
                elif any(k in d_text for k in ["偏多", "升值", "看漲", "偏強", "看多"]):
                    direction = "bullish"
        if direction == "neutral":
            if any(k in combined for k in ["偏空", "貶值", "看跌", "偏弱"]):
                direction = "bearish"
            elif any(k in combined for k in ["偏多", "升值", "看漲", "偏強"]):
                direction = "bullish"

        direction_label = {
            "bullish": "日圓偏多",
            "bearish": "日圓偏空",
            "neutral": "方向不明",
        }[direction]

        def _split_factors(raw_text):
            raw = str(raw_text or "").strip()
            if not raw:
                return []
            parts = re.split(r"[、，,／/]", raw)
            return [part.strip(" 　。.；;") for part in parts if part.strip(" 　。.；;")]

        factors_match = re.search(
            r"看漲訊號：(.+?)(?:\s*看跌訊號：)(.+)",
            signal_text.replace("\n", " "),
        )
        bullish_factors = []
        bearish_factors = []
        if factors_match:
            bullish_factors = _split_factors(factors_match.group(1))
            bearish_factors = _split_factors(factors_match.group(2))

        factor_universe = [
            "央行資產負債表",
            "COT大戶持倉",
            "技術面均線位置",
            "干預偵測",
            "Werner信用框架",
        ]
        ordered_factors = []
        seen = set()
        for name in bullish_factors + bearish_factors + factor_universe:
            if name and name not in seen:
                seen.add(name)
                ordered_factors.append(name)

        score_base = len(bullish_factors) + len(bearish_factors)
        strength = round((len(bullish_factors) / score_base) * 5) if score_base else 0
        strength = max(0, min(5, strength))
        dots = ("●" * strength) + ("○" * (5 - strength))

        factor_tags = []
        for factor in ordered_factors:
            if factor in bullish_factors:
                tone = "bullish"
                symbol = "▲"
            elif factor in bearish_factors:
                tone = "bearish"
                symbol = "▼"
            else:
                tone = "neutral"
                symbol = "—"
            factor_tags.append(
                f'<span class="factor-tag {tone}">{symbol} {_esc(factor)}</span>'
            )

        # 只從 cot_warning 抓一句，截短到 40 字
        warning_html = ""
        if cot_warning and any(k in cot_warning for k in ["擁擠", "過度", "96%", "注意"]):
            w = cot_warning.strip()[:40]
            warning_html = f'<div class="hero-warning">⚠ {_esc(w)}</div>'

        return (
            f'<section class="hero-signal {direction}">'
            f'<div class="hero-signal-top">'
            f'<div class="hero-direction">{direction_label}</div>'
            f'<div class="hero-strength"><span class="hero-strength-dots">{dots}</span> <span>{strength}/5</span></div>'
            f'</div>'
            f'<div class="hero-factors">{"".join(factor_tags)}</div>'
            f'{warning_html}'
            f'</section>'
        )
    except Exception:
        return ""


def _build_cot_summary_html(cot_text):
    text = str(cot_text or "")
    compact = text.replace("\n", " ")

    report_date = ""
    net_label = ""
    net_value = ""
    wow_value = ""
    percentile = ""

    date_match = re.search(r"報告日期\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", compact)
    if date_match:
        report_date = date_match.group(1)

    net_match = re.search(r"(淨多頭|淨空頭)\s*([0-9,]+)\s*口", compact)
    if not net_match:
        net_match = re.search(r"非商業(淨多頭|淨空頭)\s*([0-9,]+)\s*口", compact)
    if net_match:
        net_label = net_match.group(1)
        net_value = net_match.group(2)

    wow_match = re.search(r"較上週\s*([+-][0-9,]+)\s*口", compact)
    if wow_match:
        wow_value = wow_match.group(1)

    pct_match = re.search(r"有\s*(\d+)%\s*的時間", text)
    if pct_match:
        percentile = f'P{pct_match.group(1)}'

    parts = []
    if report_date:
        parts.append(f"報告日期 {report_date}")
    if net_label and net_value:
        wow_suffix = f"（{wow_value}）" if wow_value else ""
        parts.append(f"{net_label} {net_value} 口{wow_suffix}")
    if percentile:
        parts.append(percentile)

    if not parts:
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        return f'<div class="cot-summary">{_esc(first_line) if first_line else "—"}</div>'
    return f'<div class="cot-summary">{_esc(" ／ ".join(parts))}</div>'


def _build_news_section_html(news_text):
    if not str(news_text or "").strip():
        return ""
    return _section("📰", "本週重要事件", _lines_html(news_text, max_lines=12))


def _build_tff_label(tff_lev_net, tff_lev_pct):
    try:
        if tff_lev_net is None or tff_lev_pct is None:
            return ""
        net = int(tff_lev_net)
        pct = int(tff_lev_pct)
    except (TypeError, ValueError):
        return ""
    side = "機構淨多" if net >= 0 else "機構淨空"
    return f"{side} {net:+,}（P{pct}）"


def _build_info_bar_html(spread_2y_text, meeting_countdown, tff_lev_net=None, tff_lev_pct=None):
    spread_text = str(spread_2y_text or "").strip()
    meeting_text = ""
    tff_text = _build_tff_label(tff_lev_net, tff_lev_pct)
    if isinstance(meeting_countdown, dict):
        meeting_text = str(meeting_countdown.get("text", "")).strip()
    else:
        meeting_text = str(meeting_countdown or "").strip()
    if not spread_text and not meeting_text and not tff_text:
        return ""

    lines = []
    if spread_text:
        lines.append(f'<div class="info-bar-line"><span class="info-bar-icon">🏦</span><span>{_esc(spread_text)}</span></div>')
    if meeting_text:
        lines.append(f'<div class="info-bar-line"><span class="info-bar-icon">📅</span><span>{_esc(meeting_text)}</span></div>')
    if tff_text:
        lines.append(f'<div class="info-bar-line"><span class="info-bar-icon">🏛</span><span>{_esc(tff_text)}</span></div>')
    return f'<section class="info-bar"><div class="info-bar-body">{"".join(lines)}</div></section>'


CSS = """
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --white: #e6edf3; --dim: #8b949e;
  --green: #3fb950; --red: #f85149; --yellow: #e8b04b;
  --orange: #f0883e; --blue: #58a6ff;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--white); font-family: -apple-system, "PingFang TC", "Noto Sans TC", sans-serif; font-size: 15px; line-height: 1.6; padding: 0 0 40px; }
.container { max-width: 1180px; margin: 0 auto; padding: 0 16px; }
.page-grid { display: grid; grid-template-columns: minmax(0, 1.8fr) minmax(280px, 0.95fr); gap: 18px; align-items: start; }
.main-column, .side-column { min-width: 0; }
header { background: var(--surface); padding: 20px 16px 16px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }
header h1 { font-size: 22px; font-weight: 700; }
.price-row { display: flex; align-items: baseline; gap: 12px; margin-top: 8px; flex-wrap: wrap; }
.price-big { font-size: 42px; font-weight: 700; font-family: "Menlo", monospace; }
.price-change { font-size: 18px; }
.danger { color: var(--orange); font-size: 13px; margin-top: 6px; }
.hero-signal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left-width: 4px;
  border-radius: 8px;
  padding: 18px 20px;
  margin: 0 0 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hero-signal.bullish { border-left-color: var(--green); }
.hero-signal.bearish { border-left-color: var(--red); }
.hero-signal.neutral { border-left-color: var(--blue); }
.hero-signal-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.hero-direction { font-size: 26px; font-weight: 700; line-height: 1.1; letter-spacing: 0.02em; }
.hero-signal.bullish .hero-direction,
.hero-signal.bullish .hero-strength { color: var(--green); }
.hero-signal.bearish .hero-direction,
.hero-signal.bearish .hero-strength { color: var(--red); }
.hero-signal.neutral .hero-direction,
.hero-signal.neutral .hero-strength { color: var(--blue); }
.hero-strength { font-size: 14px; font-weight: 600; white-space: nowrap; }
.hero-strength-dots { font-size: 1rem; line-height: 1; }
.hero-strength span { margin-left: 6px; }
.hero-factors { display: flex; flex-wrap: wrap; gap: 6px; }
.factor-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  margin: 2px;
  border: 1px solid;
}
.factor-tag.bullish { background: #1a3a2a; border-color: #3fb950; color: #3fb950; }
.factor-tag.bearish { background: #3a1a1a; border-color: #f85149; color: #f85149; }
.factor-tag.neutral { background: #21262d; border-color: #484f58; color: #8b949e; }
.hero-warning {
  padding: 9px 12px;
  border-radius: 6px;
  border: 1px solid rgba(240, 136, 62, 0.45);
  background: rgba(240, 136, 62, 0.1);
  color: #f2cc9b;
  font-size: 13px;
  line-height: 1.5;
}
.info-bar {
  background: #121820;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin: 0 0 12px;
}
.info-bar-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.info-bar-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: var(--dim);
  line-height: 1.5;
}
.info-bar-icon {
  width: 16px;
  flex: 0 0 16px;
}
section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  margin: 0 0 12px;
}
.cot-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  margin: 0 0 12px;
}
.cot-summary {
  color: var(--white);
  font-size: 14px;
  margin-bottom: 12px;
}
.sec-header {
  font-size: 13px;
  color: var(--dim);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 10px;
}
.sec-body { font-size: 14px; word-break: break-word; overflow-wrap: break-word; }
.sec-body div { padding: 2px 0; }
.green { color: var(--green); }
.red { color: var(--red); }
.yellow { color: var(--yellow); }
.orange { color: var(--orange); }
.blue { color: var(--blue); }
.dim { color: var(--dim); }
.mono { font-family: "Menlo", monospace; }
.small { font-size: 12px; }
.sparkline { margin-top: 8px; font-size: 14px; }
.spark-chars { font-family: "Noto Sans Symbols 2", "Segoe UI Symbol", "Apple Color Emoji", "Noto Sans Symbols", "Menlo", monospace; letter-spacing: 2px; font-size: 16px; color: var(--blue); }
table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
th, td { padding: 7px 10px; border: 1px solid var(--border); text-align: left; vertical-align: top; }
th { background: var(--surface); color: var(--dim); font-weight: 500; }
.table-responsive, .tech-table-wrap { overflow-x: auto; width: 100%; }
.tech-table td:first-child { font-family: "Menlo", monospace; width: 90px; }
.current-row { background: #1c2d42; }
.werner-card { padding: 8px 0; border-bottom: 1px solid var(--border); }
.werner-card:last-child { border-bottom: none; }
.w-name { font-weight: 500; margin-bottom: 3px; }
.w-val { font-size: 14px; }
.tooltip {
  display: inline-flex;
  position: relative;
  margin-left: 6px;
  width: 17px;
  height: 17px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  border: 1px solid var(--border);
  color: var(--dim);
  font-size: 11px;
  cursor: help;
}
.tooltip-box {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 10px);
  transform: translateX(-50%);
  width: 220px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #0f1722;
  border: 1px solid var(--border);
  color: var(--white);
  font-size: 12px;
  line-height: 1.5;
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.18s ease;
  z-index: 20;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.28);
}
.tooltip:hover .tooltip-box,
.tooltip:focus .tooltip-box,
.tooltip:focus-within .tooltip-box {
  opacity: 1;
  visibility: visible;
}
.verdict-block { padding: 6px 0; border-bottom: 1px solid var(--border); }
.verdict-block:last-child { border-bottom: none; }
.verdict-label { color: var(--blue); font-weight: 600; margin-right: 4px; }
.signal-row { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 4px; }
.signal-chip { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 3px 10px; font-size: 12px; }
.details-panel {
  margin: 8px 0 20px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  overflow: hidden;
}
.details-panel summary {
  list-style: none;
  cursor: pointer;
  padding: 14px 16px;
  font-size: 15px;
  font-weight: 600;
  color: var(--white);
}
.details-panel summary::-webkit-details-marker { display: none; }
.details-content { padding: 0 16px 10px; }
.details-content section:last-child { margin-bottom: 0; }
.section-lead {
  font-size: 13px;
  color: var(--dim);
  margin-bottom: 10px;
  line-height: 1.5;
}
.section-split { height: 8px; }
.chart-box { height: 420px; min-height: 420px; margin-top: 12px; }
.chart-box.backtest { height: 400px; min-height: 400px; }
.cot-similar-wrap {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.cot-similar-title {
  font-size: 12px;
  color: var(--dim);
  margin-bottom: 10px;
  letter-spacing: 0.04em;
}
.cot-similar-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}
.cot-similar-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: #121820;
}
.cot-similar-label {
  font-size: 11px;
  color: var(--dim);
  margin-bottom: 4px;
}
.cot-similar-date {
  font-size: 15px;
  font-weight: 600;
  color: var(--white);
}
.cot-similar-pct {
  font-size: 12px;
  color: var(--orange);
  margin-top: 4px;
}
.cot-similar-empty {
  font-size: 13px;
  color: var(--dim);
}
footer { color: var(--dim); font-size: 11px; text-align: center; padding: 20px 16px 0; }
@media (max-width: 768px) {
  .container { max-width: 100%; padding: 0 12px; }
  .page-grid { grid-template-columns: 1fr; }
  .price-big { font-size: 34px; }
  .hero-signal-top { flex-direction: column; }
  .hero-direction { font-size: 1.6rem; }
  .hero-strength-dots { font-size: 1.2rem; }
  .info-bar-body,
  .info-bar-line { flex-direction: column; }
  .info-bar-line { gap: 4px; }
  .hero-factors { flex-wrap: wrap; }
  .chart-box,
  .chart-box.backtest { height: auto; min-height: 300px; }
  .cot-similar-list { grid-template-columns: 1fr; }
  .table-responsive,
  .tech-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  table { font-size: 12px; }
  th, td { padding: 5px 7px; }
}
"""


def _cot_chart_payload(cot_history):
    rows = _load_cot_history_rows(cot_history)
    if not rows:
        return None

    values = [row["net_short"] for row in rows]
    positives = sorted([v for v in values if v > 0])
    negatives = sorted([v for v in values if v < 0])

    if len(positives) >= 5:
        idx = int(len(positives) * 0.8)
        warn_high = positives[min(idx, len(positives) - 1)]
    else:
        warn_high = _percentile(values, 0.80)

    if len(negatives) >= 5:
        idx = int(len(negatives) * 0.2)
        warn_low = negatives[max(idx, 0)]
    else:
        warn_low = _percentile(values, 0.20)
    latest_value = values[-1]
    p95 = _percentile(values, 0.95)
    p05 = _percentile(values, 0.05)
    y_max = max(p95 * 1.2, latest_value * 1.1, warn_high * 1.1)
    y_min = min(p05 * 1.2, warn_low * 1.1)
    mean = sum(values) / len(values)
    if latest_value > warn_high:
        signal_text = '⚠ 多頭過度擁擠，多殺多風險升高'
    elif latest_value < warn_low:
        signal_text = '⚠ 空頭過度擁擠，軋空風險升高'
    else:
        signal_text = '空單水位正常，無極端訊號'
    ma52 = []
    for i in range(len(values)):
        window = values[max(0, i - 51):i + 1]
        ma52.append(round(sum(window) / len(window), 2))

    return {
        'dates': [row['date'] for row in rows],
        'values': values,
        'positive': [v if v > 0 else None for v in values],
        'negative': [v if v < 0 else None for v in values],
        'ma52': ma52,
        'mean': round(mean, 4),
        'warn_high': round(warn_high, 4),
        'warn_low': round(warn_low, 4),
        'y_min': round(y_min, 4),
        'y_max': round(y_max, 4),
        'signal_text': signal_text,
    }


def _build_cot_similar_history_html(cot_history):
    rows = _load_cot_history_rows(cot_history)
    if len(rows) < 12:
        return (
            '<div class="cot-similar-wrap">'
            '<div class="cot-similar-title">歷史相似情境</div>'
            '<div class="cot-similar-empty">歷史樣本不足，無法比對</div>'
            '</div>'
        )

    values = [row["net_short"] for row in rows]
    latest = rows[-1]
    latest_pct = _cot_rank_percentile(values, latest["net_short"])
    if latest_pct < 80:
        return ""

    p80_threshold = _percentile(values, 0.80)
    similar_rows = []
    for row in reversed(rows[:-1]):
        row_pct = _cot_rank_percentile(values, row["net_short"])
        if row["net_short"] >= p80_threshold and row_pct >= 80:
            similar_rows.append(
                f'<div class="cot-similar-card">'
                f'<div class="cot-similar-label">上次出現類似 COT 極端</div>'
                f'<div class="cot-similar-date">{_esc(row["date"] or "未知日期")}</div>'
                f'<div class="cot-similar-pct">P{row_pct}</div>'
                f'</div>'
            )
        if len(similar_rows) >= 3:
            break

    if not similar_rows:
        body_html = '<div class="cot-similar-empty">歷史樣本不足，無法比對</div>'
    else:
        body_html = "".join(similar_rows)

    return (
        '<div class="cot-similar-wrap">'
        '<div class="cot-similar-title">歷史相似情境</div>'
        f'<div class="cot-similar-list">{body_html}</div>'
        '</div>'
    )


def _backtest_chart_payload():
    try:
        import backtest
    except Exception:
        return None

    try:
        frame, _, _ = backtest.build_signal_frame()
        stats = backtest.summarize_backtest(frame)
    except Exception:
        return None

    required_cols = {"strategy_return_pct", "usdjpy_close"}
    if frame is None or getattr(frame, "empty", True) or not required_cols.issubset(frame.columns):
        return None

    try:
        frame = frame.copy().sort_index()
        strategy = (1 + frame["strategy_return_pct"].fillna(0) / 100).cumprod() * 100 - 100
        benchmark_weekly = ((frame["usdjpy_close"].shift(1) - frame["usdjpy_close"]) / frame["usdjpy_close"].shift(1)).fillna(0)
        benchmark = (1 + benchmark_weekly).cumprod() * 100 - 100
    except Exception:
        return None

    dates = [idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx) for idx in frame.index]

    def _optional_float(value):
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        'dates': dates,
        'strategy': [round(float(v), 4) for v in strategy],
        'benchmark': [round(float(v), 4) for v in benchmark],
        'win_rate': _optional_float(getattr(stats, 'win_rate_pct', None)),
        'sharpe': _optional_float(getattr(stats, 'sharpe_ratio', None)),
        'total_return': _optional_float(getattr(stats, 'total_return_pct', None)),
        'benchmark_return': _optional_float(getattr(stats, 'benchmark_return_pct', None)),
    }


def _plotly_assets_html(cot_payload=None, backtest_payload=None):
    if not cot_payload and not backtest_payload:
        return "", "", ""

    cot_div = ""
    backtest_div = ""
    script_lines = [
        "<script>",
        "(function(){",
        "const theme = {paper_bgcolor:'#0d1117', plot_bgcolor:'#0d1117', font:{color:'#eee'}};",
        "const config = {responsive: true};",
    ]

    if cot_payload:
        cot_div = '<div id="cot-chart" class="chart-box"></div>'
        cot_json = json.dumps(cot_payload, ensure_ascii=False)
        script_lines.extend([
            f'const cotData = {cot_json};',
            'const latest_val = cotData.values[cotData.values.length - 1];',
            'const latest_date = cotData.dates[cotData.dates.length - 1];',
            'const cot_traces = [',
            '{',
            '  x: cotData.dates, y: cotData.values.map(v => v >= 0 ? v : null),',
            '  type: "scatter", mode: "none", name: "淨空（看跌日圓）",',
            '  fill: "tozeroy", fillcolor: "rgba(248,81,73,0.25)",',
            '  showlegend: false',
            '},',
            '{',
            '  x: cotData.dates, y: cotData.values.map(v => v < 0 ? v : null),',
            '  type: "scatter", mode: "none", name: "淨多（看漲日圓）",',
            '  fill: "tozeroy", fillcolor: "rgba(63,185,80,0.25)",',
            '  showlegend: false',
            '},',
            '{',
            '  x: cotData.dates, y: cotData.values,',
            '  type: "scatter", mode: "lines", name: "淨部位",',
            '  line: {color: "#e8b04b", width: 2},',
            '  hovertemplate: "%{x}<br>淨部位: %{y:,.0f} 口<extra></extra>"',
            '},',
            '{',
            '  x: cotData.dates, y: cotData.ma52,',
            '  type: "scatter", mode: "lines", name: "52週均線",',
            '  line: {color: "#8b949e", dash: "dot", width: 1.5},',
            '  hovertemplate: "均線: %{y:,.0f}<extra></extra>"',
            '}',
            '];',
            'const active_warn = latest_val >= 0 ? cotData.warn_high : cotData.warn_low;',
            'const active_warn_label = latest_val >= 0 ? "多頭警戒" : "空頭警戒";',
            'const pct_to_warn = active_warn ? (((latest_val - active_warn) * Math.sign(active_warn)) / Math.abs(active_warn) * 100).toFixed(0) : null;',
            'const now_label = pct_to_warn !== null ? `現在 ${(latest_val/1000).toFixed(0)}k　距${active_warn_label}線 ${pct_to_warn > 0 ? "+" : ""}${pct_to_warn}%` : `現在 ${(latest_val/1000).toFixed(0)}k`;',
            'Plotly.newPlot("cot-chart", cot_traces, {',
            'title: {text: cotData.signal_text, x: 0.5, xanchor: "center", font: {size: 13, color: "#cdd9e5"}},',
            'annotations: [{',
            '  x: cotData.dates[Math.floor(cotData.dates.length * 0.08)], y: cotData.warn_high,',
            '  text: "⚠ 多頭警戒線", showarrow: false,',
            '  font: {color: "#f85149", size: 12, bold: true},',
            '  bgcolor: "rgba(40,10,10,0.85)", bordercolor: "#f85149", borderwidth: 1, borderpad: 4',
            '}, {',
            '  x: cotData.dates[Math.floor(cotData.dates.length * 0.08)], y: cotData.warn_low,',
            '  text: "⚠ 空頭警戒線", showarrow: false,',
            '  font: {color: "#3fb950", size: 12, bold: true},',
            '  bgcolor: "rgba(10,30,10,0.85)", bordercolor: "#3fb950", borderwidth: 1, borderpad: 4',
            '}, {',
            '  x: latest_date, y: latest_val,',
            '  text: now_label,',
            '  showarrow: true, arrowhead: 3, arrowsize: 1.2, arrowcolor: "#e8b04b", ax: -60, ay: 50,',
            '  xanchor: "right",',
            '  font: {color: "#e8b04b", size: 13},',
            '  bgcolor: "rgba(26,26,46,0.92)", bordercolor: "#e8b04b", borderwidth: 2, borderpad: 6',
            '}],',
            'shapes: [{',
            '  type: "line", x0: cotData.dates[0], x1: cotData.dates[cotData.dates.length - 1],',
            '  y0: 0, y1: 0,',
            '  line: {color: "#58a6ff", width: 1.5, dash: "solid"}',
            '}, {',
            '  type: "line", x0: cotData.dates[0], x1: cotData.dates[cotData.dates.length - 1],',
            '  y0: cotData.warn_high, y1: cotData.warn_high,',
            '  line: {color: "#f85149", width: 2, dash: "dot"}',
            '}, {',
            '  type: "line", x0: cotData.dates[0], x1: cotData.dates[cotData.dates.length - 1],',
            '  y0: cotData.warn_low, y1: cotData.warn_low,',
            '  line: {color: "#3fb950", width: 2, dash: "dot"}',
            '}],',
            'margin: {l: 55, r: 15, t: 50, b: 40},',
            'xaxis: {gridcolor: "#2d333b", showgrid: true, tickfont: {size: 11}, tickformat: "%b %Y"},',
            'yaxis: {gridcolor: "#2d333b", tickformat: ",.0f", tickfont: {size: 11}, range: [cotData.y_min, cotData.y_max]},',
            'hovermode: "closest",',
            'legend: {orientation: "h", y: -0.18, x: 0.5, xanchor: "center", font: {size: 11}},',
            '...theme',
            '}, config);',
        ])

    if backtest_payload:
        backtest_div = '<div id="backtest-chart" class="chart-box backtest"></div>'
        backtest_json = json.dumps(backtest_payload, ensure_ascii=False)
        script_lines.extend([
            f'const backtestData = {backtest_json};',
            'const s_last = backtestData.strategy[backtestData.strategy.length - 1];',
            'const b_last = backtestData.benchmark[backtestData.benchmark.length - 1];',
            'const d_last = backtestData.dates[backtestData.dates.length - 1];',
            'const outperf = (s_last - b_last).toFixed(1);',
            'const annotations = [',
            '{x: d_last, y: s_last, text: `+${s_last.toFixed(1)}%`,',
            ' showarrow: true, arrowhead: 2, arrowcolor: "#58a6ff", ax: 30, ay: -20,',
            ' font: {color: "#58a6ff", size: 13, bold: true}, bgcolor: "rgba(26,26,46,0.85)", bordercolor: "#58a6ff", borderwidth: 1},',
            '{x: d_last, y: b_last, text: `${b_last.toFixed(1)}%`,',
            ' showarrow: true, arrowhead: 2, arrowcolor: "#f85149", ax: 30, ay: 20,',
            ' font: {color: "#f85149", size: 13}, bgcolor: "rgba(26,26,46,0.85)", bordercolor: "#f85149", borderwidth: 1}',
            '];',
            'if (backtestData.total_return !== null) {',
            '  const b_ret = backtestData.benchmark_return !== null ? backtestData.benchmark_return.toFixed(1) : "—";',
            '  const wr = backtestData.win_rate !== null ? backtestData.win_rate.toFixed(1) : "—";',
            '  const sr = backtestData.sharpe !== null ? backtestData.sharpe.toFixed(2) : "—";',
            '  annotations.push({',
            '    x: 1, y: 1, xref: "paper", yref: "paper",',
            '    xanchor: "right", yanchor: "top",',
            '    text: `策略 +${backtestData.total_return.toFixed(1)}%<br>基準 ${b_ret}%<br>勝率 ${wr}%<br>Sharpe ${sr}`,',
            '    showarrow: false,',
            '    font: {size: 12, color: "#cdd9e5"},',
            '    bgcolor: "rgba(26,26,46,0.9)",',
            '    bordercolor: "#58a6ff",',
            '    borderwidth: 1,',
            '    borderpad: 8,',
            '    align: "left"',
            '  });',
            '}',
            'Plotly.newPlot("backtest-chart", [',
            '// fill between lines',
            '{x: [...backtestData.dates, ...backtestData.dates.slice().reverse()],',
            ' y: [...backtestData.strategy, ...backtestData.benchmark.slice().reverse()],',
            ' fill: "toself", fillcolor: "rgba(88,166,255,0.08)",',
            ' line: {color: "transparent"}, showlegend: false, hoverinfo: "skip"},',
            '{x: backtestData.dates, y: backtestData.strategy, type: "scatter", mode: "lines",',
            ' name: `策略 (${s_last.toFixed(1)}%)`, line: {color: "#58a6ff", width: 2.5},',
            ' hovertemplate: "%{x}<br>策略: %{y:.1f}%<extra></extra>"},',
            '{x: backtestData.dates, y: backtestData.benchmark, type: "scatter", mode: "lines",',
            ' name: `Buy & Hold JPY (${b_last.toFixed(1)}%)`, line: {color: "#f85149", width: 2},',
            ' hovertemplate: "%{x}<br>B&H: %{y:.1f}%<extra></extra>"}',
            '], {',
            'title: {text: `Werner 訊號策略 vs 持有日圓　超越基準 +${outperf}%`, font: {size: 13, color: "#cdd9e5"}},',
            'annotations,',
            'margin: {l: 56, r: 80, t: 55, b: 45},',
            'xaxis: {gridcolor: "#2d333b"},',
            'yaxis: {gridcolor: "#2d333b",',
            ' zeroline: true, zerolinecolor: "#58a6ff", zerolinewidth: 1.5, ticksuffix: "%"},',
            'legend: {orientation: "h", y: -0.15, x: 0},',
            'hovermode: "x unified",',
            '...theme',
            '}, config);',
        ])

    script_lines.extend(["})();", "</script>"])
    return cot_div, backtest_div, "\n".join(script_lines)


def build_html(data: dict) -> str:
    d = data
    price = d.get("price", 0)
    if not price:
        return '<p>資料載入中...</p>'
    change = d.get("change", 0)
    pct = abs(d.get("pct", 0))
    chg_cls = "green" if change < 0 else "red"
    chg_label = "升值" if change < 0 else "貶值"

    # price header
    header = f"""
<header>
  <div class="container">
    <h1>💴 日圓週報　{_esc(d.get('date',''))}</h1>
    <div class="price-row">
      <span class="price-big">USD/JPY {price:.2f}</span>
      <span class="price-change {chg_cls}">日圓{chg_label} {abs(change):.2f}（{pct:.2f}%）</span>
    </div>
    {('<div class="danger">⚠ ' + _esc(d.get('danger','')) + '</div>') if d.get('danger') else ''}
  </div>
</header>"""

    cot_text_raw = str(d.get("cot", ""))
    cot_pct_m = re.search(r'有\s*(\d+)%\s*的時間', cot_text_raw)
    cot_pct = int(cot_pct_m.group(1)) if cot_pct_m else 0
    if cot_pct >= 90:
        cot_warning = f"COT P{cot_pct}：多頭極度擁擠，歷史上常見反轉前兆"
    elif cot_pct <= 10:
        cot_warning = f"COT P{cot_pct}：空頭極度擁擠，注意軋空風險"
    else:
        cot_warning = ""
    hero_html = _build_hero_signal_html(d.get("signal_summary", ""), d.get("verdict", ""), cot_warning)
    main_sections = []
    side_sections = []

    cot_payload = _cot_chart_payload(d.get("cot_history", []))
    backtest_payload = _backtest_chart_payload()
    cot_chart_div, backtest_chart_div, plotly_script = _plotly_assets_html(cot_payload, backtest_payload)
    cot_similar_html = _build_cot_similar_history_html(d.get("cot_history", []))

    cot_html = _build_cot_summary_html(d.get("cot", ""))
    cot_html += cot_chart_div
    cot_html += cot_similar_html
    cot_section_html = f'<section class="cot-section"><div class="sec-header">🏦 大戶持倉 COT</div><div class="sec-body">{cot_html}</div></section>'

    news_html = _build_news_section_html(d.get("news", ""))
    info_bar_html = _build_info_bar_html(
        d.get("spread_2y_text", ""),
        d.get("meeting_countdown", ""),
        d.get("tff_lev_net"),
        d.get("tff_lev_pct"),
    )

    main_sections.append(_section("🎯", "本週判斷", _verdict_html(d.get("verdict", ""), skip_labels={"操作建議"})))

    # 技術面
    tech_html = _tech_table(d.get("tech", {}), price)
    if tech_html:
        side_sections.append(_section("📐", "技術面區間", tech_html))

    # 央行 + 干預
    cb_html = _lines_html(d.get("cb", ""), max_lines=99)
    if d.get("mof"):
        cb_html += '<div class="section-split"></div>' + _lines_html(d.get("mof", ""), max_lines=99)
    main_sections.append(_section("🏛", "央行訊號 & 干預偵測", cb_html))

    # Werner 信用框架（新）
    werner_html = _werner_table(
        d.get("lending"),
        d.get("bop"),
        d.get("fiscal"),
        mfg_text=d.get("mfg_import"),
    )
    if werner_html:
        werner_html = (
            '<div class="section-lead">'
            '日本央行學者 Werner 理論：推動匯率的是信用數量，而非利率。以下三個指標追蹤信用擴張速度與資金流向。'
            '</div>' + werner_html
        )
        main_sections.append(_section("📡", "Werner 信用框架", werner_html))

    # 訊號一致性
    main_sections.append(_section("📊", "訊號一致性", _lines_html(d.get("signal_summary", ""), max_lines=99)))

    # 行事曆
    side_sections.append(_section("📅", "下週行事曆", _lines_html(d.get("calendar", ""), max_lines=10)))

    compliance_html = _disclaimer_card_html()
    footer_html = (
        "<footer>"
        "<div>本報告僅供個人參考，不構成投資建議</div>"
        "<div>數據來源：Federal Reserve Bank of St. Louis (FRED), Bank of Japan (BOJ), "
        "Ministry of Finance Japan (MOF), CFTC</div>"
        "</footer>"
    )
    details_html = (
        '<details class="details-panel">'
        '<summary>▶ 完整分析</summary>'
        f'<div class="details-content">{"".join(main_sections)}</div>'
        '</details>'
    )
    backtest_section_html = _section("📈", "策略回測", backtest_chart_div) if backtest_payload else ""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel='preconnect' href='https://fonts.googleapis.com'>
<link href='https://fonts.googleapis.com/css2?family=Noto+Sans+Symbols+2&display=swap' rel='stylesheet'>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<title>日圓週報 {_esc(d.get('date',''))}</title>
<style>{CSS}</style>
</head>
<body>
{header}
<div class="container">
{hero_html}
<div class="page-grid">
<div class="main-column">
{news_html}
{info_bar_html}
{cot_section_html}
{backtest_section_html}
</div>
<aside class="side-column">
{''.join(side_sections)}
</aside>
</div>
{details_html}
{compliance_html}
</div>
{footer_html}
{plotly_script}
</body>
</html>"""


def push_to_github_pages(html: str, date_str: str) -> str:
    """寫出 HTML，GitHub Pages 推送交由外部 workflow 處理。"""
    use_dist = os.environ.get("JPY_USE_DIST") == "1"
    if use_dist:
        target_dir = DIST_DIR
    elif REPO_DIR.exists():
        target_dir = REPO_DIR
    else:
        target_dir = DIST_DIR

    target_dir.mkdir(parents=True, exist_ok=True)
    html_path = target_dir / "index.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("HTML 已輸出到 %s（date=%s）", html_path, date_str)
    return "https://aqua5230.github.io/jpy-weekly/"


if __name__ == "__main__":
    # 測試用假資料
    data = {
        "date": "2026年03月24日",
        "price": 158.66,
        "change": -0.23,
        "pct": 0.14,
        "danger": "接近 160 干預紅線，留意財務省動向",
        "cot": "報告日期 2026-03-17　非商業淨多頭 30,099 口，較上週 +27,809 口\n多頭 61,703　空頭 31,604\n52週定位：近一年當中有 96% 的時間比現在更空\n大家幾乎都在看漲，位置擁擠，反而要小心大跌\n近8週趨勢：▁▁▁▁▁▁▁█  本週 多頭 30,099 口",
        "cot_history": [-45200, -52300, -60100, -55800, -49400, -58700, 2290, 30099],
        "verdict": "【操作建議】可考慮做多日圓\n聯準會擴表更快，但注意 COT 擁擠風險\n⚠️ 僅供參考，非投資建議\n【方向】日圓偏強\n【數據指向】聯準會擴表快於日銀，長期利多日圓\n【本週關鍵】美國 PMI 數據若強勁將挑戰 160",
        "tech": {"ma20": 158.1, "ma50": 157.55, "high20": 160.25, "low20": 155.86},
        "cb": "方向：偏向日圓升值\n解讀：Fed 擴表速度快於日銀，美元供給增加",
        "mof": "近三個月無財務省外匯干預（上次：2024-07-11）",
        "lending": "民間信用年增：+4.3%（BIS，2025-Q3）\n名目 GDP 年增：+3.9%\n信用乖離率 ∆MF：+0.4% → 信用增速與實體相符",
        "bop": "金融帳近4季：172B USD（正＝流出）\n經常帳：5.3% of GDP\n解讀：長期資本外流擴大 → 日圓貶值壓力↑",
        "fiscal": "民間信用/GDP：113.7%（YoY +0.5 ppt）\n解讀：信用/GDP 比率穩定",
        "signal_summary": "本週訊號一致性：偏向日圓升值（2/3 個訊號）\n看漲訊號：央行資產負債表、COT大戶持倉　看跌訊號：技術面均線位置",
        "calendar": "03/24 🇺🇸 Flash Manufacturing PMI　→ 若高於預測，利空日圓\n03/24 🇺🇸 Flash Services PMI　→ 若高於預測，利空日圓\n03/26 🇺🇸 Unemployment Claims　→ 若低於預測，利空日圓",
        "spread_2y_text": "美國2Y 4.12%　日本2Y 0.78%　利差 3.34%（短端）",
        "meeting_countdown": {
            "fed_days": 43,
            "boj_days": 37,
            "fed_date": "2026-05-06/07",
            "boj_date": "2026-04-30/05-01",
            "text": "Fed 下次會議 2026-05-06/07（43天後）　BOJ 2026-04-30/05-01（37天後）",
        },
    }
    html = build_html(data)
    out = BASE_DIR / "report_preview.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"預覽：{out}")

    try:
        url = push_to_github_pages(html, data["date"])
        print(f"GitHub Pages：{url}")
    except Exception as exc:
        print(f"GitHub Pages 發佈略過：{exc}")
