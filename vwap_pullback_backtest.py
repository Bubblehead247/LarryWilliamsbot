"""
Long VWAP Pullback intraday backtest on 5-minute bars.

Strategy (all deterministic, vectorized where possible):
  1. Fresh intraday VWAP + volume-weighted stdev bands, reset every calendar day.
  2. Entry requires, on bar t:
       A) High >= VWAP + 1.0*sigma at some point in bars [t-5, t-1] (prior impulsive push)
       B) Low_t <= VWAP_t + 0.2*sigma_t  AND  Close_t >= VWAP_t - 0.5*sigma_t (pullback into VWAP zone)
       C) Volume_t < 0.8 * vol_sma20_t (volume contraction)
       D) Close_t > Open_t AND (Close_t - Low_t) / (High_t - Low_t) >= 0.60 (bullish reversal bar)
  3. Entry fills at Open of bar t+1.
  4. Stop-loss = min(Low_t, VWAP_t) - 0.5*ATR14_t ; Take-profit = Entry + 2*(Entry - SL).
  5. Position is force-closed at the final bar's Close if neither TP nor SL is hit by end of session
     (no overnight holding).

Run: python vwap_pullback_backtest.py --ticker QQQ
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Strategy constants
# ---------------------------------------------------------------------------
PUSH_LOOKBACK_BARS = 5
PUSH_SIGMA_MULT = 1.0
PULLBACK_UPPER_SIGMA_MULT = 0.2
PULLBACK_LOWER_SIGMA_MULT = 0.5
VOLUME_SMA_WINDOW = 20
VOLUME_CONTRACTION_MULT = 0.8
REVERSAL_CLOSE_LOC_MIN = 0.60
ATR_WINDOW = 14
ATR_STOP_MULT = 0.5
REWARD_RISK_MULT = 2.0

STARTING_EQUITY = 100_000.0


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    sl: float
    tp: float
    return_pct: float
    exit_reason: str


def fetch_intraday_data(ticker: str, period: str = "60d", interval: str = "5m") -> pd.DataFrame:
    """Download 5-minute intraday OHLCV data for `ticker`."""
    df = yf.download(
        ticker,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
    )
    if df.empty:
        raise ValueError(f"No data returned for ticker '{ticker}'.")

    # yfinance can return a MultiIndex column frame even for a single ticker.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns=str.title)
    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Downloaded data missing columns: {missing}")

    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add VWAP, sigma bands, volume SMA, and ATR columns. Resets VWAP each day."""
    df = df.copy()
    trading_day = df.index.date

    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3.0
    df["TP"] = typical_price

    tp_vol = typical_price * df["Volume"]
    grouped_vol = df.groupby(trading_day)["Volume"]
    grouped_tp_vol = tp_vol.groupby(trading_day)

    cum_vol = grouped_vol.cumsum()
    cum_tp_vol = grouped_tp_vol.cumsum()

    # Guard against zero cumulative volume (e.g. a bar with no trades yet).
    safe_cum_vol = cum_vol.replace(0, np.nan)
    df["VWAP"] = (cum_tp_vol / safe_cum_vol).ffill().fillna(typical_price)

    sq_dev_vol = ((typical_price - df["VWAP"]) ** 2) * df["Volume"]
    cum_sq_dev_vol = sq_dev_vol.groupby(trading_day).cumsum()
    variance = (cum_sq_dev_vol / safe_cum_vol).fillna(0.0)
    df["sigma"] = np.sqrt(variance.clip(lower=0.0))

    df["Upper_1"] = df["VWAP"] + PUSH_SIGMA_MULT * df["sigma"]
    df["Upper_2"] = df["VWAP"] + 2.0 * df["sigma"]

    df["vol_sma20"] = df["Volume"].rolling(VOLUME_SMA_WINDOW, min_periods=VOLUME_SMA_WINDOW).mean()

    prev_close = df["Close"].shift(1)
    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["ATR14"] = true_range.rolling(ATR_WINDOW, min_periods=ATR_WINDOW).mean()

    df["trading_day"] = trading_day
    return df


