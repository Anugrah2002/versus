"""
Structured logger for Versus Backend with timestamps and encoding safety across all platforms.
"""

import sys
import logging
from typing import Optional

# Ensure standard output uses utf-8 on Windows
if sys.platform.startswith("win") and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class SafeStreamHandler(logging.StreamHandler):
    """A stream handler that safely encodes special unicode characters on legacy Windows terminals."""
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                safe_msg = msg.encode("ascii", "replace").decode("ascii")
                stream.write(safe_msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logger(name: str = "versus", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = SafeStreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


logger = setup_logger("versus-engine")
