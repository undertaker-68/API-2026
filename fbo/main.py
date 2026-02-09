from __future__ import annotations

import logging
import time
from pathlib import Path

from fbo.config import get_config
from fbo.sync.runner import run_once


def setup_logging(log_level: str, log_path: str) -> None:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(log_level)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)


def main() -> None:
    cfg = get_config()
    setup_logging(cfg.log_level, cfg.log_path)

    log = logging.getLogger("fbo.main")
    log.info("FBO sync started (poll=%ss, dry_run=%s)", cfg.poll_seconds, cfg.dry_run)

    while True:
        try:
            run_once(cfg)
        except Exception:
            log.exception("run_once failed")
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    main()
