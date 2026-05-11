"""Position sizing."""
import math
import config


def position_size(account_equity: float, entry_price: float, stop_price: float,
                  risk_pct: float = config.RISK_PCT) -> int:
    """Shares = (equity * risk_pct) / (entry - stop). Rounded down. Zero if invalid."""
    risk_per_share = entry_price - stop_price
    if risk_per_share <= 0 or account_equity <= 0:
        return 0
    raw = (account_equity * risk_pct) / risk_per_share
    return max(0, math.floor(raw))


def stop_price(entry_price: float, atr: float, mult: float = config.HARD_STOP_MULT) -> float:
    return entry_price - mult * atr


def target_price(entry_price: float, atr: float, mult: float = config.TARGET_MULT) -> float:
    return entry_price + mult * atr
