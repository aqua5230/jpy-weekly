#!/usr/bin/env python3
"""方案合併測試：圖片卡片 + Telegraph 完整報告連結"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from test_image import draw_card
from test_telegraph import create_telegraph_account, publish_to_telegraph, build_nodes
import requests
from config import TG_TOKEN, TG_PUBLIC

BASE_DIR = Path(os.environ.get("JPY_BASE_DIR", Path(__file__).resolve().parent.parent))

def send_card_with_link(img_path, tg_url, data):
    arrow = "📉" if data['change'] < 0 else "📈"
    caption = (
        f"💴 <b>USD/JPY {data['price']:.2f}</b>　{arrow} {abs(data['change']):.2f}（{data['pct']:.2f}%）\n"
        f"📖 <a href='{tg_url}'>完整報告</a>"
    )
    with open(img_path, 'rb') as f:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
            data={"chat_id": TG_PUBLIC, "caption": caption, "parse_mode": "HTML"},
            files={"photo": f},
            timeout=30
        )
    return r.json()


if __name__ == '__main__':
    data = {
        'date': '2026年03月24日',
        'price': 158.66,
        'change': -0.23,
        'pct': 0.14,
        'danger': '接近 160 干預紅線，留意財務省動向',
        'cot': '最新非商業淨空頭為 67,780 口，較上週 +26,380 口\n投機性放空情緒攀升至近 20 個月新高\n市場對日圓極度看淡',
        'news': '1. 美國 Flash PMI 數據強勁，加劇日圓貶值壓力\n2. 日本東京 CPI 通膨數據，影響日銀升息預期\n3. 日本財政年度結算季節性資金回流',
        'verdict': '【方向】日圓偏弱\n【數據指向】COT 淨空頭大幅增加，看淡情緒創新高\n【本週關鍵】美國 Flash PMI 若強勁將挑戰 160',
        'calendar': '03/25 | BoJ 政策會議意見摘要 | 利多日圓\n03/27 | 東京 3 月 CPI | 利多日圓\n03/31 | 日本財政年度結算 | 利多日圓',
        'tech': {
            'ma20': 158.1,
            'ma50': 157.55,
            'high20': 160.25,
            'low20': 156.8,
        },
    }

    print("🖼  生成圖片卡片...")
    img = draw_card(data)
    out = BASE_DIR / "test_card.png"
    img.save(out, quality=95)

    print("📝 發佈 Telegraph...")
    token = create_telegraph_account()
    nodes = build_nodes(data)
    tg_url = publish_to_telegraph(token, f"日圓週報　{data['date']}", nodes)
    print(f"   {tg_url}")

    print("📨 發送到 TG...")
    result = send_card_with_link(str(out), tg_url, data)
    if result.get('ok'):
        print("✅ 完成")
    else:
        print(f"❌ 失敗：{result}")
