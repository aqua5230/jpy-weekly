#!/usr/bin/env python3
import json
import os
import random
from contextlib import redirect_stderr
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf

from data_provider import (
    DataFetchError,
    fetch_boj_assets,
    fetch_fed_assets,
    fetch_japan_rate,
    fetch_us10y,
    fetch_usdjpy_weekly,
)

try:
    from sklearn.ensemble import RandomForestClassifier
except Exception:  # pragma: no cover - optional dependency
    RandomForestClassifier = None


COT_HISTORY = Path.home() / ".cot_history.json"
LEGACY_COT_HISTORY = Path("/Users/lollapalooza/Desktop/投資/.cot_history.json")
LOOKBACK_WEEKS = 260
LOOKBACK_YEARS = 5
WEEKS_PER_YEAR = 52
RISK_FREE_RATE_ANNUAL = 0.04


@dataclass
class BacktestStats:
    total_signals: int
    correct_signals: int
    win_rate_pct: float
    strong_signal_count: int
    strong_signal_win_rate: float
    avg_profit_pct: float
    avg_loss_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    profit_factor: float
    total_return_pct: float
    benchmark_return_pct: float
    start_date: str
    end_date: str


@dataclass
class MLStats:
    test_accuracy_pct: float
    latest_up_probability_pct: float
    latest_down_probability_pct: float
    latest_prediction: str


@dataclass
class BacktestResult:
    frame: pd.DataFrame
    stats: BacktestStats
    data_mode: str
    note: str | None
    ml_stats: MLStats | None
    factor_weights: dict[str, float]


def load_cot_history() -> list[dict]:
    for path in (COT_HISTORY, LEGACY_COT_HISTORY):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return []


def load_cot_series() -> pd.Series:
    history = load_cot_history()
    if not history:
        return pd.Series(dtype=float, name="net_short")

    cot = pd.DataFrame(history)
    if cot.empty or "date" not in cot or "net_short" not in cot:
        return pd.Series(dtype=float, name="net_short")

    cot["date"] = pd.to_datetime(cot["date"], errors="coerce")
    cot["net_short"] = pd.to_numeric(cot["net_short"], errors="coerce")
    cot = cot.dropna(subset=["date", "net_short"]).sort_values("date")
    if cot.empty:
        return pd.Series(dtype=float, name="net_short")
    return cot.set_index("date")["net_short"]

def asof_join(base: pd.DataFrame, series: pd.Series, column_name: str) -> pd.DataFrame:
    if series.empty:
        base[column_name] = pd.NA
        return base

    s = series.sort_index().rename(column_name).copy()
    s.index.name = "date"  # 統一 index name
    joined = pd.merge_asof(
        base.reset_index().rename(columns={"index": "date"}),
        s.reset_index(),
        on="date",
        direction="backward",
    )
    return joined.set_index("date")


def safe_signal(condition: pd.Series, positive: int = 1, negative: int = -1) -> pd.Series:
    signal = pd.Series(negative, index=condition.index, dtype="int64")
    signal.loc[condition] = positive
    signal.loc[condition.isna()] = 0
    return signal


def annualization_weeks(sample_size: int) -> float:
    return float(min(sample_size, WEEKS_PER_YEAR)) if sample_size > 0 else 0.0


