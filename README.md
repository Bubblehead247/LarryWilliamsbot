# GLD Larry Williams Swing Bot

A modular swing-trading bot for SPDR Gold Shares (GLD) using a Larry Williams-inspired
multi-filter setup. Trades through Alpaca (paper by default).

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
python main.py scan         # one-off evening signal scan
python main.py monitor      # one-off morning position check
```

`main.py` schedules two jobs (America/New_York):

| Time     | Job                  |
|----------|----------------------|
| 09:31 ET | `position_monitor()` |
| 16:15 ET | `signal_scan()`      |

## Strategy

A BUY requires **all four** filters to pass:

1. **Seasonal Gate** — date inside one of the configured bullish windows
   (late Jul–early Aug, Nov–Feb).
2. **COT Commercial Index** — 52-week percentile of Net Commercial position > 70.
3. **Trend Filter** — close above 50-EMA.
4. **Entry Trigger** — Williams exhaustion: today's low < yesterday's low AND
   today's close > yesterday's close.

When all pass, a bracket BUY is submitted:

- Hard stop: `entry − 2 × ATR(14)`
- Target:    `entry + 3 × ATR(14)`
- Size:      `(equity × 2%) / (entry − stop)`, rounded down

### Exits (priority order in `position_monitor`)

1. **Bailout** — if next open > entry, close at market (checked first every morning).
2. **Time stop** — exit at next open after 10 calendar days.
3. **Seasonal close** — exit if date falls outside bullish window.
4. **Breakeven trail** — once close ≥ entry + 1×ATR, move stop to entry.
5. **Hard stop / target** — handled by the original bracket order at Alpaca.

## Modules

| File         | Role                                                            |
|--------------|-----------------------------------------------------------------|
| `config.py`  | All tunables + env-loaded Alpaca creds                          |
| `data.py`    | Price (yfinance) and COT (cftc-cot / direct CFTC) fetchers      |
| `filters.py` | Each filter as a pure function; ATR helper                      |
| `signals.py` | `signal_scan()` assembles filters + sizes the trade             |
| `position.py`| `position_monitor()` exits in priority order each morning       |
| `execution.py`| Thin Alpaca wrapper (bracket buy, close, stop replace)         |
| `risk.py`    | Position sizing and stop/target math                            |
| `journal.py` | Append every scan + action to `journal.csv`                     |
| `main.py`    | APScheduler entry point                                         |

## Files written at runtime

- `journal.csv` — every scan + trade action with full filter state
- `cot_cache.csv` — weekly COT data, refreshed Fridays
- `bot.log` — INFO-level runtime log

## Safety notes

- `config.PAPER_TRADING = True` by default. Do not flip until backtested.
- If any data fetch fails, the scan logs the error and exits — never trades on
  incomplete data.
- COT is weekly (Friday release); cache invalidates on the next Friday only.
- All entries use Alpaca **bracket** orders so a stop/target are live the moment
  the parent fills.
