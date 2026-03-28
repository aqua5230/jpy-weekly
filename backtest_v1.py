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

# Step 5：compute_stats
def compute_stats(results):
    # results 是 list of dict，每筆有 score, return, correct
    total_count = len(results)
    
    # valid_count = score != 0 的筆數
    valid_results = [r for r in results if r['score'] != 0]
    valid_count = len(valid_results)
    
    # win_rate = correct==True 的筆數 / valid_count
    if valid_count == 0:
        win_rate = None
    else:
        correct_count = sum(1 for r in valid_results if r['correct'] is True)
        win_rate = correct_count / valid_count
    
    # avg_return_by_score：對每個 score 值計算平均 return
    avg_return_by_score = {}
    for score_val in [1, -0.5, 0]:
        score_results = [r for r in results if r['score'] == score_val]
        if score_results:
            avg_ret = sum(r['return'] for r in score_results) / len(score_results)
            avg_return_by_score[score_val] = avg_ret
    
    return {
        'total_count': total_count,
        'valid_count': valid_count,
        'win_rate': win_rate,
        'avg_return_by_score': avg_return_by_score
    }

# Step 6：多筆回測 + 統計
if __name__ == '__main__':
    print('=== 開始多筆回測 ===\n')
    
    backtest_results = []
    
    # 測資設計：
    # 筆1: score=+1（順勢看升），日圓升（USD/JPY 下跌）→ correct=True
    ret1, correct1 = evaluate_one_case(
        date='2026-03-17',
        score=1,
        close_price=149.50,
        next_close_price=148.80,  # 下跌，日圓升
    )
    backtest_results.append({'score': 1, 'return': ret1, 'correct': correct1})
    
    # 筆2: score=+1（順勢看升），日圓貶（USD/JPY 上漲）→ correct=False
    ret2, correct2 = evaluate_one_case(
        date='2026-03-24',
        score=1,
        close_price=149.50,
        next_close_price=151.20,  # 上漲，日圓貶
    )
    backtest_results.append({'score': 1, 'return': ret2, 'correct': correct2})
    
    # 筆3: score=-0.5（分歧看貶），日圓貶（USD/JPY 上漲）→ correct=True
    ret3, correct3 = evaluate_one_case(
        date='2026-03-31',
        score=-0.5,
        close_price=150.00,
        next_close_price=151.50,  # 上漲，日圓貶
    )
    backtest_results.append({'score': -0.5, 'return': ret3, 'correct': correct3})
    
    # 筆4: score=-0.5（分歧看貶），日圓升（USD/JPY 下跌）→ correct=False
    ret4, correct4 = evaluate_one_case(
        date='2026-04-07',
        score=-0.5,
        close_price=151.00,
        next_close_price=149.30,  # 下跌，日圓升
    )
    backtest_results.append({'score': -0.5, 'return': ret4, 'correct': correct4})
    
    # 筆5: score=0（不交易），任意方向 → correct=None
    ret5, correct5 = evaluate_one_case(
        date='2026-04-14',
        score=0,
        close_price=149.80,
        next_close_price=150.50,  # 任意方向
    )
    backtest_results.append({'score': 0, 'return': ret5, 'correct': correct5})
    
    print('\n=== 統計結果 ===')
    stats = compute_stats(backtest_results)
    
    print(f'總筆數: {stats["total_count"]}')
    print(f'有效筆數（排除 score=0）: {stats["valid_count"]}')
    print(f'勝率: {stats["win_rate"]:.1%}' if stats["win_rate"] is not None else 'N/A')
    print('各 score 平均報酬:')
    for score_val in sorted(stats["avg_return_by_score"].keys()):
        avg_ret = stats["avg_return_by_score"][score_val]
        print(f'  score={score_val:+g}: {avg_ret*100:+.2f}%')