def calculate_factor_weights(frame: pd.DataFrame) -> dict[str, float]:
    factor_cols = ["signal_ratio", "signal_ma", "signal_cot", "signal_rate", "signal_vix"]
    next_close = frame["usdjpy_close"].shift(-1)
    sharpe_values: dict[str, float] = {}

    for col in factor_cols:
        signal = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        strategy_return_pct = pd.Series(0.0, index=frame.index, dtype=float)
        long_mask = signal > 0
        short_mask = signal < 0
        strategy_return_pct.loc[long_mask] = (
            (frame.loc[long_mask, "usdjpy_close"] - next_close.loc[long_mask])
            / frame.loc[long_mask, "usdjpy_close"]
            * 100
        )
        strategy_return_pct.loc[short_mask] = (
            (next_close.loc[short_mask] - frame.loc[short_mask, "usdjpy_close"])
            / frame.loc[short_mask, "usdjpy_close"]
            * 100
        )

        factor_returns = (strategy_return_pct / 100).dropna()
        sharpe = 0.0
        if not factor_returns.empty:
            std = factor_returns.std()
            if pd.notna(std) and std > 0:
                sharpe = float(factor_returns.mean() / std * (annualization_weeks(len(factor_returns)) ** 0.5))
        signal_changes = signal.diff().ne(0).sum()
        is_low_frequency = signal_changes < len(signal) * 0.1
        if sharpe > 0:
            sharpe_values[col] = sharpe
        else:
            sharpe_values[col] = 0.5 if is_low_frequency else 0.01

    total_sharpe = sum(sharpe_values.values())
    if total_sharpe <= 0:
        return {col: 1.0 for col in factor_cols}
    return {col: value / total_sharpe * len(factor_cols) for col, value in sharpe_values.items()}


