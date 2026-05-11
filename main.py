"""Scheduler entry point.

- position_monitor() at 9:31 AM ET (1 min after open)
- signal_scan()    at 4:15 PM ET (after close); auto-executes BUY signals
"""
import logging
import sys
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from signals import signal_scan, execute_signal
from position import position_monitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("main")


def morning_job():
    log.info("=== Morning position_monitor ===")
    symbols = [config.SYMBOL, *config.SEASONAL_WINDOWS_BY_SYMBOL.keys()]
    for symbol in symbols:
        try:
            position_monitor(symbol)
        except Exception as e:
            log.exception("position_monitor crashed for %s: %s", symbol, e)


def evening_job():
    log.info("=== Evening signal_scan ===")
    symbols = [config.SYMBOL, *config.SEASONAL_WINDOWS_BY_SYMBOL.keys()]
    for symbol in symbols:
        log.info("--- Scanning %s ---", symbol)
        try:
            result = signal_scan(symbol)
            execute_signal(result)
        except Exception as e:
            log.exception("signal_scan crashed for %s: %s", symbol, e)


def main():
    log.info("Starting GLD bot (paper=%s)", config.PAPER_TRADING)
    sched = BlockingScheduler(timezone="America/New_York")
    sched.add_job(morning_job, CronTrigger(hour=9, minute=31, day_of_week="mon-fri"))
    sched.add_job(evening_job, CronTrigger(hour=16, minute=15, day_of_week="mon-fri"))
    log.info("Scheduler armed. Ctrl+C to quit.")
    sched.start()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        evening_job()
    elif len(sys.argv) > 1 and sys.argv[1] == "monitor":
        morning_job()
    else:
        main()
