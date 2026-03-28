# backtest_v1.py
# 最小回測框架 v1：單週驗證，驗證 Position Score 與下週報酬的對錯邏輯

import json
import os
from datetime import date, timedelta

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
def evaluate_one_case(date_str, score, close_price, next_close_price):
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
    print(f'{date_str} | {score} | return: {sign}{return_pct:.2f}% | correct: {correct}')
    
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

def log_prediction(date_str, werner_direction, position_score, close_price, log_path):
    """每次週報跑完後記錄當下預測，不填未來欄位。"""
    # 讀取現有記錄
    records = []
    if os.path.exists(log_path):
        try:
            with open(log_path, encoding='utf-8') as f:
                records = json.load(f)
        except Exception:
            records = []

    # 若同一天已有記錄，不重複 append
    existing_dates = {r['date'] for r in records}
    if date_str in existing_dates:
        return False  # 已存在，不寫入

    # append 新記錄
    records.append({
        'date': date_str,
        'werner_direction': werner_direction,
        'position_score': position_score,
        'close_price': close_price,
        # 1週
        'next_1w_price': None,
        'return_1w': None,
        'correct_1w': None,
        # 8週
        'next_8w_price': None,
        'return_8w': None,
        'correct_8w': None,
        'status': 'pending',
        'status_8w': 'pending',
    })

    # 寫回
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return True  # 成功寫入


def load_prediction_log(log_path):
    """讀取 backtest_predictions.json
    若檔案不存在，回傳空 list
    若 JSON 壞掉，回傳空 list
    """
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_prediction_log(log_path, records):
    """把 records 寫回 log_path
    utf-8, indent=2
    """
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def resolve_pending_predictions(records, price_lookup):
    """對每筆 pending 的紀錄同時結算 1週和 8週預測。
    回傳 (records, resolved_count, pending_count)
    """
    import datetime as dt
    resolved_count = 0
    pending_count = 0
    for r in records:
        record_date = dt.date.fromisoformat(r['date'])
        # --- 結算 1週 ---
        if r.get('status') == 'pending':
            next_1w = str(record_date + dt.timedelta(days=7))
            if next_1w in price_lookup:
                r['next_1w_price'] = price_lookup[next_1w]
                r['return_1w'] = (r['next_1w_price'] - r['close_price']) / r['close_price']
                score = r['position_score']
                if score == 0:
                    r['correct_1w'] = None
                elif score > 0:
                    r['correct_1w'] = r['return_1w'] < 0
                else:
                    r['correct_1w'] = r['return_1w'] > 0
                r['status'] = 'resolved'
                resolved_count += 1
            else:
                pending_count += 1
        # --- 結算 8週 ---
        if r.get('status_8w') == 'pending':
            next_8w = str(record_date + dt.timedelta(days=56))
            if next_8w in price_lookup:
                r['next_8w_price'] = price_lookup[next_8w]
                r['return_8w'] = (r['next_8w_price'] - r['close_price']) / r['close_price']
                score = r['position_score']
                if score == 0:
                    r['correct_8w'] = None
                elif score > 0:
                    r['correct_8w'] = r['return_8w'] < 0
                else:
                    r['correct_8w'] = r['return_8w'] > 0
                r['status_8w'] = 'resolved'
    return records, resolved_count, pending_count


# Step 6：多筆回測 + 統計
if __name__ == '__main__':
    print('=== 開始多筆回測 ===\n')
    
    backtest_results = []
    
    # 測資設計：
    # 筆1: score=+1（順勢看升），日圓升（USD/JPY 下跌）→ correct=True
    ret1, correct1 = evaluate_one_case(
        date_str='2026-03-17',
        score=1,
        close_price=149.50,
        next_close_price=148.80,  # 下跌，日圓升
    )
    backtest_results.append({'score': 1, 'return': ret1, 'correct': correct1})
    
    # 筆2: score=+1（順勢看升），日圓貶（USD/JPY 上漲）→ correct=False
    ret2, correct2 = evaluate_one_case(
        date_str='2026-03-24',
        score=1,
        close_price=149.50,
        next_close_price=151.20,  # 上漲，日圓貶
    )
    backtest_results.append({'score': 1, 'return': ret2, 'correct': correct2})
    
    # 筆3: score=-0.5（分歧看貶），日圓貶（USD/JPY 上漲）→ correct=True
    ret3, correct3 = evaluate_one_case(
        date_str='2026-03-31',
        score=-0.5,
        close_price=150.00,
        next_close_price=151.50,  # 上漲，日圓貶
    )
    backtest_results.append({'score': -0.5, 'return': ret3, 'correct': correct3})
    
    # 筆4: score=-0.5（分歧看貶），日圓升（USD/JPY 下跌）→ correct=False
    ret4, correct4 = evaluate_one_case(
        date_str='2026-04-07',
        score=-0.5,
        close_price=151.00,
        next_close_price=149.30,  # 下跌，日圓升
    )
    backtest_results.append({'score': -0.5, 'return': ret4, 'correct': correct4})
    
    # 筆5: score=0（不交易），任意方向 → correct=None
    ret5, correct5 = evaluate_one_case(
        date_str='2026-04-14',
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

    print()
    print('=== R5.4 resolve 測試 ===')

    # mock 一筆 pending 紀錄
    test_records = [
        {
            'date': '2026-03-24',
            'werner_direction': '升',
            'position_score': 1,
            'close_price': 149.50,
            'next_1w_price': None, 'return_1w': None, 'correct_1w': None,
            'next_8w_price': None, 'return_8w': None, 'correct_8w': None,
            'status': 'pending', 'status_8w': 'pending',
        },
        {
            'date': '2026-03-31',
            'werner_direction': '貶',
            'position_score': -0.5,
            'close_price': 150.00,
            'next_1w_price': None, 'return_1w': None, 'correct_1w': None,
            'next_8w_price': None, 'return_8w': None, 'correct_8w': None,
            'status': 'pending', 'status_8w': 'pending',
        },
    ]

    # mock price_lookup：只有 2026-03-31 的價格，沒有 2026-04-07
    price_lookup = {
        '2026-03-31': 148.80,  # 2026-03-24 的下一週，日圓升（USD/JPY 跌）→ score=1 correct=True
    }

    records, resolved, pending = resolve_pending_predictions(test_records, price_lookup)
    print(f'resolved: {resolved} 筆，仍 pending: {pending} 筆')
    for r in records:
        print(json.dumps(r, ensure_ascii=False))


def holding_backtest(records: list) -> dict:
    position = 0
    entry_price = None
    trades = []

    for record in records:
        score = record['position_score']
        price = record['close_price']

        if score == 1 and position == 0:
            position = 1
            entry_price = price
        elif position == 1 and score < 0:
            ret = (entry_price - price) / entry_price
            trades.append({
                'entry': entry_price,
                'exit': price,
                'return': ret,
                'correct': ret > 0,
            })
            position = 0
            entry_price = None

    total = len(trades)
    if total == 0:
        win_rate = 0.0
        avg_return = 0.0
    else:
        win_rate = sum(1 for trade in trades if trade['correct']) / total
        avg_return = sum(trade['return'] for trade in trades) / total

    return {
        'trades': trades,
        'total': total,
        'win_rate': win_rate,
        'avg_return': avg_return,
    }
