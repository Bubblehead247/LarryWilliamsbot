# Larry Williams Swing Bot

A modular swing-trading bot using a Larry Williams-inspired multi-filter setup.
Trades GLD plus the sector/index ETFs **XLE, XLB, XLF, SPY, QQQ** through Alpaca
(paper by default).

## Setup

```bash
cd LarryWilliamsbot
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then edit .env with your Alpaca paper keys
```

## Run

```bash
python main.py              # start scheduler (runs forever)
python main.py scan         # one-off evening signal scan (all symbols)
python main.py monitor      # one-off morning position check (all symbols)
```

`main.py` schedules two jobs (America/New_York). Each loops over the full symbol
list — GLD plus every key in `SEASONAL_WINDOWS_BY_SYMBOL` — with per-symbol
error isolation:

| Time     | Job                  |
|----------|----------------------|
| 09:31 ET | `position_monitor()` |
| 16:15 ET | `signal_scan()`      |

## Strategy

A BUY requires **all four** filters to pass. Two filter variants run depending
on the symbol:

| # | Filter        | GLD                                        | ETFs (XLE/XLB/XLF/SPY/QQQ)                     |
|---|---------------|--------------------------------------------|------------------------------------------------|
| 1 | Seasonal Gate | `SEASONAL_WINDOWS` (Jul–Aug, Nov–Feb)      | `SEASONAL_WINDOWS_BY_SYMBOL[symbol]`           |
| 2 | Sentiment     | COT Commercial Index > 70 (52-wk pct)      | *auto-pass — no COT report for sector ETFs*    |
| 3 | Trend         | Close > 50-EMA                             | Close > 50-EMA                                 |
| 4 | Entry Trigger | Williams exhaustion (low<prev, close>prev) | Williams %R(`WILLIAMS_R_PERIOD[symbol]`) < −80 |

When all pass, a bracket BUY is submitted:

- **Hard stop**
  - GLD: `entry − 2 × ATR(14)`
  - ETFs: `entry × (1 − STOP_LOSS_PCT[symbol])` (3.5–6% by symbol)
- **Target**: `entry + 3 × ATR(14)`
- **Size**: `(equity × 2%) / (entry − stop)`, rounded down

### Per-symbol tables (`config.py`)

```python
SEASONAL_WINDOWS_BY_SYMBOL = {
    "XLE": [("02-20", "05-25"), ("09-15", "10-15")],
    "XLB": [("01-25", "04-25"), ("10-25", "11-25")],
    "XLF": [("01-01", "02-15"), ("10-15", "12-31")],
    "SPY": [("11-01", "04-30"), ("09-25", "10-15"), ("12-15", "01-05")],
    "QQQ": [("11-01", "04-30"), ("01-15", "02-28"), ("09-25", "10-15")],
}
WILLIAMS_R_PERIOD = {"XLE": 14, "XLB": 14, "XLF": 10, "SPY": 14, "QQQ": 10}
STOP_LOSS_PCT     = {"XLE": 0.04, "XLB": 0.04, "XLF": 0.035, "SPY": 0.04, "QQQ": 0.06}
```

Year-wrap windows like `("12-15", "01-05")` are handled automatically.

### Exits (priority order in `position_monitor`)

Runs independently for every symbol with an open Alpaca position:

1. **Bailout** — if next open > entry, close at market (checked first every morning).
2. **Time stop** — exit at next open after 10 calendar days.
3. **Seasonal close** — exit if date falls outside that symbol's bullish window.
4. **Breakeven trail** — once close ≥ entry + 1×ATR, move stop to entry.
5. **Hard stop / target** — handled by the original bracket order at Alpaca.

## Modules

| File          | Role                                                            |
|---------------|-----------------------------------------------------------------|
| `config.py`   | All tunables + env-loaded Alpaca creds                          |
| `data.py`     | Price (yfinance, symbol-aware) and COT fetchers                 |
| `filters.py`  | Each filter as a pure function; ATR + Williams %R helpers       |
| `signals.py`  | `signal_scan(symbol)` assembles filters + sizes the trade       |
| `position.py` | `position_monitor(symbol)` exits in priority order each morning |
| `execution.py`| Thin Alpaca wrapper (bracket buy, close, stop replace)          |
| `risk.py`     | Position sizing and stop/target math                            |
| `journal.py`  | Append every scan + action to `journal.csv`                     |
| `main.py`     | APScheduler entry point; loops over all symbols                 |

## Files written at runtime

- `lwbot_journal.csv` — every scan + trade action with full filter state
- `lwbot_cot_cache.csv` — weekly COT data, refreshed Fridays
- `lwbot_bot.log` — INFO-level runtime log

## Safety notes

- `config.PAPER_TRADING = True` by default. Do not flip until backtested.
- If any data fetch fails, the scan logs the error and exits — never trades on
  incomplete data.
- Per-symbol scan/monitor errors are isolated: one ticker failing won't skip
  the others.
- COT is weekly (Friday release); cache invalidates on the next Friday only.
- All entries use Alpaca **bracket** orders so a stop/target are live the moment
  the parent fills.

