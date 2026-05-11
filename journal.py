"""CSV journal for every scan and trade action."""
import os
import csv
from datetime import datetime
import config

FIELDS = [
    "timestamp", "event", "symbol", "date",
    "seasonal_pass", "cot_pass", "trend_pass", "trigger_pass",
    "signal", "entry_price", "stop_price", "target_price",
    "shares", "atr14", "notes",
]


def _ensure_header():
    if not os.path.exists(config.JOURNAL_PATH):
        with open(config.JOURNAL_PATH, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def write(event: str, payload: dict):
    """Append a journal row. payload keys subset of FIELDS."""
    _ensure_header()
    row = {k: "" for k in FIELDS}
    row.update({k: v for k, v in payload.items() if k in FIELDS})
    row["timestamp"] = datetime.utcnow().isoformat()
    row["event"] = event
    with open(config.JOURNAL_PATH, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)