def compute_entry_signals(df: pd.DataFrame) -> pd.Series:
    """Vectorized boolean mask for bars where all entry conditions A-D hold."""
    high_reached_upper1 = df["High"] >= df["Upper_1"]
    # Condition A: within bars t-5..t-1, High reached Upper_1 at least once.
    prior_push = (
        high_reached_upper1.shift(1)
        .rolling(PUSH_LOOKBACK_BARS, min_periods=1)
        .max()
        .fillna(0)
        .astype(bool)
    )

    # Reset the lookback at day boundaries: don't let yesterday's push qualify today's bar.
    same_day_count = df.groupby("trading_day").cumcount()
    prior_push &= same_day_count >= 1  # need at least 1 prior bar in the same session

    cond_b = (df["Low"] <= df["VWAP"] + PULLBACK_UPPER_SIGMA_MULT * df["sigma"]) & (
        df["Close"] >= df["VWAP"] - PULLBACK_LOWER_SIGMA_MULT * df["sigma"]
    )

    cond_c = df["Volume"] < VOLUME_CONTRACTION_MULT * df["vol_sma20"]

    bar_range = df["High"] - df["Low"]
    safe_range = bar_range.replace(0, np.nan)
    close_loc = (df["Close"] - df["Low"]) / safe_range
    cond_d = (df["Close"] > df["Open"]) & (close_loc >= REVERSAL_CLOSE_LOC_MIN)

    signal = prior_push & cond_b & cond_c & cond_d & df["vol_sma20"].notna() & df["ATR14"].notna()
    return signal.fillna(False)


def run_backtest(df: pd.DataFrame) -> list[Trade]:
    """Walk the bars sequentially, simulating one position at a time (no pyramiding)."""
    signals = compute_entry_signals(df)
    n = len(df)
    trades: list[Trade] = []

    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    opens = df["Open"].to_numpy()
    closes = df["Close"].to_numpy()
    vwaps = df["VWAP"].to_numpy()
    atrs = df["ATR14"].to_numpy()
    trading_days = df["trading_day"].to_numpy()
    times = df.index
    signal_arr = signals.to_numpy()

    i = 0
    while i < n - 1:
        if not signal_arr[i]:
            i += 1
            continue

        entry_idx = i + 1
        # Entry must happen within the same trading session as the signal bar.
        if trading_days[entry_idx] != trading_days[i]:
            i += 1
            continue

        entry_price = opens[entry_idx]
        sl = min(lows[i], vwaps[i]) - ATR_STOP_MULT * atrs[i]
        risk = entry_price - sl
        if risk <= 0 or np.isnan(risk):
            i += 1
            continue
        tp = entry_price + REWARD_RISK_MULT * risk

        exit_price = None
        exit_time = None
        exit_reason = None
        day = trading_days[entry_idx]

        j = entry_idx
        while j < n and trading_days[j] == day:
            is_last_bar_of_day = (j == n - 1) or (trading_days[j + 1] != day)

            if lows[j] <= sl:
                exit_price = sl
                exit_reason = "SL"
                exit_time = times[j]
                break
            if highs[j] >= tp:
                exit_price = tp
                exit_reason = "TP"
                exit_time = times[j]
                break
            if is_last_bar_of_day:
                exit_price = closes[j]
                exit_reason = "EOD"
                exit_time = times[j]
                break
            j += 1
        else:
            # Ran off the end of the data without hitting the day boundary check above.
            exit_price = closes[j - 1] if j > entry_idx else closes[entry_idx]
            exit_reason = "EOD"
            exit_time = times[j - 1] if j > entry_idx else times[entry_idx]

        return_pct = (exit_price - entry_price) / entry_price * 100.0
        trades.append(
            Trade(
                entry_time=times[entry_idx],
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                sl=sl,
                tp=tp,
                return_pct=return_pct,
                exit_reason=exit_reason,
            )
        )

        # Resume scanning for new signals only after this trade has closed.
        i = max(j, entry_idx) + 1

    return trades


