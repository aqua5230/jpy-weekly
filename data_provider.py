#!/usr/bin/env python3
import io
import os
import re
from contextlib import redirect_stderr
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf


FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
USER_AGENT = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
FED_H41_CURRENT_URL = "https://www.federalreserve.gov/releases/h41/current/h41.htm"
BOJ_RATE_HTML_URL = "https://www.stat-search.boj.or.jp/ssi/mtshtml/fm08_m_1.html"
BOJ_ASSETS_HTML_URL = "https://www.stat-search.boj.or.jp/ssi/mtshtml/md01_m_1.html"
FRED_CACHE_DIR = Path(__file__).parent


class DataFetchError(RuntimeError):
    pass


def _fred_cache_path(series_id: str) -> Path:
    return FRED_CACHE_DIR / f".fred_cache_{series_id}.csv"


def _parse_fred_df(text: str, series_id: str, value_name: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    date_col = "DATE" if "DATE" in df.columns else "observation_date"
    val_col = series_id if series_id in df.columns else df.columns[-1]
    df["DATE"] = pd.to_datetime(df[date_col], errors="coerce")
    df[value_name] = pd.to_numeric(df[val_col], errors="coerce")
    df = df.dropna(subset=["DATE", value_name]).sort_values("DATE")
    return df.set_index("DATE")[value_name]


def _read_cached_series(series_id: str, value_name: str) -> pd.Series:
    cache_path = _fred_cache_path(series_id)
    if not cache_path.exists():
        raise DataFetchError(f"{series_id} 無快取")
    series = _parse_fred_df(cache_path.read_text(encoding="utf-8"), series_id, value_name)
    if series.empty:
        raise DataFetchError(f"{series_id} 快取無有效資料")
    return series


def _attach_note(series: pd.Series, note: str | None) -> pd.Series:
    if note:
        series.attrs["note"] = note
    return series


def _flatten_columns(columns) -> list[str]:
    flat: list[str] = []
    for col in columns:
        if isinstance(col, tuple):
            parts = [str(part).strip() for part in col if str(part).strip() and str(part).strip() != "nan"]
            flat.append(" ".join(parts))
        else:
            flat.append(str(col).strip())
    return flat


def _coerce_numeric(value) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_table_row_series(
    tables: list[pd.DataFrame],
    row_patterns: list[str],
    value_name: str,
    value_transform=None,
) -> pd.Series:
    for table in tables:
        df = table.copy()
        df.columns = _flatten_columns(df.columns)
        text_df = df.astype(str)
        row_mask = text_df.apply(
            lambda row: any(
                re.search(pattern, " ".join(row.tolist()), flags=re.IGNORECASE)
                for pattern in row_patterns
            ),
            axis=1,
        )
        if not row_mask.any():
            continue

        row = df.loc[row_mask].iloc[0]
        points: list[tuple[pd.Timestamp, float]] = []
        for column, raw_value in row.items():
            date = pd.to_datetime(str(column), errors="coerce")
            value = _coerce_numeric(raw_value)
            if pd.isna(date) or value is None:
                continue
            if value_transform is not None:
                value = value_transform(value)
            points.append((pd.Timestamp(date).normalize(), value))
        if not points:
            continue

        series = pd.Series(
            [value for _, value in points],
            index=pd.DatetimeIndex([date for date, _ in points], name="DATE"),
            name=value_name,
            dtype=float,
        ).sort_index()
        series = series[~series.index.duplicated(keep="last")]
        if not series.empty:
            return series

    raise DataFetchError(f"{value_name} 表格解析失敗")


def _parse_jgb_era_date(date_str: str) -> pd.Timestamp:
    era_map = {"S": 1925, "H": 1988, "R": 2018, "T": 1911, "M": 1867}
    s = date_str.strip()
    for era, offset in era_map.items():
        if s.startswith(era):
            rest = s[1:]
            parts = rest.replace(".", "/").split("/")
            if len(parts) == 3:
                year = int(parts[0]) + offset
                month = int(parts[1])
                day = int(parts[2])
                return pd.Timestamp(year, month, day)
    return pd.to_datetime(s, errors="coerce")


def fetch_yfinance_history(symbol: str, **kwargs):
    try:
        with open(os.devnull, "w") as devnull, redirect_stderr(devnull):
            hist = yf.Ticker(symbol).history(**kwargs)
        if hist is None or hist.empty:
            raise DataFetchError(f"{symbol} 無歷史資料")
        return hist
    except Exception as exc:
        if isinstance(exc, DataFetchError):
            raise
        raise DataFetchError(f"{symbol} 抓取失敗: {exc}") from exc


def fetch_fred_series(series_id: str, value_name: str) -> pd.Series:
    cache_path = _fred_cache_path(series_id)
    response = None
    try:
        response = requests.get(FRED_CSV_URL.format(series_id=series_id), headers=USER_AGENT, timeout=30)
        response.raise_for_status()
        series = _parse_fred_df(response.text, series_id, value_name)
        if series.empty:
            raise DataFetchError(f"FRED {series_id} 無有效資料")
        cache_path.write_text(response.text, encoding="utf-8")
        return series
    except Exception as fetch_exc:
        if cache_path.exists():
            try:
                series = _parse_fred_df(cache_path.read_text(encoding="utf-8"), series_id, value_name)
                if not series.empty:
                    series.attrs["fallback_used"] = True
                    return series
            except Exception:
                pass
        status_code = getattr(response, "status_code", "N/A")
        preview = (response.text[:200].replace("\n", " ") if response is not None else "")
        raise DataFetchError(
            f"FRED {series_id} 抓取失敗（無快取）: {fetch_exc} | status_code={status_code} | body={preview}"
        ) from fetch_exc


def fetch_fred_points(series_id: str) -> list[tuple[pd.Timestamp, float]]:
    series = fetch_fred_series(series_id, series_id)
    return [(pd.Timestamp(index).to_pydatetime(), float(value)) for index, value in series.items()]


def fetch_latest_jgb_curve_row() -> dict[str, str]:
    urls = [
        "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv",
        "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv",
    ]
    last_error = None

    for url in urls:
        try:
            response = requests.get(url, headers=USER_AGENT, timeout=20)
            response.raise_for_status()
            text = response.content.decode("shift-jis")
            rows = []
            for line in text.splitlines():
                if not line.strip():
                    continue
                cols = [col.strip() for col in line.split(",")]
                if not cols or cols[0].startswith("国"):
                    continue
                rows.append(cols)
            if len(rows) < 2:
                raise DataFetchError("日本公債 CSV 資料不足")

            header = rows[0]
            valid_rows = [
                row for row in rows[1:]
                if len(row) == len(header) and re.match(r"^[RHSTrhst]\d+\.\d+\.\d+", row[0])
            ]
            if not valid_rows:
                raise DataFetchError("日本公債 CSV 找不到有效的基準日資料列")
            return dict(zip(header, valid_rows[-1]))
        except Exception as exc:
            last_error = exc

    raise DataFetchError(f"抓取日本公債殖利率失敗: {last_error}")


def fetch_fed_assets() -> pd.Series:
    try:
        response = requests.get(FED_H41_CURRENT_URL, headers=USER_AGENT, timeout=30)
        response.raise_for_status()
        tables = pd.read_html(io.StringIO(response.text))
        return _parse_table_row_series(
            tables,
            row_patterns=[r"\bTotal assets\b"],
            value_name="fed_assets",
        )
    except Exception as exc:
        try:
            series = _read_cached_series("WALCL", "fed_assets")
            return _attach_note(series, f"fed_assets 使用 WALCL 快取 fallback: {exc}")
        except Exception as cache_exc:
            raise DataFetchError(f"Fed Total Assets 抓取失敗: {exc}; 快取也失敗: {cache_exc}") from exc


def fetch_us10y() -> pd.Series:
    hist = fetch_yfinance_history("^TNX", period="10y", interval="1wk", auto_adjust=False)
    series = hist["Close"].copy()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    series = (series / 10.0).sort_index()
    series.name = "us10y_rate"
    return series


def fetch_japan_rate() -> pd.Series:
    errors: list[str] = []

    try:
        response = requests.get(
            "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv",
            headers=USER_AGENT,
            timeout=20,
        )
        response.raise_for_status()
        text = response.content.decode("shift-jis")
        rows = []
        for line in text.split("\n")[1:]:
            line = line.strip().rstrip("\r")
            if not line or line.startswith("国") or line.startswith("基準"):
                continue
            cols = [x.strip() for x in line.split(",")]
            if len(cols) > 10 and cols[10] not in ("", "-"):
                try:
                    dt = _parse_jgb_era_date(cols[0])
                    val = float(cols[10])
                    if not pd.isna(dt):
                        rows.append((dt, val))
                except (ValueError, IndexError):
                    continue
        if rows:
            series = pd.Series(
                [v for _, v in rows],
                index=pd.DatetimeIndex([d for d, _ in rows], name="DATE"),
                name="japan_rate",
                dtype=float,
            ).sort_index()
            series = series[~series.index.duplicated(keep="last")]
            return series
        errors.append("MOF CSV 解析到 0 筆有效資料")
    except Exception as exc:
        errors.append(f"MOF CSV 失敗: {exc}")

    try:
        response = requests.get(BOJ_RATE_HTML_URL, headers=USER_AGENT, timeout=30)
        response.raise_for_status()
        tables = pd.read_html(io.StringIO(response.text))
        series = _parse_table_row_series(
            tables,
            row_patterns=[r"10\s*year", r"10年", r"長期"],
            value_name="japan_rate",
        )
        series.name = "japan_rate"
        return series
    except Exception as exc:
        errors.append(f"BOJ HTML 失敗: {exc}")

    fallback_index = pd.date_range(end=pd.Timestamp.today().normalize(), periods=520, freq="W-FRI")
    fallback = pd.Series(0.7, index=fallback_index, name="japan_rate", dtype=float)
    return _attach_note(fallback, f"japan_rate 使用 FALLBACK 常數 0.7: {'; '.join(errors)}")


def fetch_boj_assets() -> pd.Series:
    try:
        response = requests.get(BOJ_ASSETS_HTML_URL, headers=USER_AGENT, timeout=30)
        response.raise_for_status()
        tables = pd.read_html(io.StringIO(response.text))
        return _parse_table_row_series(
            tables,
            row_patterns=[r"\bTotal assets\b", r"資産計", r"資産合計", r"Assets total"],
            value_name="boj_assets",
        )
    except Exception as exc:
        try:
            series = _read_cached_series("JPNASSETS", "boj_assets")
            return _attach_note(series, f"boj_assets 使用 JPNASSETS 快取 fallback: {exc}")
        except Exception as cache_exc:
            raise DataFetchError(f"BOJ 資產抓取失敗: {exc}; 快取也失敗: {cache_exc}") from exc


def fetch_usdjpy_weekly() -> pd.DataFrame:
    hist = fetch_yfinance_history("USDJPY=X", period="5y", interval="1wk", auto_adjust=False)
    df = hist[["Close"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.sort_index()
    return df.rename(columns={"Close": "usdjpy_close"})