def calculate_signals(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    has_ratio_inputs = (
        "fed_assets" in frame
        and "boj_assets" in frame
        and frame["fed_assets"].notna().any()
        and frame["boj_assets"].notna().any()
    )
    if has_ratio_inputs:
        frame["fed_boj_ratio"] = frame["fed_assets"] / frame["boj_assets"]
        frame["ratio_yoy"] = frame["fed_boj_ratio"].pct_change(periods=LOOKBACK_WEEKS)
        frame["signal_ratio"] = safe_signal(frame["ratio_yoy"] > 0)
    else:
        frame["fed_boj_ratio"] = pd.NA
        frame["ratio_yoy"] = pd.NA
        frame["signal_ratio"] = 0

    frame["ma20"] = frame["usdjpy_close"].rolling(20).mean()
    frame["signal_ma"] = 0
    frame.loc[frame["usdjpy_close"] < frame["ma20"], "signal_ma"] = 1
    frame.loc[frame["usdjpy_close"] > frame["ma20"], "signal_ma"] = -1

    if "us10y_rate" in frame and "japan_rate" in frame:
        frame["rate_diff"] = frame["us10y_rate"] - frame["japan_rate"]
        frame["rate_diff_ma260"] = frame["rate_diff"].rolling(LOOKBACK_WEEKS).mean()
        rate_condition = (frame["rate_diff"] < frame["rate_diff_ma260"]).astype("boolean")
        rate_condition = rate_condition.mask(frame["rate_diff"].isna() | frame["rate_diff_ma260"].isna())
        frame["signal_rate"] = safe_signal(rate_condition)
    else:
        frame["rate_diff"] = pd.NA
        frame["rate_diff_ma260"] = pd.NA
        frame["signal_rate"] = 0

    if "net_short" in frame and frame["net_short"].notna().any():
        frame["cot_ma4"] = frame["net_short"].rolling(4).mean()
        frame["cot_ma260"] = frame["net_short"].rolling(LOOKBACK_WEEKS).mean()
        cot_condition = (frame["cot_ma4"] > frame["cot_ma260"]).astype("boolean")
        cot_condition = cot_condition.mask(frame["cot_ma4"].isna() | frame["cot_ma260"].isna())
        frame["signal_cot"] = safe_signal(cot_condition)
    else:
        frame["cot_ma4"] = pd.NA
        frame["cot_ma260"] = pd.NA
        frame["signal_cot"] = 0

    # VIX 因子：VIX > 長期週MA = 避險情緒 = 日圓升
    if "vix" in frame and frame["vix"].notna().any():
        frame["vix_ma260"] = frame["vix"].rolling(LOOKBACK_WEEKS).mean()
        vix_condition = (frame["vix"] > frame["vix_ma260"]).astype("boolean")
        vix_condition = vix_condition.mask(frame["vix"].isna() | frame["vix_ma260"].isna())
        frame["signal_vix"] = safe_signal(vix_condition)
    else:
        frame["vix_ma260"] = pd.NA
        frame["signal_vix"] = 0

    factor_weights = calculate_factor_weights(frame)
    frame.attrs["factor_weights"] = factor_weights
    frame["signal_total"] = sum(frame[col] * factor_weights[col] for col in factor_weights)
    frame["active_weight_sum"] = frame.apply(
        lambda row: sum(factor_weights[col] for col in factor_weights if abs(row[col]) > 0),
        axis=1,
    )
    frame["is_strong_signal"] = frame["signal_total"].abs() >= frame["active_weight_sum"] * 0.6

    frame["next_close"] = frame["usdjpy_close"].shift(-1)
    frame["next_week_change"] = frame["next_close"] - frame["usdjpy_close"]
    frame["prediction"] = frame["signal_total"].map(
        lambda x: "JPY_APPRECIATE" if x > 0 else ("JPY_DEPRECIATE" if x < 0 else "NO_SIGNAL")
    )
    frame["actual"] = frame["next_week_change"].map(
        lambda x: "JPY_APPRECIATE" if x < 0 else ("JPY_DEPRECIATE" if x > 0 else "FLAT")
    )

    frame["strategy_return_pct"] = 0.0
    up_mask = frame["prediction"] == "JPY_APPRECIATE"
    down_mask = frame["prediction"] == "JPY_DEPRECIATE"
    frame.loc[up_mask, "strategy_return_pct"] = (
        (frame.loc[up_mask, "usdjpy_close"] - frame.loc[up_mask, "next_close"])
        / frame.loc[up_mask, "usdjpy_close"]
        * 100
    )
    frame.loc[down_mask, "strategy_return_pct"] = (
        (frame.loc[down_mask, "next_close"] - frame.loc[down_mask, "usdjpy_close"])
        / frame.loc[down_mask, "usdjpy_close"]
        * 100
    )

    frame["is_correct"] = (
        ((frame["prediction"] == "JPY_APPRECIATE") & (frame["actual"] == "JPY_APPRECIATE"))
        | ((frame["prediction"] == "JPY_DEPRECIATE") & (frame["actual"] == "JPY_DEPRECIATE"))
    )

    cutoff = frame.index.max() - pd.DateOffset(years=LOOKBACK_YEARS)
    frame = frame.loc[frame.index >= cutoff].copy()
    frame = frame.dropna(subset=["ma20", "next_close"])
    if has_ratio_inputs:
        frame = frame.dropna(subset=["ratio_yoy"])
    frame = frame[frame["prediction"] != "NO_SIGNAL"].copy()
    return frame


def build_demo_input_frame() -> pd.DataFrame:
    rng = random.Random(42)
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=260, freq="W-FRI")

    price = []
    fed_assets = []
    boj_assets = []
    us10y_rate = []
    japan_rate = []
    net_short = []
    current_price = 142.0
    current_fed = 8_100_000.0
    current_boj = 735_000_000.0
    current_us10y = 3.8
    current_jp10y = 0.8
    current_net_short = 20_000.0

    for i, _ in enumerate(dates):
        cyclical = ((i % 26) - 13) * 0.08
        current_price += cyclical + rng.uniform(-1.8, 1.8)
        current_price = max(105.0, min(165.0, current_price))
        current_fed *= 1 + rng.uniform(-0.004, 0.006)
        current_boj *= 1 + rng.uniform(-0.002, 0.004)
        current_us10y = min(5.5, max(1.5, current_us10y + rng.uniform(-0.12, 0.12)))
        current_jp10y = min(2.2, max(0.0, current_jp10y + rng.uniform(-0.05, 0.05)))
        current_net_short += rng.uniform(-6_000, 6_000) + ((i % 17) - 8) * 350
        current_net_short = max(-80_000.0, min(120_000.0, current_net_short))

        price.append(current_price)
        fed_assets.append(current_fed)
        boj_assets.append(current_boj)
        us10y_rate.append(current_us10y)
        japan_rate.append(current_jp10y)
        net_short.append(current_net_short)

    return pd.DataFrame(
        {
            "usdjpy_close": price,
            "fed_assets": fed_assets,
            "boj_assets": boj_assets,
            "us10y_rate": us10y_rate,
            "japan_rate": japan_rate,
            "net_short": net_short,
        },
        index=dates,
    ).rename_axis("date")


