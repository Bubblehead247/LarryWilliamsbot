"""signal_scan: assemble filters into a go/no-go each evening."""
import logging
from datetime import datetime

import config
import data
import filters
import risk
import execution
import journal

log = logging.getLogger(__name__)


def signal_scan(symbol: str = config.SYMBOL) -> dict:
    """Run all filters, build candidate trade, journal result, return dict."""
    today = datetime.utcnow().date()
    is_etf = symbol in config.WILLIAMS_R_PERIOD
    result = {
        "symbol": symbol,
        "date": today.isoformat(),
        "seasonal_pass": False,
        "cot_pass": False,
        "trend_pass": False,
        "trigger_pass": False,
        "signal": "FLAT",
        "entry_price": None,
        "stop_price": None,
        "target_price": None,
        "shares": None,
        "atr14": None,
    }

    try:
        price_df = data.fetch_price_history(symbol=symbol)
        cot_df = None if is_etf else data.fetch_cot()
    except Exception as e:
        log.error("Data fetch failed; skipping scan: %s", e)
        journal.write("scan_error", {**result, "notes": str(e)})
        return result

    try:
        result["seasonal_pass"] = filters.seasonal_pass(today, symbol=symbol)
        # ETFs (XLE/XLB/XLF/SPY/QQQ) have no COT report — skip that filter.
        result["cot_pass"] = True if is_etf else filters.cot_pass(cot_df)
        result["trend_pass"] = filters.trend_pass(price_df)
        result["trigger_pass"] = (
            filters.williams_r_pass(price_df, symbol) if is_etf
            else filters.trigger_pass(price_df)
        )
        atr14 = filters.compute_atr(price_df)
        result["atr14"] = round(atr14, 4)
    except Exception as e:
        log.error("Filter evaluation failed: %s", e)
        journal.write("scan_error", {**result, "notes": str(e)})
        return result

    all_pass = all([
        result["seasonal_pass"], result["cot_pass"],
        result["trend_pass"], result["trigger_pass"],
    ])

    if all_pass:
        entry = float(price_df["close"].iloc[-1])  # proxy for tomorrow's open
        if is_etf:
            stop = entry * (1.0 - config.STOP_LOSS_PCT[symbol])
        else:
            stop = risk.stop_price(entry, atr14)
        target = risk.target_price(entry, atr14)
        try:
            equity = execution.account_equity()
        except Exception as e:
            log.error("Could not read account equity: %s", e)
            equity = 0.0
        shares = risk.position_size(equity, entry, stop)
        result.update({
            "signal": "BUY" if shares > 0 else "FLAT",
            "entry_price": round(entry, 4),
            "stop_price": round(stop, 4),
            "target_price": round(target, 4),
            "shares": shares,
        })

    journal.write("scan", result)
    log.info("Scan result: %s", result)
    return result


def execute_signal(scan_result: dict):
    """If scan produced a BUY, place the bracket order."""
    if scan_result.get("signal") != "BUY":
        return None
    symbol = scan_result.get("symbol", config.SYMBOL)
    if execution.get_open_position(symbol) is not None:
        log.info("Position already open; skipping new entry")
        return None
    order = execution.submit_bracket_buy(
        symbol=symbol,
        qty=scan_result["shares"],
        entry_price=scan_result["entry_price"],
        stop_price=scan_result["stop_price"],
        target_price=scan_result["target_price"],
    )
    journal.write("entry_submitted", scan_result)
    return order
