"""
日圓方向判斷引擎（Werner 四原則）

p1 = 信用創造速度（主方向）
p2 = 干預是否沖銷（短期轉折，永不主導）
p3 = 信用品質（泡沫 vs 實體）
p4 = 資本流 vs 經常帳（長期風險）
"""


def decide_jpy_direction(p1, p2, p3, p4):
    """
    p1~p4 格式：
    {
        "direction": "升" / "貶" / "中性",
        "strength": "強" / "中" / "弱"
    }

    回傳：
    {
        "direction": "升" / "貶" / "中性",
        "confidence": "高" / "中" / "低",
        "leader": "P1" / "P3" / "P4"
    }
    """
    # 決定主導原則
    if p1["strength"] in ("強", "中"):
        leader = "P1"
        main_direction = p1["direction"]
    else:
        # p1 弱 → 看 p3、p4 是否一致
        d3 = p3["direction"]
        d4 = p4["direction"]
        non_neutral = [d for d in (d3, d4) if d != "中性"]

        if len(non_neutral) == 2 and d3 == d4:
            leader = "P3" if p3["strength"] >= p4["strength"] else "P4"
            main_direction = d3
        elif len(non_neutral) == 1:
            leader = "P3" if d3 != "中性" else "P4"
            main_direction = non_neutral[0]
        else:
            return {"direction": "中性", "confidence": "低", "leader": "CONFLICT"}

    # 計算信心分數（p2 永不主導，但參與計分）
    inputs = [
        ("P1", p1),
        ("P2", p2),
        ("P3", p3),
        ("P4", p4),
    ]

    score = 0
    for name, p in inputs:
        if p["direction"] == main_direction:
            score += 1
        elif p["direction"] != "中性":
            score -= 1
        # 中性 → 0

    if score >= 2:
        confidence = "高"
    elif score == 1:
        confidence = "中"
    else:
        confidence = "低"

    return {
        "direction": main_direction,
        "confidence": confidence,
        "leader": leader,
    }