def build_signal_frame():
    notes: list[str] = []
    try:
        price = fetch_usdjpy_weekly()
        cot_series = load_cot_series()
        if cot_series.empty:
            raise DataFetchError("COT 歷史為空，無法建立 COT 因子")
    except DataFetchError as exc:
        demo_frame = build_demo_input_frame()
        return calculate_signals(demo_frame), "DEMO", str(exc)

    def record_series_note(series: pd.Series) -> None:
        note = series.attrs.get("note")
        if note:
            notes.append(str(note))

    try:
        fed_assets = fetch_fed_assets()
        record_series_note(fed_assets)
    except DataFetchError as exc:
        notes.append(f"fed_assets 失敗，ratio 因子改為跳過: {exc}")
        fed_assets = pd.Series(dtype=float)

    try:
        boj_assets = fetch_boj_assets()
        record_series_note(boj_assets)
    except DataFetchError as exc:
        notes.append(f"boj_assets 失敗，ratio 因子改為跳過: {exc}")
        boj_assets = pd.Series(dtype=float)

    try:
        us10y_rate = fetch_us10y()
        record_series_note(us10y_rate)
    except DataFetchError as exc:
        notes.append(f"us10y_rate 失敗，rate 因子改為跳過: {exc}")
        us10y_rate = pd.Series(dtype=float)

    try:
        japan_rate = fetch_japan_rate()
        record_series_note(japan_rate)
    except DataFetchError as exc:
        notes.append(f"japan_rate 失敗，rate 因子改為跳過: {exc}")
        japan_rate = pd.Series(dtype=float)

    # VIX：避險情緒因子
    try:
        import contextlib
        with open(os.devnull, "w") as devnull, contextlib.redirect_stderr(devnull):
            vix_hist = yf.Ticker("^VIX").history(period="10y", interval="1wk", auto_adjust=False)
        if not vix_hist.empty:
            vix_series = vix_hist["Close"].copy()
            vix_series.index = pd.to_datetime(vix_series.index).tz_localize(None)
            vix_series.name = "vix"
            vix_series.index.name = "date"
        else:
            vix_series = pd.Series(dtype=float)
            notes.append("VIX 抓取空資料")
    except Exception as exc:
        vix_series = pd.Series(dtype=float)
        notes.append(f"VIX 失敗: {exc}")

    frame = price.copy()
    frame.index.name = "date"
    frame = asof_join(frame, fed_assets, "fed_assets")
    frame = asof_join(frame, boj_assets, "boj_assets")
    frame = asof_join(frame, us10y_rate, "us10y_rate")
    frame = asof_join(frame, japan_rate, "japan_rate")
    frame = asof_join(frame, cot_series, "net_short")
    frame = asof_join(frame, vix_series, "vix")
    note = " | ".join(notes) if notes else None
    return calculate_signals(frame), "REAL", note


