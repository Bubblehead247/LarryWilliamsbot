"""Data fetching: price history (yfinance) and COT (cftc-cot)."""
import os
import logging
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

import config

log = logging.getLogger(__name__)


def fetch_price_history(symbol: str = config.SYMBOL, lookback_days: int = 400) -> pd.DataFrame:
    """Return daily OHLCV DataFrame, indexed by date, oldest first."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=lookback_days)
    df = yf.download(symbol, start=start, end=end + timedelta(days=1),
                     progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"No price data returned for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    return df


def _cot_cache_fresh() -> bool:
    """COT is released Fridays — cache is fresh if last modified after most recent Friday."""
    if not os.path.exists(config.COT_CACHE_PATH):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(config.COT_CACHE_PATH))
    today = datetime.utcnow()
    # Days since last Friday (weekday 4)
    days_since_fri = (today.weekday() - 4) % 7
    last_friday = (today - timedelta(days=days_since_fri)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return mtime >= last_friday


def fetch_cot(force: bool = False) -> pd.DataFrame:
    """
    Fetch CFTC Legacy COT report for COMEX Gold.
    Returns DataFrame indexed by report date with columns ['comm_long','comm_short','net'].
    """
    if not force and _cot_cache_fresh():
        log.info("Using cached COT data")
        return pd.read_csv(config.COT_CACHE_PATH, parse_dates=["date"]).set_index("date")

    try:
        from cot_reports import cot_hist  # cftc-cot exposes via cot_reports
    except ImportError:
        # Fallback: read directly from CFTC if cftc-cot wrapper not present
        return _fetch_cot_direct()

    df = cot_hist(cot_report_type="legacy_fut")
    df = df[df["CFTC Contract Market Code"].astype(str).str.zfill(6) == config.COT_GOLD_CODE]
    df["date"] = pd.to_datetime(df["As of Date in Form YYYY-MM-DD"])
    out = pd.DataFrame({
        "date": df["date"],
        "comm_long": pd.to_numeric(df["Commercial Positions-Long (All)"], errors="coerce"),
        "comm_short": pd.to_numeric(df["Commercial Positions-Short (All)"], errors="coerce"),
    }).dropna().sort_values("date")
    out["net"] = out["comm_long"] - out["comm_short"]
    out.to_csv(config.COT_CACHE_PATH, index=False)
    return out.set_index("date")


def _fetch_cot_direct() -> pd.DataFrame:
    """Fallback: pull current-year Legacy futures-only report directly from CFTC."""
    import io, zipfile, urllib.request
    url = "https://www.cftc.gov/files/dea/history/deacot2025.zip"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = [n for n in z.namelist() if n.endswith(".txt")][0]
        with z.open(name) as f:
            df = pd.read_csv(f, low_memory=False)
    code_col = [c for c in df.columns if "Contract Market Code" in c][0]
    long_col = [c for c in df.columns if "Commercial" in c and "Long" in c and "All" in c][0]
    short_col = [c for c in df.columns if "Commercial" in c and "Short" in c and "All" in c][0]
    date_col = [c for c in df.columns if "As of Date" in c][0]
    df = df[df[code_col].astype(str).str.zfill(6) == config.COT_GOLD_CODE].copy()
    df["date"] = pd.to_datetime(df[date_col])
    out = pd.DataFrame({
        "date": df["date"],
        "comm_long": pd.to_numeric(df[long_col], errors="coerce"),
        "comm_short": pd.to_numeric(df[short_col], errors="coerce"),
    }).dropna().sort_values("date")
    out["net"] = out["comm_long"] - out["comm_short"]
    out.to_csv(config.COT_CACHE_PATH, index=False)
    return out.set_index("date")
