"""LWbot Streamlit dashboard.

Run: streamlit run dashboard.py --server.port 8502
"""
from datetime import datetime, date, timedelta
import os
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from ta.trend import EMAIndicator
from ta.momentum import WilliamsRIndicator

import config
import data as datamod
import filters as filt
import execution

ALL_SYMBOLS = [config.SYMBOL, *config.SEASONAL_WINDOWS_BY_SYMBOL.keys()]

st.set_page_config(page_title="LWbot", layout="wide")

# ---------- sidebar: symbol picker ----------
symbol = st.sidebar.selectbox("Symbol", ALL_SYMBOLS, index=0)
IS_ETF = symbol in config.WILLIAMS_R_PERIOD

st.title(f"LWbot — Larry Williams Swing Bot · {symbol}")
strategy_label = (
    f"4-filter swing (Williams %R trigger, {config.STOP_LOSS_PCT[symbol]*100:.1f}% stop)"
    if IS_ETF else
    "4-filter swing (Williams exhaustion + COT, ATR stop)"
)
st.caption(f"{strategy_label} · paper={config.PAPER_TRADING} · refresh page to update")


# ---------- helpers ----------
@st.cache_data(ttl=60)
def load_journal() -> pd.DataFrame:
    if not os.path.exists(config.JOURNAL_PATH):
        return pd.DataFrame()
    df = pd.read_csv(config.JOURNAL_PATH)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@st.cache_data(ttl=300)
def load_prices(sym: str):
    return datamod.fetch_price_history(symbol=sym, lookback_days=400)


@st.cache_data(ttl=900)
def load_cot():
    return datamod.fetch_cot()


def account_snapshot():
    try:
        acct = execution.get_client().get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
        }
    except Exception as e:
        return {"error": str(e)}


def position_snapshot(sym: str):
    try:
        pos = execution.get_open_position(sym)
        if pos is None:
            return None
        return {
            "qty": int(float(pos.qty)),
            "avg_entry": float(pos.avg_entry_price),
            "current_price": float(pos.current_price),
            "unrealized_pl": float(pos.unrealized_pl),
            "unrealized_plpc": float(pos.unrealized_plpc),
            "market_value": float(pos.market_value),
            "side": str(pos.side),
        }
    except Exception as e:
        return {"error": str(e)}


def _format_window(start: str, end: str) -> str:
    return f"{start} → {end}"


# ---------- load data ----------
journal = load_journal()
journal_sym = journal[journal.get("symbol") == symbol] if not journal.empty else journal
acct = account_snapshot()
pos = position_snapshot(symbol)


# ---------- ROW 1: system health ----------
c1, c2, c3, c4 = st.columns(4)

last_scan = journal_sym[journal_sym["event"] == "scan"].tail(1) if not journal_sym.empty else pd.DataFrame()

with c1:
    if not last_scan.empty:
        ts = last_scan.iloc[0]["timestamp"]
        st.metric(f"Last {symbol} Scan (UTC)", ts.strftime("%m-%d %H:%M"),
                  last_scan.iloc[0]["signal"])
    else:
        st.metric(f"Last {symbol} Scan", "—")

with c2:
    if "error" in acct:
        st.metric("Account Equity", "ERR")
        st.caption(acct["error"][:80])
    else:
        st.metric("Account Equity", f"${acct['equity']:,.2f}")
        st.caption(f"cash ${acct['cash']:,.0f} · BP ${acct['buying_power']:,.0f}")

with c3:
    if pos is None:
        st.metric(f"{symbol} Position", "FLAT")
    elif "error" in pos:
        st.metric(f"{symbol} Position", "ERR")
    else:
        st.metric(f"{symbol} Position",
                  f"{pos['qty']} @ ${pos['avg_entry']:.2f}",
                  f"{pos['unrealized_plpc']*100:+.2f}%")

with c4:
    err_rows = journal_sym[journal_sym["event"] == "scan_error"].tail(5) if not journal_sym.empty else pd.DataFrame()
    st.metric(f"{symbol} Errors (last 5)", len(err_rows))


st.divider()

# ---------- ROW 2: today's filters ----------
st.subheader(f"Today's {symbol} signal")