def summarize_backtest(frame: pd.DataFrame) -> BacktestStats:
    total_signals = int(len(frame))
    correct_signals = int(frame["is_correct"].sum())
    win_rate_pct = (correct_signals / total_signals * 100) if total_signals else 0.0
    strong_frame = frame[frame["is_strong_signal"]]
    strong_signal_count = int(len(strong_frame))
    strong_signal_win_rate = float(strong_frame["is_correct"].mean() * 100) if strong_signal_count else 0.0

    profits = frame.loc[frame["strategy_return_pct"] > 0, "strategy_return_pct"]
    losses = frame.loc[frame["strategy_return_pct"] < 0, "strategy_return_pct"]

    weekly_returns = frame["strategy_return_pct"] / 100
    weekly_std = weekly_returns.std()
    sharpe_ratio = 0.0
    annualization = annualization_weeks(len(weekly_returns))
    risk_free_weekly = 0.0
    if annualization > 0:
        risk_free_weekly = RISK_FREE_RATE_ANNUAL / annualization
    excess_return = weekly_returns.mean() - risk_free_weekly
    if (
        pd.notna(weekly_std)
        and weekly_std > 0
        and annualization > 0
        and pd.notna(excess_return)
    ):
        sharpe_ratio = float(
            excess_return
            / weekly_std
            * (annualization ** 0.5)
        )

    cumulative = (1 + weekly_returns).cumprod()
    max_drawdown_pct = float(
        ((cumulative - cumulative.cummax()) / cumulative.cummax()).min() * 100
    ) if not cumulative.empty else 0.0
    gross_profit = weekly_returns[weekly_returns > 0].sum()
    gross_loss = weekly_returns[weekly_returns < 0].sum()
    gross_loss_abs = abs(gross_loss)
    if gross_loss_abs > 0:
        profit_factor = float(gross_profit / gross_loss_abs)
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0
    total_return_pct = float((cumulative.iloc[-1] - 1) * 100) if not cumulative.empty else 0.0

    first_price = frame["usdjpy_close"].iloc[0]
    last_price = frame["usdjpy_close"].iloc[-1]
    benchmark_return_pct = float((first_price - last_price) / first_price * 100)

    return BacktestStats(
        total_signals=total_signals,
        correct_signals=correct_signals,
        win_rate_pct=win_rate_pct,
        strong_signal_count=strong_signal_count,
        strong_signal_win_rate=strong_signal_win_rate,
        avg_profit_pct=float(profits.mean()) if not profits.empty else 0.0,
        avg_loss_pct=float(losses.mean()) if not losses.empty else 0.0,
        sharpe_ratio=sharpe_ratio,
        max_drawdown_pct=max_drawdown_pct,
        profit_factor=profit_factor,
        total_return_pct=total_return_pct,
        benchmark_return_pct=benchmark_return_pct,
        start_date=frame.index.min().strftime("%Y-%m-%d"),
        end_date=frame.index.max().strftime("%Y-%m-%d"),
    )


def run_ml_analysis(frame: pd.DataFrame) -> MLStats | None:
    if RandomForestClassifier is None or len(frame) < 30:
        return None

    feature_cols = ["signal_ratio", "signal_ma", "signal_cot", "signal_rate", "ratio_yoy"]
    if any(col not in frame.columns for col in feature_cols):
        return None

    ml_frame = frame.dropna(subset=feature_cols + ["is_correct"]).copy()
    if len(ml_frame) < 30:
        return None

    split_idx = max(int(len(ml_frame) * 0.8), 1)
    if split_idx >= len(ml_frame):
        return None

    X_train = ml_frame.iloc[:split_idx][feature_cols]
    y_train = ml_frame.iloc[:split_idx]["is_correct"].astype(int)
    X_test = ml_frame.iloc[split_idx:][feature_cols]
    y_test = ml_frame.iloc[split_idx:]["is_correct"].astype(int)
    if X_test.empty or y_train.nunique() < 2:
        return None

    model = RandomForestClassifier(n_estimators=300, max_depth=5, random_state=42)
    model.fit(X_train, y_train)

    test_accuracy_pct = float(model.score(X_test, y_test) * 100)
    latest_features = ml_frame.iloc[[-1]][feature_cols]
    latest_proba = model.predict_proba(latest_features)[0]
    classes = list(model.classes_)
    prob_correct = float(latest_proba[classes.index(1)]) if 1 in classes else 0.0
    prob_incorrect = float(latest_proba[classes.index(0)]) if 0 in classes else 0.0
    return MLStats(
        test_accuracy_pct=test_accuracy_pct,
        latest_up_probability_pct=prob_correct * 100,
        latest_down_probability_pct=prob_incorrect * 100,
        latest_prediction="CORRECT" if prob_correct >= prob_incorrect else "INCORRECT",
    )


