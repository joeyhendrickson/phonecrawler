from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path

import structlog

_LOG_FILE: Path | None = None
progress_callback: ContextVar[Callable[[str, str], None] | None] = ContextVar(
    "progress_callback", default=None
)


def setup_logging(*, debug: bool = False, log_file: Path | None = None) -> None:
    """JSON structured logs to file; tagged progress lines go to stdout via announce()."""
    global _LOG_FILE
    _LOG_FILE = log_file
    level = logging.DEBUG if debug else logging.INFO
    handlers: list[logging.Handler] = []
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        handlers.append(file_handler)
    if debug or log_file is None:
        handlers.append(logging.StreamHandler(sys.stderr))
    if not handlers:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(level=level, handlers=handlers, format="%(message)s", force=True)

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if debug:
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def announce(tag: str, message: str) -> None:
    """Operator-facing progress line: [CRAWL] 12/40 https://example.edu/admissions"""
    line = f"[{tag}] {message}"
    print(line, flush=True)
    if _LOG_FILE is not None:
        with _LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    callback = progress_callback.get()
    if callback is not None:
        callback(tag, message)
