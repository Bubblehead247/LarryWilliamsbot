"""Alpaca order placement and position management."""
import logging
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, StopOrderRequest,
    TakeProfitRequest, StopLossRequest, GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus

import config

log = logging.getLogger(__name__)


def get_client() -> TradingClient:
    return TradingClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
        paper=config.PAPER_TRADING,
    )


def account_equity() -> float:
    return float(get_client().get_account().equity)


def get_open_position(symbol: str = config.SYMBOL):
    try:
        return get_client().get_open_position(symbol)
    except Exception:
        return None


def submit_bracket_buy(symbol: str, qty: int, entry_price: float,
                       stop_price: float, target_price: float):
    """Submit a bracket buy: market entry, take-profit limit, stop-loss."""
    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=round(target_price, 2)),
        stop_loss=StopLossRequest(stop_price=round(stop_price, 2)),
    )
    order = get_client().submit_order(req)
    log.info("Submitted bracket BUY: %s qty=%d stop=%.2f tp=%.2f",
             symbol, qty, stop_price, target_price)
    return order


def submit_market_sell(symbol: str, qty: int):
    req = MarketOrderRequest(
        symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
    )
    order = get_client().submit_order(req)
    log.info("Submitted market SELL: %s qty=%d", symbol, qty)
    return order


def close_position(symbol: str = config.SYMBOL):
    try:
        get_client().close_position(symbol)
        log.info("Closed position %s", symbol)
    except Exception as e:
        log.error("close_position failed: %s", e)


def update_stop_to_breakeven(symbol: str, entry_price: float):
    """Cancel existing stop order and replace at entry price (breakeven)."""
    client = get_client()
    orders = client.get_orders(
        filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
    )
    for o in orders:
        if o.order_type == "stop" or (o.stop_price is not None):
            client.cancel_order_by_id(o.id)
            log.info("Cancelled prior stop %s", o.id)
    pos = get_open_position(symbol)
    if pos is None:
        return
    req = StopOrderRequest(
        symbol=symbol,
        qty=int(pos.qty),
        side=OrderSide.SELL,
        time_in_force=TimeInForce.GTC,
        stop_price=round(entry_price, 2),
    )
    client.submit_order(req)
    log.info("Stop moved to breakeven @ %.2f", entry_price)