def summarize_performance(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "avg_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "expectancy_dollars": 0.0,
        }

    returns_pct = np.array([t.return_pct for t in trades])
    wins = returns_pct[returns_pct > 0]
    losses = returns_pct[returns_pct <= 0]

    total_trades = len(trades)
    win_rate_pct = len(wins) / total_trades * 100.0

    gross_gain = wins.sum() if wins.size else 0.0
    gross_loss = abs(losses.sum()) if losses.size else 0.0
    profit_factor = gross_gain / gross_loss if gross_loss > 0 else float("inf") if gross_gain > 0 else 0.0

    avg_return_pct = returns_pct.mean()

    # Equity curve assuming fixed fractional (full) compounding per trade's % return.
    equity = STARTING_EQUITY * np.cumprod(1 + returns_pct / 100.0)
    equity_with_start = np.concatenate([[STARTING_EQUITY], equity])
    running_max = np.maximum.accumulate(equity_with_start)
    drawdowns = (equity_with_start - running_max) / running_max
    max_drawdown_pct = drawdowns.min() * 100.0

    avg_win_dollars = wins.mean() / 100.0 * STARTING_EQUITY if wins.size else 0.0
    avg_loss_dollars = abs(losses.mean()) / 100.0 * STARTING_EQUITY if losses.size else 0.0
    win_prob = len(wins) / total_trades
    loss_prob = len(losses) / total_trades
    expectancy_dollars = win_prob * avg_win_dollars - loss_prob * avg_loss_dollars

    return {
        "total_trades": total_trades,
        "win_rate_pct": win_rate_pct,
        "profit_factor": profit_factor,
        "avg_return_pct": avg_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "expectancy_dollars": expectancy_dollars,
    }


def save_trade_log(trades: list[Trade], path: str) -> None:
    rows = [
        {
            "Entry Time": t.entry_time,
            "Exit Time": t.exit_time,
            "Entry Price": round(t.entry_price, 4),
            "Exit Price": round(t.exit_price, 4),
            "SL": round(t.sl, 4),
            "TP": round(t.tp, 4),
            "Return %": round(t.return_pct, 4),
            "Exit Reason": t.exit_reason,
        }
        for t in trades
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def print_summary(ticker: str, stats: dict, path: str) -> None:
    print("=" * 50)
    print(f"  VWAP Pullback Backtest Summary — {ticker}")
    print("=" * 50)
    print(f"  Total Trades:          {stats['total_trades']}")
    print(f"  Win Rate:              {stats['win_rate_pct']:.2f}%")
    pf = stats["profit_factor"]
    pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
    print(f"  Profit Factor:         {pf_str}")
    print(f"  Avg Trade Return:      {stats['avg_return_pct']:.3f}%")
    print(f"  Max Drawdown:          {stats['max_drawdown_pct']:.2f}%")
    print(f"  Expectancy per Trade:  ${stats['expectancy_dollars']:.2f}")
    print("=" * 50)
    if stats["total_trades"] > 0:
        print(f"  Trade log saved to: {path}")
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Long VWAP Pullback intraday backtest")
    parser.add_argument("--ticker", type=str, default="QQQ", help="Ticker symbol (default: QQQ)")
    parser.add_argument("--period", type=str, default="60d", help="yfinance history period (default: 60d)")
    parser.add_argument("--interval", type=str, default="5m", help="Bar interval (default: 5m)")
    parser.add_argument(
        "--out", type=str, default="trades_log.csv", help="Output CSV path for the trade log"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print(f"Fetching {args.interval} data for {args.ticker} ({args.period})...")
    raw = fetch_intraday_data(args.ticker, period=args.period, interval=args.interval)
    print(f"Fetched {len(raw)} bars across {len(np.unique(raw.index.date))} trading days.")

    df = compute_indicators(raw)
    trades = run_backtest(df)
    stats = summarize_performance(trades)

    save_trade_log(trades, args.out)
    print_summary(args.ticker, stats, args.out)


if __name__ == "__main__":
    main()