prices = None
cot = None
atr14 = None
try:
    prices = load_prices(symbol)
    today = datetime.utcnow().date()

    seasonal_ok = filt.seasonal_pass(today, symbol=symbol)

    if IS_ETF:
        cot_val = None
        cot_ok = True  # auto-pass for ETFs
    else:
        cot = load_cot()
        cot_val = filt.cot_index(cot)
        cot_ok = cot_val > config.COT_THRESHOLD

    trend_ok = filt.trend_pass(prices)

    if IS_ETF:
        wr_period = config.WILLIAMS_R_PERIOD[symbol]
        wr_val = filt.williams_r(prices, wr_period)
        trigger_ok = wr_val < -80.0
    else:
        wr_val = None
        trigger_ok = filt.trigger_pass(prices)

    atr14 = filt.compute_atr(prices)
    close = float(prices["close"].iloc[-1])
    ema50 = EMAIndicator(close=prices["close"], window=config.EMA_PERIOD).ema_indicator().iloc[-1]

    f1, f2, f3, f4 = st.columns(4)
    def badge(ok): return "PASS" if ok else "FAIL"

    with f1:
        st.metric("Seasonal", badge(seasonal_ok), help="In one of the bullish windows?")
        if IS_ETF:
            for s, e in config.SEASONAL_WINDOWS_BY_SYMBOL[symbol]:
                st.caption(_format_window(s, e))
        else:
            for (sm, sd), (em, ed) in config.SEASONAL_WINDOWS:
                st.caption(f"{sm:02d}-{sd:02d} → {em:02d}-{ed:02d}")
    with f2:
        if IS_ETF:
            st.metric("COT", "n/a", "ETF — auto-pass")
        else:
            st.metric("COT Index", badge(cot_ok), f"{cot_val:.1f} / threshold {config.COT_THRESHOLD}")
    with f3:
        st.metric("Trend (50-EMA)", badge(trend_ok),
                  f"close ${close:.2f} vs EMA ${ema50:.2f}")
    with f4:
        if IS_ETF:
            st.metric(f"Williams %R({wr_period})", badge(trigger_ok),
                      f"{wr_val:.1f} < -80?")
        else:
            y_low, t_low = prices["low"].iloc[-2], prices["low"].iloc[-1]
            y_close, t_close = prices["close"].iloc[-2], prices["close"].iloc[-1]
            st.metric("Trigger (Williams)", badge(trigger_ok),
                      f"lo {t_low:.2f}<{y_low:.2f}? cl {t_close:.2f}>{y_close:.2f}?")

    # Proposed trade
    if all([seasonal_ok, cot_ok, trend_ok, trigger_ok]):
        if IS_ETF:
            stop = close * (1.0 - config.STOP_LOSS_PCT[symbol])
        else:
            stop = close - 2 * atr14
        target = close + 3 * atr14
        st.success(f"All filters PASS — proposed BUY: entry ${close:.2f}, "
                   f"stop ${stop:.2f}, target ${target:.2f}, ATR14 {atr14:.2f}")
    else:
        st.info(f"Signal: FLAT · ATR14 {atr14:.2f}")
except Exception as e:
    st.error(f"Filter evaluation failed: {e}")


st.divider()

# ---------- ROW 3: charts ----------
left, right = st.columns(2)

with left:
    st.subheader(f"{symbol} price + 50-EMA")
    if prices is not None:
        ema = EMAIndicator(close=prices["close"], window=config.EMA_PERIOD).ema_indicator()
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=prices.index, open=prices["open"], high=prices["high"],
            low=prices["low"], close=prices["close"], name=symbol,
        ))
        fig.add_trace(go.Scatter(x=prices.index, y=ema, name="50-EMA",
                                 line=dict(color="orange", width=2)))
        fig.update_layout(height=400, xaxis_rangeslider_visible=False,
                          margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

with right:
    if IS_ETF and prices is not None:
        wr_period = config.WILLIAMS_R_PERIOD[symbol]
        st.subheader(f"Williams %R({wr_period})")
        wr_series = WilliamsRIndicator(
            high=prices["high"], low=prices["low"], close=prices["close"], lbp=wr_period,
        ).williams_r()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=wr_series.index, y=wr_series, name=f"%R({wr_period})"))
        fig.add_hline(y=-80, line_dash="dash", line_color="green",
                      annotation_text="oversold (-80)")
        fig.add_hline(y=-20, line_dash="dash", line_color="red",
                      annotation_text="overbought (-20)")
        fig.update_layout(height=400, yaxis_range=[-100, 0],
                          margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)
    elif cot is not None:
        st.subheader("COT Commercial Index (52w percentile)")
        net = cot["net"].dropna()
        pct = net.rolling(config.COT_LOOKBACK_WEEKS).apply(
            lambda w: (w <= w.iloc[-1]).sum() / len(w) * 100.0, raw=False
        )
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=pct.index, y=pct, name="COT Index"))
        fig.add_hline(y=config.COT_THRESHOLD, line_dash="dash", line_color="red",
                      annotation_text=f"threshold {config.COT_THRESHOLD}")
        fig.update_layout(height=400, yaxis_range=[0, 100],
                          margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)