## Dashboard

A Streamlit dashboard visualizes recent signals, COT data, and price history:

```bash
streamlit run dashboard.py --server.port 8502
```

Opens at `http://localhost:8502`. Reads from `lwbot_journal.csv`, live yfinance
prices, and the cached COT. Refresh the page to update (cached: 60s journal,
5min prices, 15min COT).

> Note: the dashboard currently focuses on GLD. Extending it to render the new
> ETF symbols is on the TODO list.

## Windows Task Scheduler (.bat files)

Two wrappers are provided to run the bot from Windows Task Scheduler without
keeping `main.py` alive as a long-running process:

| File              | Equivalent to            | Schedule suggestion       |
|-------------------|--------------------------|---------------------------|
| `run_scan.bat`    | `python main.py scan`    | Daily 16:15 ET, Mon–Fri   |
| `run_monitor.bat` | `python main.py monitor` | Daily 09:31 ET, Mon–Fri   |

Both `cd` into the project directory and append stderr to `task_stderr.log`.
Edit the hardcoded `C:\Python314\python.exe` path to match your install.

## Adding a new ticker

Three dicts in `config.py` are the only thing to edit — the scan loop picks up
new symbols automatically from `SEASONAL_WINDOWS_BY_SYMBOL.keys()`:

```python
SEASONAL_WINDOWS_BY_SYMBOL["XLK"] = [("11-01", "04-30"), ("09-25", "10-15")]
WILLIAMS_R_PERIOD["XLK"] = 14
STOP_LOSS_PCT["XLK"]     = 0.05
```

That's it. Next `python main.py scan` will include the new symbol with COT
auto-passing and Williams %R as the trigger. To add a *non-ETF* with COT data
(like another futures-backed product), you'd need a new entry in `data.py`
analogous to `COT_GOLD_CODE` plus branching in `signal_scan`.

## Journal schema

`lwbot_journal.csv` columns (one row per scan or trade action):

| Column         | Description                                          |
|----------------|------------------------------------------------------|
| `timestamp`    | UTC ISO 8601 — when the row was written              |
| `event`        | `scan`, `scan_error`, `entry_submitted`, `bailout_exit`, `time_stop`, `seasonal_close`, `stop_to_breakeven` |
| `symbol`       | Ticker scanned                                       |
| `date`         | Trading date (UTC)                                   |
| `seasonal_pass`, `cot_pass`, `trend_pass`, `trigger_pass` | Boolean filter outcomes |
| `signal`       | `BUY` or `FLAT`                                      |
| `entry_price`, `stop_price`, `target_price` | Trade prices when signal=BUY    |
| `shares`       | Sized position                                       |
| `atr14`        | ATR(14) at scan time                                 |
| `notes`        | Free-form (error messages, exit reasons)             |

Load in pandas: `pd.read_csv("lwbot_journal.csv", parse_dates=["timestamp"])`.

## Backtesting

**There is no backtest harness in this repo.** Paper-trade first. The filter
functions in `filters.py` are pure (take a `price_df`, return bool) and can be
driven by historical bars to roll a backtest yourself, but that scaffolding
isn't included.

## Requirements

- **Python 3.10+** (uses `date | None` union syntax)
- Key dependencies (full list in `requirements.txt`):
  - `alpaca-py` — broker integration
  - `yfinance` — daily OHLCV
  - `ta` — EMA, ATR, Williams %R
  - `apscheduler` — cron scheduling
  - `cot-reports` — CFTC COT (with direct-CFTC fallback in `data.py`)
  - `streamlit`, `plotly` — dashboard
  - `python-dotenv` — `.env` loader

## Troubleshooting

| Symptom                                                     | Likely cause / fix                                                              |
|-------------------------------------------------------------|---------------------------------------------------------------------------------|
| `No price data returned for <SYMBOL>`                       | Weekend or market holiday — yfinance returns empty. Retry after the next close. |
| `Insufficient price history for EMA/ATR/Williams %R`        | Lookback too short (default 400d). Bump `lookback_days` in `data.py`.            |
| yfinance returns MultiIndex columns and filters fail        | Handled by `data.py:21–22`. If it regresses, check yfinance version.            |
| Alpaca 401 / `account_equity` error                         | Bad keys or hitting live URL with paper keys. Verify `.env` and `PAPER_TRADING`. |
| COT cache looks stale                                       | Cache refreshes Fridays. Force reload: `data.fetch_cot(force=True)`.            |
| `signal_scan('XLK')` KeyError on stop                       | Symbol not in `STOP_LOSS_PCT`. Add it to all three config dicts (see above).    |

## License & disclaimer

**No license file is included** — treat as proprietary/unlicensed until you
add one.

This software is provided **as-is for educational purposes only**. It is not
financial advice. Trading involves substantial risk of loss. The author(s)
make no warranty about correctness, profitability, or suitability for any
purpose. **You are solely responsible** for any orders this bot submits,
paper or live. Backtest, paper-trade, and review the code before flipping
`PAPER_TRADING = False`.
