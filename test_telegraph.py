#!/usr/bin/env python3
"""日圓週報 Telegraph 內容節點與 Telegram 連結發送工具"""
import requests
import json
from config import TG_TOKEN, TG_PUBLIC


def create_telegraph_account():
    r = requests.post("https://api.telegra.ph/createAccount", json={
        "short_name": "JPY週報",
        "author_name": "日圓投資監控"
    }, timeout=15)
    return r.json()['result']['access_token']


def publish_to_telegraph(token, title, content_nodes):
    r = requests.post("https://api.telegra.ph/createPage", json={
        "access_token": token,
        "title": title,
        "content": content_nodes,
        "return_content": False
    }, timeout=15)
    result = r.json()
    if not result.get('ok'):
        raise RuntimeError(result)
    return result['result']['url']


def build_nodes(data):
    """把週報資料轉成 Telegraph node 格式"""
    def p(text):       return {"tag": "p", "children": [text]}
    def h3(text):      return {"tag": "h3", "children": [text]}
    def h4(text):      return {"tag": "h4", "children": [text]}
    def bold(text):    return {"tag": "b", "children": [text]}
    def hr():          return {"tag": "hr"}
    def pre(text):     return {"tag": "pre", "children": [text]}
    def ul(items):
        return {"tag": "ul", "children": [
            {"tag": "li", "children": [i]} for i in items
        ]}

    nodes = []

    # 價格
    nodes.append(p(f"USD/JPY　{data['price']:.2f}　日圓{'升值' if data['change'] < 0 else '貶值'} {abs(data['change']):.2f}（{data['pct']:.2f}%）"))
    if data['danger']:
        nodes.append(p(f"⚠️ {data['danger']}"))
    nodes.append(hr())

    # COT
    nodes.append(h4("🏦 大戶持倉 COT"))
    for ln in data['cot'].split('\n'):
        if ln.strip():
            nodes.append(p(ln.strip()))
    nodes.append(hr())

    # 央行資產負債表
    if data.get('cb'):
        nodes.append(h4("🏛️ 央行資產負債表"))
        for ln in data['cb'].split('\n'):
            if ln.strip():
                nodes.append(p(ln.strip()))
        nodes.append(hr())

    # 本週重要事件
    nodes.append(h4("📰 本週重要事件"))
    for ln in data['news'].split('\n'):
        if ln.strip():
            nodes.append(p(ln.strip()))
    nodes.append(hr())

    # 技術面
    nodes.append(h4("📐 技術面區間"))
    current_price = data['price']
    tech = data['tech']
    tech_items = [
        ("ma20", "MA20 短期均線"),
        ("ma50", "MA50 中期均線"),
        ("high20", "20日高點"),
        ("low20", "20日低點"),
    ]
    raw_levels = []
    for key, label in tech_items:
        price = tech.get(key)
        if price is None:
            continue
        if price < current_price:
            icon = "🟢"
        elif price > current_price:
            icon = "🔴"
        else:
            icon = "🟡"
        raw_levels.append((price, label, icon))

    lower_levels = sorted([item for item in raw_levels if item[0] < current_price], key=lambda x: x[0])
    upper_levels = sorted([item for item in raw_levels if item[0] > current_price], key=lambda x: x[0])
    equal_levels = [item for item in raw_levels if item[0] == current_price]
    lines = [f"{icon} {price:.2f}  {label}" for price, label, icon in lower_levels + equal_levels]
    lines.append(f"▶️ {current_price:.2f}  現價")
    lines.extend(f"{icon} {price:.2f}  {label}" for price, label, icon in upper_levels)
    levels = "\n".join(lines)
    nodes.append(pre(levels))
    nodes.append(hr())

    # 下週行事曆
    nodes.append(h4("📅 下週行事曆"))
    cal_items = [ln.strip() for ln in data['calendar'].split('\n') if ln.strip()]
    nodes.append(ul(cal_items))
    nodes.append(hr())

    # 本週判斷
    nodes.append(h4("🎯 本週判斷"))
    for ln in data['verdict'].split('\n'):
        if ln.strip():
            nodes.append(p(ln.strip()))

    nodes.append(hr())
    nodes.append(p("本報告為個人市場觀察記錄，僅供參考，不構成投資建議。"))

    return nodes


def send_telegraph_link(url, summary):
    text = f"💴 <b>日圓週報</b>\n\n{summary}\n\n📖 <a href='{url}'>完整報告</a>"
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_PUBLIC, "text": text, "parse_mode": "HTML"},
        timeout=15
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

    print("📡 建立 Telegraph 帳號...")
    token = create_telegraph_account()

    print("📝 發佈文章...")
    title = f"日圓週報　{data['date']}"
    nodes = build_nodes(data)
    url = publish_to_telegraph(token, title, nodes)
    print(f"✅ 發佈成功：{url}")

    print("📨 發送 TG 連結...")
    summary = f"USD/JPY　{data['price']:.2f}　日圓升值 {abs(data['change']):.2f}\n🎯 日圓偏弱｜關鍵：美國 Flash PMI"
    result = send_telegraph_link(url, summary)
    if result.get('ok'):
        print("✅ TG 已送出")
    else:
        print(f"❌ 失敗：{result}")
