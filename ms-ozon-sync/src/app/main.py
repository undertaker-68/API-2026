import argparse
import logging
import time
from dotenv import load_dotenv

from app.logging_setup import setup_logging
from app.config import load_config
from app.state_store import StateStore
from app.ozon_client import OzonClient
from app.ms_client import MSClient
from app.sync_orders import run_once

log = logging.getLogger("main")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--since", default="2026-01-28")
    return p.parse_args()


def main():
    load_dotenv()
    args = parse_args()

    cfg = load_config()
    setup_logging(level=__import__("os").environ.get("LOG_LEVEL", "INFO"), log_file="logs/app.log")

    store = StateStore()
    ozon = OzonClient(cfg)
    ms = MSClient(cfg)

    log.info("start dry_run=%s poll_seconds=%s", cfg.dry_run, cfg.poll_seconds)

    if args.once:
        run_once(cfg, store, ozon, ms, since_date=args.since)
        return

    while True:
        try:
            run_once(cfg, store, ozon, ms, since_date=args.since)
        except Exception as e:
            log.exception("sync loop error: %s", e)
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    main()
