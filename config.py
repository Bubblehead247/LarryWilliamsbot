"""Configuration constants for the GLD swing trading bot."""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Trading universe ---
SYMBOL = "GLD"
COT_GOLD_CODE = "088691"  # CFTC code for COMEX Gold

# --- Risk parameters ---
RISK_PCT = 0.02
ATR_PERIOD = 14
HARD_STOP_MULT = 2.0
TARGET_MULT = 3.0
BREAKEVEN_MULT = 1.0

# --- Filter parameters ---
COT_THRESHOLD = 70
COT_LOOKBACK_WEEKS = 52
EMA_PERIOD = 50

# --- Exit parameters ---
TIME_STOP_DAYS = 10

# --- Seasonal windows (month, day) inclusive ranges considered bullish for GLD ---
# Late July – early August, and November – February
SEASONAL_WINDOWS = [
    ((7, 20), (8, 10)),
    ((11, 1), (12, 31)),
    ((1, 1), (2, 28)),
]

# --- Additional tickers: per-symbol seasonal windows ("MM-DD" ranges) ---
SEASONAL_WINDOWS_BY_SYMBOL = {
    "XLE": [("02-20", "05-25"), ("09-15", "10-15")],
    "XLB": [("01-25", "04-25"), ("10-25", "11-25")],
    "XLF": [("01-01", "02-15"), ("10-15", "12-31")],
    "SPY": [("11-01", "04-30"), ("09-25", "10-15"), ("12-15", "01-05")],
    "QQQ": [("11-01", "04-30"), ("01-15", "02-28"), ("09-25", "10-15")],
}

WILLIAMS_R_PERIOD = {
    "XLE": 14, "XLB": 14, "XLF": 10, "SPY": 14, "QQQ": 10,
}

STOP_LOSS_PCT = {
    "XLE": 0.04, "XLB": 0.04, "XLF": 0.035, "SPY": 0.04, "QQQ": 0.06,
}

# --- Mode ---
PAPER_TRADING = True

# --- Alpaca creds ---
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv(
    "ALPACA_BASE_URL",
    "https://paper-api.alpaca.markets" if PAPER_TRADING else "https://api.alpaca.markets",
)

# --- Paths ---
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
JOURNAL_PATH = os.path.join(PROJECT_DIR, "lwbot_journal.csv")
COT_CACHE_PATH = os.path.join(PROJECT_DIR, "lwbot_cot_cache.csv")
LOG_PATH = os.path.join(PROJECT_DIR, "lwbot_bot.log")
DASHBOARD_TITLE = "LWbot — Larry Williams GLD Swing Bot"