st.divider()

# ---------- ROW 4: filter timeline + journal ----------
st.subheader(f"{symbol} filter pass/fail timeline (from journal)")
if not journal_sym.empty:
    scans = journal_sym[journal_sym["event"] == "scan"].copy()
    if not scans.empty:
        scans["date"] = pd.to_datetime(scans["date"])
        scans = scans.sort_values("date").tail(60)
        cats = ["seasonal_pass", "cot_pass", "trend_pass", "trigger_pass"]
        fig = go.Figure()
        for i, c in enumerate(cats):
            vals = scans[c].astype(str).map({"True": 1, "False": 0}).fillna(0)
            fig.add_trace(go.Scatter(
                x=scans["date"], y=[i] * len(scans),
                mode="markers", name=c.replace("_pass", ""),
                marker=dict(size=12,
                            color=["#2ecc71" if v == 1 else "#e74c3c" for v in vals]),
            ))
        fig.update_layout(
            height=220,
            yaxis=dict(tickvals=list(range(len(cats))),
                       ticktext=[c.replace("_pass", "") for c in cats]),
            margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"No scan entries for {symbol} yet")
else:
    st.info("No journal entries yet")

st.subheader(f"Recent {symbol} journal entries")
if not journal_sym.empty:
    st.dataframe(
        journal_sym.sort_values("timestamp", ascending=False).head(25),
        use_container_width=True, hide_index=True,
    )

st.divider()

# ---------- ROW 5: seasonal strip + schedule ----------
left2, right2 = st.columns([3, 1])


def _windows_to_segments(symbol: str, year: int) -> list[dict]:
    """Return [{Window, Start, End}, ...]; splits year-wrapping windows into two segments."""
    rows = []
    if symbol in config.SEASONAL_WINDOWS_BY_SYMBOL:
        for start, end in config.SEASONAL_WINDOWS_BY_SYMBOL[symbol]:
            sm, sd = map(int, start.split("-"))
            em, ed = map(int, end.split("-"))
            label = f"{start} → {end}"
            ed = min(ed, 28) if em == 2 else ed
            if (sm, sd) <= (em, ed):
                rows.append(dict(Window=label,
                                 Start=date(year, sm, sd),
                                 End=date(year, em, ed)))
            else:
                # year-wrap: Jan 1..end + start..Dec 31
                rows.append(dict(Window=label + " (wrap a)",
                                 Start=date(year, 1, 1),
                                 End=date(year, em, ed)))
                rows.append(dict(Window=label + " (wrap b)",
                                 Start=date(year, sm, sd),
                                 End=date(year, 12, 31)))
    else:
        for (sm, sd), (em, ed) in config.SEASONAL_WINDOWS:
            rows.append(dict(Window=f"{sm:02d}-{sd:02d} to {em:02d}-{ed:02d}",
                             Start=date(year, sm, sd),
                             End=date(year, em, min(ed, 28))))
    return rows


with left2:
    st.subheader(f"{symbol} seasonal windows (current year)")
    today = date.today()
    sdf = pd.DataFrame(_windows_to_segments(symbol, today.year))
    fig = go.Figure()
    for _, r in sdf.iterrows():
        fig.add_trace(go.Bar(
            x=[(r["End"] - r["Start"]).days], y=["Bullish"],
            base=[r["Start"]], orientation="h", name=r["Window"], showlegend=False,
        ))
    today_ts = pd.Timestamp(today)
    fig.add_shape(type="line", x0=today_ts, x1=today_ts, y0=-0.5, y1=0.5,
                  line=dict(color="black", width=2))
    fig.add_annotation(x=today_ts, y=0.5, text=f"today {today.isoformat()}",
                       showarrow=False, yshift=10)
    fig.update_xaxes(type="date",
                     range=[pd.Timestamp(today.year, 1, 1),
                            pd.Timestamp(today.year, 12, 31)])
    fig.update_layout(height=120, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

with right2:
    st.subheader("Schedule")
    st.write("**Monitor**: weekdays 08:31 CT")
    st.write("**Scan**: weekdays 15:15 CT")
    st.caption("Each job loops over all symbols")

st.divider()
st.caption(f"Journal: `{os.path.basename(config.JOURNAL_PATH)}` · "
           f"Log: `{os.path.basename(config.LOG_PATH)}` · "
           f"COT cache: `{os.path.basename(config.COT_CACHE_PATH)}`")
