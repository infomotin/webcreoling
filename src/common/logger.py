"""
Structured Logging Module.
Provides colored console output via Rich and rotating file logs for debugging and audit trails.
"""

import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from rich.logging import RichHandler
from config.settings import settings


_LOGGERS = {}


def setup_logger(
    name: str = "webcreoling",
    log_file: Optional[Path] = None,
    level: str = "INFO",
) -> logging.Logger:
    """Configure and return a standardized logger."""
    if name in _LOGGERS:
        return _LOGGERS[name]

    logger = logging.getLogger(name)
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)
    logger.propagate = False

    # Clear existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # Rich Console Handler with UTF-8 support
    from rich.console import Console
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    safe_console = Console(force_terminal=True, legacy_windows=False)
    rich_handler = RichHandler(
        console=safe_console,
        rich_tracebacks=True,
        markup=True,
        show_time=True,
        show_path=False,
        level=log_level,
    )
    rich_format = logging.Formatter("%(message)s")
    rich_handler.setFormatter(rich_format)
    logger.addHandler(rich_handler)

    # Rotating File Handler
    if log_file is None:
        settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = settings.LOGS_DIR / "webcreoling.log"

    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB per file
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file
        file_format = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not initialize log file {log_file}: {e}", file=sys.stderr)

    _LOGGERS[name] = logger
    return logger


def get_logger(name: str = "webcreoling") -> logging.Logger:
    """Retrieve or create a logger instance."""
    if name not in _LOGGERS:
        return setup_logger(name, level=settings.LOG_LEVEL)
    return _LOGGERS[name]
