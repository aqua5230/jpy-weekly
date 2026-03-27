#!/usr/bin/env python3
"""日圓週報圖片卡片模組與 Telegram 發送工具"""
from PIL import Image, ImageDraw, ImageFont
import requests
import os
from config import TG_TOKEN, TG_PUBLIC

FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
MONO_PATH = "/System/Library/Fonts/Menlo.ttc"

# ── 顏色 ──────────────────────────────────────
BG       = "#0d1117"
SURFACE  = "#161b22"
BORDER   = "#30363d"
WHITE    = "#e6edf3"
DIM      = "#8b949e"
GREEN    = "#3fb950"
YELLOW   = "#d29922"
ORANGE   = "#f0883e"
RED      = "#f85149"
BLUE     = "#58a6ff"
ACCENT   = "#1f6feb"

W, PAD = 900, 44

def font(size, mono=False):
    return ImageFont.truetype(MONO_PATH if mono else FONT_PATH, size)

def text_w(draw, text, f):
    return draw.textlength(text, font=f)

def draw_card(data):
    def render(d, height, draw_enabled):
        def line(y, x1=PAD, x2=W-PAD, color=BORDER):
            if draw_enabled:
                d.line([(x1, y), (x2, y)], fill=color, width=1)

        def section_header(y, icon, title):
            if draw_enabled:
                d.text((PAD, y), icon, font=font(20), fill=DIM)
                d.text((PAD+34, y), title, font=font(20), fill=DIM)
            return y + 34

        if draw_enabled:
            d.rectangle([(0, 0), (W, 86)], fill=SURFACE)
            d.text((PAD, 20), "💴 日圓週報", font=font(28), fill=WHITE)
            date_w = text_w(d, data['date'], font(20))
            d.text((W-PAD-date_w, 26), data['date'], font=font(20), fill=DIM)
        line(86)

        y = 106
        if draw_enabled:
            d.text((PAD, y), "USD/JPY", font=font(18), fill=DIM)
            price_str = f"{data['price']:.2f}"
            d.text((PAD, y+24), price_str, font=font(52), fill=WHITE)
            arrow = "↓" if data['change'] < 0 else "↑"
            chg_color = GREEN if data['change'] < 0 else RED
            chg_str = f"{arrow} 日圓{'升值' if data['change'] < 0 else '貶值'} {abs(data['change']):.2f}（{data['pct']:.2f}%）"
            d.text((PAD+230, y+38), chg_str, font=font(20), fill=chg_color)
            if data['danger']:
                d.text((PAD, y+82), f"⚠ {data['danger']}", font=font(16), fill=ORANGE)
        y = 218
        line(y)

        y += 18
        y = section_header(y, "🏦", "大戶持倉 COT")
        for ln in data['cot'].split('\n')[:3]:
            if ln.strip():
                if draw_enabled:
                    d.text((PAD, y), ln.strip(), font=font(17), fill=WHITE)
                y += 28

        # COT 近8週長條圖
        cot_history_raw = data.get('cot_history', [])
        if cot_history_raw and isinstance(cot_history_raw[0], dict):
            cot_history = [item.get('net_short', 0) for item in cot_history_raw[-8:]]
        else:
            cot_history = cot_history_raw[-8:] if len(cot_history_raw) > 8 else cot_history_raw
        if cot_history:
            max_abs = max(abs(v) for v in cot_history) or 1
            bar_area_w = W - PAD * 2 - 80  # 長條圖總寬度
            bar_h = 14
            bar_gap = 4
            zero_x = PAD + 40  # 零軸 x 座標（留 40px 給標籤）

            y += 8
            if draw_enabled:
                # 畫零軸
                d.line([(zero_x, y), (zero_x, y + len(cot_history) * (bar_h + bar_gap))], fill=BORDER, width=1)

            for i, val in enumerate(cot_history):
                bar_y = y + i * (bar_h + bar_gap)
                is_last = (i == len(cot_history) - 1)
                bar_len = int(abs(val) / max_abs * (bar_area_w // 2))
                bar_len = max(bar_len, 2)

                if draw_enabled:
                    if val >= 0:
                        color = GREEN if not is_last else "#58d68d"
                        d.rectangle([(zero_x, bar_y), (zero_x + bar_len, bar_y + bar_h)], fill=color)
                    else:
                        color = RED if not is_last else "#f1948a"
                        d.rectangle([(zero_x - bar_len, bar_y), (zero_x, bar_y + bar_h)], fill=color)

                    # 週次標籤（左側）
                    week_label = "本週" if is_last else f"-{len(cot_history)-1-i}W"
                    d.text((PAD, bar_y), week_label, font=font(11, mono=True), fill=WHITE if is_last else DIM)

                    # 數值標籤（右側）
                    val_label = f"{val/1000:+.0f}k"
                    if val >= 0:
                        d.text((zero_x + bar_len + 4, bar_y), val_label, font=font(11, mono=True), fill=GREEN if not is_last else WHITE)
                    else:
                        label_x = max(PAD + 40, zero_x - bar_len - 32)
                        d.text((label_x, bar_y), val_label, font=font(11, mono=True), fill=RED if not is_last else WHITE)

            y += len(cot_history) * (bar_h + bar_gap) + 8

        line(y := y+10)

        y += 18
        y = section_header(y, "🎯", "本週判斷")
        for ln in data['verdict'].split('\n'):
            if ln.strip():
                if draw_enabled:
                    color = WHITE
                    if '偏強' in ln:
                        color = GREEN
                    elif '偏弱' in ln:
                        color = RED
                    elif '不明' in ln:
                        color = YELLOW
                    d.text((PAD, y), ln.strip(), font=font(17), fill=color)
                y += 28
        line(y := y+10)

        y += 18
        y = section_header(y, "📐", "技術面區間")
        tech = data['tech']
        current_price = data['price']
        raw_levels = []
        tech_items = [
            ("ma20", "MA20 短期均線"),
            ("ma50", "MA50 中期均線"),
            ("high20", "20日高點"),
            ("low20", "20日低點"),
        ]
        for key, label in tech_items:
            price = tech.get(key)
            if price is None:
                continue
            if price < current_price:
                color = GREEN
            elif price > current_price:
                color = RED
            else:
                color = YELLOW
            raw_levels.append((price, label, color))

        lower_levels = sorted([item for item in raw_levels if item[0] < current_price], key=lambda x: x[0])
        upper_levels = sorted([item for item in raw_levels if item[0] > current_price], key=lambda x: x[0])
        equal_levels = [item for item in raw_levels if item[0] == current_price]
        levels = lower_levels + equal_levels + [(current_price, "現價", BLUE)] + upper_levels
        bar_x = PAD + 250
        if draw_enabled:
            d.line([(bar_x-12, y), (bar_x-12, y+len(levels)*32)], fill=BORDER, width=1)
        for price, label, color in levels:
            is_current = price == data['price']
            if draw_enabled:
                if is_current:
                    d.rectangle([(PAD-4, y-3), (W-PAD+4, y+26)], fill="#1c2d42")
                d.text((PAD, y), f"{price:.2f}", font=font(18, mono=True), fill=color)
                d.text((bar_x, y), label, font=font(17), fill=WHITE if is_current else DIM)
            y += 32
        line(y := y+10)

        y += 18
        y = section_header(y, "🏛", "央行訊號 & 干預偵測")
        status_tags = data.get('status_tags', {}) or {}
        tag_specs = [
            (status_tags.get('fed', ''), BLUE),
            (status_tags.get('spread', ''), YELLOW),
        ]
        tag_x = PAD
        tag_y = y
        tag_h = 30
        for tag_text, outline in tag_specs:
            if not tag_text:
                continue
            tag_w = int(text_w(d, tag_text, font(15)) + 28)
            if draw_enabled:
                d.rounded_rectangle([(tag_x, tag_y), (tag_x + tag_w, tag_y + tag_h)], radius=14, outline=outline, width=2, fill=SURFACE)
                d.text((tag_x + 14, tag_y + 6), tag_text, font=font(15), fill=WHITE)
            tag_x += tag_w + 12
        y += 42

        progress = max(0.0, min(float(status_tags.get('intervention_progress', 0.0) or 0.0), 1.0))
        distance_label = status_tags.get('intervention_distance_label', '')
        red_line = float(status_tags.get('intervention_price', 160.0) or 160.0)
        progress_w = W - PAD * 2
        progress_h = 14
        if draw_enabled:
            d.text((PAD, y), f"現價逼近干預線 {red_line:.0f}", font=font(15), fill=DIM)
            d.text((W - PAD - text_w(d, distance_label, font(15)), y), distance_label, font=font(15), fill=ORANGE)
            bar_y = y + 28
            d.rounded_rectangle([(PAD, bar_y), (PAD + progress_w, bar_y + progress_h)], radius=7, fill="#21262d", outline=BORDER)
            filled_w = max(12, int(progress_w * progress)) if progress > 0 else 0
            if filled_w:
                fill_color = RED if progress >= 0.97 else ORANGE if progress >= 0.94 else BLUE
                d.rounded_rectangle([(PAD, bar_y), (PAD + filled_w, bar_y + progress_h)], radius=7, fill=fill_color)
            marker_x = PAD + progress_w - 2
            d.rectangle([(marker_x, bar_y - 6), (marker_x + 4, bar_y + progress_h + 6)], fill=RED)
            price_x = min(PAD + max(0, int(progress_w * progress) - 18), PAD + progress_w - 36)
            d.text((price_x, bar_y + 20), f"{data['price']:.2f}", font=font(13, mono=True), fill=WHITE)
            d.text((PAD + progress_w - 34, bar_y + 20), "160", font=font(13, mono=True), fill=RED)
        y += 60

        cb_lines = []
        if data.get('mof'):
            first_mof = next((ln.strip() for ln in str(data.get('mof', '')).split('\n') if ln.strip()), "")
            if first_mof:
                cb_lines.append(first_mof)
        if data.get('cb'):
            explain = next((ln.strip() for ln in data['cb'].split('\n') if '解讀：' in ln), "")
            if explain:
                cb_lines.append(explain)
        for ln in cb_lines[:2]:
            if draw_enabled:
                color = GREEN if '升值' in ln else RED if '貶值' in ln or '干預' in ln else DIM
                d.text((PAD, y), ln[:70], font=font(15), fill=color)
            y += 24
        line(y := y + 8)

        y += 18
        y = section_header(y, "📊", "訊號一致性")
        signal_text = data.get('signal_summary', '')
        if signal_text:
            for ln in signal_text.split('\n')[:2]:
                if ln.strip():
                    if draw_enabled:
                        color = GREEN if '升值' in ln else RED if '貶值' in ln else YELLOW
                        d.text((PAD, y), ln.strip()[:65], font=font(15), fill=color)
                    y += 24
        line(y := y + 8)

        y += 18
        y = section_header(y, "📡", "Werner 信用框架")
        werner_lines = []
        # 從 lending_text 抓信用乖離率那一行
        lending_text = data.get('lending', '')
        if lending_text:
            for ln in lending_text.split('\n'):
                if '∆MF' in ln or '信用乖離率' in ln:
                    werner_lines.append(ln.strip())
        # 從 bop_text
        bop_text = data.get('bop', '')
        if bop_text:
            for ln in bop_text.split('\n')[:2]:
                if ln.strip():
                    werner_lines.append(ln.strip())
        for ln in werner_lines[:4]:
            if draw_enabled:
                color = RED if '貶值' in ln or '外流' in ln else GREEN if '升值' in ln or '收縮' in ln else DIM
                d.text((PAD, y), ln[:62], font=font(15), fill=color)
            y += 22
        line(y := y + 6)

        y += 18
        y = section_header(y, "📅", "下週行事曆")
        for ln in data['calendar'].split('\n')[:3]:
            if ln.strip():
                if draw_enabled:
                    d.text((PAD, y), ln.strip(), font=font(16), fill=DIM)
                y += 26

        if draw_enabled:
            line(height-36)
            d.text((PAD, height-24), "本報告僅供個人參考，不構成投資建議", font=font(13), fill=BORDER)

        return y

    dummy = Image.new("RGB", (W, 1), BG)
    content_bottom = render(ImageDraw.Draw(dummy), 1, False)
    H = max(800, content_bottom + 60)

    img = Image.new("RGB", (W, H), BG)
    render(ImageDraw.Draw(img), H, True)
    return img


def send_photo(img_path, caption=""):
    with open(img_path, 'rb') as f:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
            data={"chat_id": TG_PUBLIC, "caption": caption},
            files={"photo": f},
            timeout=30
        )
    return r.json()


if __name__ == '__main__':
    # 用上次週報的數據測試
    data = {
        'date': '2026年03月24日',
        'price': 158.66,
        'change': -0.23,
        'pct': 0.14,
        'danger': '接近 160 干預紅線，留意財務省動向',
        'cot': '最新非商業淨空頭為 67,780 口，較上週 +26,380 口\n投機性放空情緒攀升至近 20 個月新高\n市場對日圓極度看淡',
        'verdict': '【方向】日圓偏弱\n【數據指向】COT 淨空頭大幅增加，看淡情緒創新高\n【本週關鍵】美國 Flash PMI 若強勁將挑戰 160',
        'calendar': '03/25 | BoJ 政策會議意見摘要 | 利多日圓\n03/27 | 東京 3 月 CPI | 利多日圓\n03/31 | 日本財政年度結算 | 利多日圓',
        'tech': {
            'ma20': 158.1,
            'ma50': 157.55,
            'high20': 160.25,
            'low20': 156.8,
        },
        'cot_history': [-45200, -52300, -60100, -55800, -49400, -58700, -63200, -67780],
        'lending': '民間信用年增：+4.3%（BIS，2025-Q3）\n名目 GDP 年增：+3.9%\n信用乖離率 ∆MF：+0.4% → 信用增速與實體相符',
        'bop': '金融帳近4季：172B USD（正＝流出）\n經常帳：5.3% of GDP\n解讀：長期資本外流擴大 → 日圓貶值壓力↑',
    }

    img = draw_card(data)
    out = os.path.expanduser("~/Desktop/投資/test_card.png")
    img.save(out, quality=95)
    print(f"圖片已存：{out}")

    result = send_photo(out)
    if result.get('ok'):
        print("✅ 圖片已發送到 TG")
    else:
        print(f"❌ 發送失敗：{result}")
