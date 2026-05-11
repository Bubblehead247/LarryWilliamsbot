"""Independently testable signal filters."""
from datetime import date, datetime
import pandas as pd
import numpy as np
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
from ta.momentum import WilliamsRIndicator

import config


def _in_window_mmdd(today: date, start: str, end: str) -> bool:
    """Check whether today (MM-DD) falls in [start, end], supporting year-wrap windows."""
    s = tuple(int(x) for x in start.split("-"))
    e = tuple(int(x) for x in end.split("-"))
    md = (today.month, today.day)
    if s <= e:
        return s <= md <= e
    return md >= s or md <= e


def seasonal_pass(today: date | None = None, symbol: str | None = None) -> bool:
    """Return True if today falls inside any bullish seasonal window.

    If `symbol` is in SEASONAL_WINDOWS_BY_SYMBOL, use that table; otherwise fall back
    to the legacy GLD SEASONAL_WINDOWS list.
    """
    today = today or datetime.utcnow().date()
    if symbol and symbol in config.SEASONAL_WINDOWS_BY_SYMBOL:
        for start, end in config.SEASONAL_WINDOWS_BY_SYMBOL[symbol]:
            if _in_window_mmdd(today, start, end):
                return True
        return False
    m, d = today.month, today.day
    for (sm, sd), (em, ed) in config.SEASONAL_WINDOWS:
        if (m, d) >= (sm, sd) and (m, d) <= (em, ed):
            return True
    return False


def williams_r(price_df: pd.DataFrame, period: int) -> float:
    if len(price_df) < period + 1:
        raise ValueError("Insufficient price history for Williams %R")
    wr = WilliamsRIndicator(
        high=price_df["high"], low=price_df["low"], close=price_df["close"], lbp=period
    ).williams_r()
    return float(wr.iloc[-1])


def williams_r_pass(price_df: pd.DataFrame, symbol: str, threshold: float = -80.0) -> bool:
    """Oversold trigger: Williams %R below threshold (default -80)."""
    period = config.WILLIAMS_R_PERIOD.get(symbol, 14)
    return williams_r(price_df, period) < threshold


def cot_index(cot_df: pd.DataFrame, lookback: int = config.COT_LOOKBACK_WEEKS) -> float:
    """Percentile rank of latest net commercial position over lookback window (0-100)."""
    if cot_df is None or len(cot_df) < 2:
        raise ValueError("Insufficient COT history")
    window = cot_df["net"].tail(lookback)
    latest = window.iloc[-1]
    rank = (window <= latest).sum() / len(window) * 100.0
    return float(rank)


def cot_pass(cot_df: pd.DataFrame, threshold: float = config.COT_THRESHOLD) -> bool:
    return cot_index(cot_df) > threshold


def trend_pass(price_df: pd.DataFrame, period: int = config.EMA_PERIOD) -> bool:
    """Latest close above N-period EMA."""
    if len(price_df) < period + 1:
        raise ValueError("Insufficient price history for EMA")
    ema = EMAIndicator(close=price_df["close"], window=period).ema_indicator()
    return bool(price_df["close"].iloc[-1] > ema.iloc[-1])


def trigger_pass(price_df: pd.DataFrame) -> bool:
    """Williams exhaustion: today's low < yesterday's low AND today's close > yesterday's close."""
    if len(price_df) < 2:
        return False
    today = price_df.iloc[-1]
    yesterday = price_df.iloc[-2]
    return bool(today["low"] < yesterday["low"] and today["close"] > yesterday["close"])


def compute_atr(price_df: pd.DataFrame, period: int = config.ATR_PERIOD) -> float:
    if len(price_df) < period + 1:
        raise ValueError("Insufficient price history for ATR")
    atr = AverageTrueRange(
        high=price_df["high"], low=price_df["low"], close=price_df["close"], window=period
    ).average_true_range()
    return float(atr.iloc[-1])
