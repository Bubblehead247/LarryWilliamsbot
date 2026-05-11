"""position_monitor: morning checks on open trades."""
import logging
from datetime import datetime, timezone

import config
import data
import filters
import execution
import journal

log = logging.getLogger(__name__)


def position_monitor(symbol: str = config.SYMBOL) -> dict:
    """Run at market open. Check exits in priority order: bailout, time-stop, seasonal,
    breakeven trail. Returns a status dict."""
    today = datetime.utcnow().date()
    status = {"symbol": symbol, "date": today.isoformat(), "action": "none"}

    pos = execution.get_open_position(symbol)
    if pos is None:
        log.info("[%s] No open position", symbol)
        return status

    entry_price = float(pos.avg_entry_price)
    qty = int(float(pos.qty))
    entry_time = getattr(pos, "created_at", None)
    if isinstance(entry_time, str):
        try:
            entry_time = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
        except Exception:
            entry_time = None

    try:
        price_df = data.fetch_price_history(symbol=symbol, lookback_days=60)
    except Exception as e:
        log.error("[%s] Price fetch failed in monitor: %s", symbol, e)
        return status

    today_open = float(price_df["open"].iloc[-1])
    today_close = float(price_df["close"].iloc[-1])

    # --- Priority 1: Bailout exit (first open after entry is profitable) ---
    if today_open > entry_price:
        log.info("[%s] Bailout: today open %.2f > entry %.2f — closing", symbol, today_open, entry_price)
        execution.close_position(symbol)
        status["action"] = "bailout_exit"
        journal.write("bailout_exit", {
            "symbol": symbol, "date": today.isoformat(),
            "entry_price": entry_price, "notes": f"open={today_open}",
        })
        return status

    # --- Priority 2: Time stop ---
    if entry_time is not None:
        days_held = (datetime.now(timezone.utc) - entry_time).days
        if days_held >= config.TIME_STOP_DAYS:
            log.info("[%s] Time stop triggered: held %d days", symbol, days_held)
            execution.close_position(symbol)
            status["action"] = "time_stop"
            journal.write("time_stop", {
                "symbol": symbol, "date": today.isoformat(),
                "notes": f"held_days={days_held}",
            })
            return status

    # --- Priority 3: Seasonal close (out of bullish window) ---
    if not filters.seasonal_pass(today, symbol=symbol):
        log.info("[%s] Seasonal close triggered", symbol)
        execution.close_position(symbol)
        status["action"] = "seasonal_close"
        journal.write("seasonal_close", {
            "symbol": symbol, "date": today.isoformat(),
        })
        return status

    # --- Priority 4: Breakeven trail ---
    try:
        atr14 = filters.compute_atr(price_df)
    except Exception:
        atr14 = None
    if atr14 and today_close >= entry_price + config.BREAKEVEN_MULT * atr14:
        log.info("[%s] Breakeven trail: moving stop to entry %.2f", symbol, entry_price)
        try:
            execution.update_stop_to_breakeven(symbol, entry_price)
            status["action"] = "stop_to_breakeven"
            journal.write("stop_to_breakeven", {
                "symbol": symbol, "date": today.isoformat(),
                "entry_price": entry_price, "stop_price": entry_price, "atr14": atr14,
            })
        except Exception as e:
            log.error("[%s] Breakeven trail failed: %s", symbol, e)

    return status