def format_report(
    frame: pd.DataFrame,
    stats: BacktestStats,
    data_mode: str,
    note: str | None,
    ml_stats: MLStats | None,
    factor_weights: dict[str, float],
) -> str:
    latest_rows = frame.tail(5).copy()
    latest_rows.index = latest_rows.index.strftime("%Y-%m-%d")

    lines = [
        "USD/JPY Werner Backtest",
        f"資料模式: {data_mode}",
        f"期間: {stats.start_date} ~ {stats.end_date}",
        f"總次數: {stats.total_signals}",
        f"正確次數: {stats.correct_signals}",
        f"勝率: {stats.win_rate_pct:.2f}%",
        f"強訊號次數: {stats.strong_signal_count}",
        f"強訊號勝率: {stats.strong_signal_win_rate:.2f}%",
        f"平均獲利: {stats.avg_profit_pct:.3f}%",
        f"平均虧損: {stats.avg_loss_pct:.3f}%",
        f"Sharpe Ratio: {stats.sharpe_ratio:.3f}",
        f"Max Drawdown: {stats.max_drawdown_pct:.3f}%",
        f"Profit Factor: {stats.profit_factor:.3f}",
        f"Total Return: {stats.total_return_pct:.3f}%",
        f"Benchmark Return (Long JPY): {stats.benchmark_return_pct:.3f}%",
        f"COT 歷史筆數: {len(load_cot_history())}",
        (
            "因子權重: "
            f"Werner={factor_weights['signal_ratio']:.2f} "
            f"MA={factor_weights['signal_ma']:.2f} "
            f"COT={factor_weights['signal_cot']:.2f} "
            f"利差={factor_weights['signal_rate']:.2f} "
            f"VIX={factor_weights['signal_vix']:.2f}"
        ),
    ]
    if note:
        lines.insert(2, f"備註: {note}")

    if ml_stats:
        lines.extend(
            [
                f"ML Test Accuracy: {ml_stats.test_accuracy_pct:.2f}%",
                (
                    "ML Latest Prob: "
                    f"correct={ml_stats.latest_up_probability_pct:.2f}% "
                    f"/ incorrect={ml_stats.latest_down_probability_pct:.2f}% "
                    f"-> {ml_stats.latest_prediction}"
                ),
            ]
        )
    else:
        lines.append("ML: unavailable")

    lines.append("")
    lines.append("最近 5 筆訊號:")
    for date, row in latest_rows.iterrows():
        lines.append(
            f"{date} | total={row['signal_total']:+.2f} | "
            f"ratio/ma/cot/rate/vix={int(row['signal_ratio']):+d}/{int(row['signal_ma']):+d}/"
            f"{int(row['signal_cot']):+d}/{int(row['signal_rate']):+d}/{int(row.get('signal_vix', 0)):+d} | "
            f"strong={'Y' if row['is_strong_signal'] else 'N'} | pred={row['prediction']} | "
            f"actual={row['actual']} | ret={row['strategy_return_pct']:+.3f}% | "
            f"{'OK' if row['is_correct'] else 'MISS'}"
        )
    return "\n".join(lines)


def run_backtest() -> BacktestResult:
    frame, data_mode, note = build_signal_frame()
    if frame.empty:
        raise RuntimeError("回測結果為空，請檢查資料來源是否完整")
    stats = summarize_backtest(frame)
    ml_stats = run_ml_analysis(frame)
    factor_weights = frame.attrs.get("factor_weights", {})
    return BacktestResult(
        frame=frame,
        stats=stats,
        data_mode=data_mode,
        note=note,
        ml_stats=ml_stats,
        factor_weights=factor_weights,
    )


def main():
    result = run_backtest()
    print(
        format_report(
            result.frame,
            result.stats,
            result.data_mode,
            result.note,
            result.ml_stats,
            result.factor_weights,
        )
    )


if __name__ == "__main__":
    main()
