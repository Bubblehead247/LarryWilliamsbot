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
