import os
import sys

from loguru import logger

_ALLOWED_LEVELS = {
    "TRACE",
    "DEBUG",
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
}

_log_level = os.getenv("LOG_LEVEL", "INFO").upper().strip()
if _log_level not in _ALLOWED_LEVELS:
    _log_level = "INFO"

logger.remove()
logger.add(
    sys.stdout,
    level=_log_level,
    backtrace=True,
    diagnose=False,
)

__all__ = ["logger"]