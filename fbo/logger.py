import logging
from config import LOG_LEVEL

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s"
)

log = logging.getLogger("ozon_fbo")
