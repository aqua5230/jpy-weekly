import json
import logging
import re
import subprocess

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def http_get(url, **kwargs):
    resp = requests.get(url, **kwargs)
    resp.raise_for_status()
    return resp


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def http_post(url, **kwargs):
    resp = requests.post(url, **kwargs)
    resp.raise_for_status()
    return resp


def safe_last(series, label):
    try:
        if series is None:
            raise ValueError(f"{label} 缺少序列")
        cleaned = series.dropna()
        if cleaned.empty:
            raise ValueError(f"{label} 無有效資料")
        return cleaned.iloc[-1]
    except Exception as exc:
        raise ValueError(f"{label} 讀取失敗: {exc}") from exc


def safe_first(series, label):
    try:
        if series is None:
            raise ValueError(f"{label} 缺少序列")
        cleaned = series.dropna()
        if cleaned.empty:
            raise ValueError(f"{label} 無有效資料")
        return cleaned.iloc[0]
    except Exception as exc:
        raise ValueError(f"{label} 讀取失敗: {exc}") from exc


def run_text_command(cmd, timeout, fallback_text=""):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True
        )
        output = result.stdout.strip()
        if output:
            return output
        logger.warning("文字模型輸出為空，改用備用文字: %s", cmd[0] if cmd else "unknown")
    except subprocess.TimeoutExpired as exc:
        logger.exception("文字模型執行逾時: %s", exc)
    except subprocess.CalledProcessError as exc:
        logger.exception("文字模型執行失敗: %s stderr=%s", exc, (exc.stderr or "").strip())
    except FileNotFoundError as exc:
        logger.exception("文字模型指令不存在: %s", exc)
    except Exception as exc:
        logger.exception("文字模型執行異常: %s", exc)
    return fallback_text


def clean_gemini_output(text):
    lines = text.split('\n')
    skip = ['我將', '我会', '讓我', '首先，我', '我需要', '我會先', 'I will', 'I am', 'Let me',
            '日期', 'Date', '─', '—']
    return '\n'.join(
        line for line in lines
        if not any(line.strip().startswith(p) for p in skip)
        and '---' not in line
    ).strip()


def extract_json_object(text):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f"找不到 JSON 物件: {text}")
    return json.loads(match.group(0))


def is_missing_result(result):
    if result is None:
        return True
    if isinstance(result, str):
        return not result.strip()
    if isinstance(result, tuple):
        return any(item is None for item in result)
    if isinstance(result, dict):
        return not bool(result)
    return False


def load_text_cache(path) -> "str | None":
    """讀取文字快取，失敗回傳 None"""
    try:
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("text")
    except Exception:
        return None


def save_text_cache(path, text: str) -> None:
    """寫入文字快取，失敗靜默忽略"""
    try:
        import json
        from datetime import datetime
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"text": text, "saved_at": datetime.now().isoformat()}, f, ensure_ascii=False)
    except Exception:
        pass
