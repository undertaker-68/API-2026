import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logging(level: str = "INFO", log_file: str = "logs/app.log") -> None:
    Path("logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    root = logging.getLogger()
    root.setLevel(level.upper())

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    fh = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)

    root.handlers.clear()
    root.addHandler(ch)
    root.addHandler(fh)
