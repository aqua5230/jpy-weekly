import logging
import re

from utils import call_deepseek

logger = logging.getLogger(__name__)


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
    return call_deepseek(prompt, timeout=180, fallback_text=fallback)
