## 任務目標
修改 utils.py 中的 clean_gemini_output 函式，改用白名單策略。

## 目前程式碼（utils.py 第 85–93 行）
```python
def clean_gemini_output(text):
    lines = text.split('\n')
    skip = ['我將', '我会', '讓我', '首先，我', '我需要', '我會先', 'I will', 'I am', 'Let me',
            '日期', 'Date', '─', '—']
    return '\n'.join(
        line for line in lines
        if not any(line.strip().startswith(p) for p in skip)
        and '---' not in line
    ).strip()
```

## 要求
將 clean_gemini_output 改為：

```python
def clean_gemini_output(text):
    lines = text.split('\n')
    # 白名單：只保留數字開頭的行 或 空行
    whitelist = [
        line for line in lines
        if not line.strip() or re.match(r'^\d+\.', line.strip())
    ]
    result = '\n'.join(whitelist).strip()
    if result:
        return result
    # fallback：Gemini 沒有按格式輸出，用舊邏輯
    skip = ['我將', '我会', '讓我', '首先，我', '我需要', '我會先', 'I will', 'I am', 'Let me',
            '日期', 'Date', '─', '—']
    return '\n'.join(
        line for line in lines
        if not any(line.strip().startswith(p) for p in skip)
        and '---' not in line
    ).strip()
```

注意：utils.py 已有 import re，不需要再 import。

## 禁止
- 不改其他函式
- 不改 data_fetcher.py
- 不改其他模組

## 驗收條件
python3 -c "
from utils import clean_gemini_output
# 白名單：只保留編號行
t = '我將檢查.gitignore\n文件似乎被忽略了\n1. 美聯準會升息：日圓走弱\n2. 日銀縮表：支撐升值\n3. 油價上漲：貿易逆差擴大'
r = clean_gemini_output(t)
assert '我將' not in r, '污染未被清除'
assert '文件似乎' not in r, '污染未被清除'
assert '1. 美聯準會' in r, '正確內容被誤刪'
print('PASS')
print(r)
"

## Codex 結果
狀態：完成
