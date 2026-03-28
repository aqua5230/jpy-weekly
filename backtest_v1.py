# backtest_v1.py
# 最小回測框架 v1：單週驗證，驗證 Position Score 與下週報酬的對錯邏輯

# Step 1：資料結構（只是一個 list of dict，不用任何 import）

# Step 2：compute_next_week_return
def compute_next_week_return(close_price, next_close_price):
    return (next_close_price - close_price) / close_price

# Step 3：對錯判斷規則
# USD/JPY 上升 = 日圓貶；USD/JPY 下降 = 日圓升
# score > 0（看日圓升）→ next_week_return < 0 → correct = True
# score < 0（看日圓貶）→ next_week_return > 0 → correct = True
# score == 0 → correct = None

# Step 4：evaluate_one_case
def evaluate_one_case(date, score, close_price, next_close_price):
    # 計算報酬
    next_week_return = compute_next_week_return(close_price, next_close_price)
    
    # 判斷 correct
    if score > 0:
        # score > 0：看日圓升 → 預期 USD/JPY 下降 → return < 0
        correct = next_week_return < 0
    elif score < 0:
        # score < 0：看日圓貶 → 預期 USD/JPY 上升 → return > 0
        correct = next_week_return > 0
    else:
        # score == 0
        correct = None
    
    # print: date, score, next_week_return (%), correct
    return_pct = next_week_return * 100
    sign = '+' if return_pct >= 0 else ''
    print(f'{date} | {score} | return: {sign}{return_pct:.2f}% | correct: {correct}')
    
    # 回傳 (next_week_return, correct)
    return (next_week_return, correct)

# Step 5：手動測試資料（2026-03-24，score 用 -0.5 示範分歧情境）
# close_price = 149.50（模擬上週收盤）
# next_close_price = 150.80（模擬下週收盤，日圓貶值方向）
# score = -0.5（分歧，看貶，日圓貶值 → next_week_return 應 > 0 → correct = True）

if __name__ == '__main__':
    result = evaluate_one_case(
        date='2026-03-24',
        score=-0.5,
        close_price=149.50,
        next_close_price=150.80,
    )
    print('Done:', result)
