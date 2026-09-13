"""Logging configuration — structured, rotating, module + audit channels."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, cast

import structlog

_CONFIGURED = False
_AUDIT_LOGGER_NAME = "sage.audit"


def setup_logging(
    *,
    level: str = "INFO",
    log_format: str = "console",
    log_dir: Path | str | None = None,
    session_id: str | None = None,
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> None:
    """Configure process-wide structured logging with optional rotating files."""
    global _CONFIGURED

    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.setLevel(log_level)
    root.addHandler(console)

    if log_dir is not None:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)

        # Main rotating application log (JSON)
        app_handler = RotatingFileHandler(
            path / "sage.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        app_handler.setFormatter(json_formatter)
        app_handler.setLevel(log_level)
        root.addHandler(app_handler)

        # Debug channel (always DEBUG into separate file when dir present)
        debug_handler = RotatingFileHandler(
            path / "sage-debug.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        debug_handler.setFormatter(json_formatter)
        debug_handler.setLevel(logging.DEBUG)
        # Only attach debug file when root is DEBUG; still create logger access
        if log_level <= logging.DEBUG:
            root.addHandler(debug_handler)

        # Module-focused log (INFO+)
        module_handler = RotatingFileHandler(
            path / "sage-modules.log",
            maxBytes=max_bytes,
            backupCount=3,
            encoding="utf-8",
        )
        module_handler.setFormatter(json_formatter)
        module_handler.setLevel(logging.INFO)
        module_handler.addFilter(_ModuleFilter())
        root.addHandler(module_handler)

        # Audit log — separate logger, not propagating noise
        audit_logger = logging.getLogger(_AUDIT_LOGGER_NAME)
        audit_logger.handlers.clear()
        audit_logger.setLevel(logging.INFO)
        audit_logger.propagate = False
        audit_handler = RotatingFileHandler(
            path / "sage-audit.log",
            maxBytes=max_bytes,
            backupCount=10,
            encoding="utf-8",
        )
        audit_handler.setFormatter(json_formatter)
        audit_logger.addHandler(audit_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    if session_id:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(session_id=session_id)

    _CONFIGURED = True


class _ModuleFilter(logging.Filter):
    """Keep sage.* module logs; drop pure access noise later if needed."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith("sage.")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def get_audit_logger() -> structlog.stdlib.BoundLogger:
    """Return the audit channel logger (writes to sage-audit.log when configured)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(_AUDIT_LOGGER_NAME))


def audit(action: str, **fields: Any) -> None:
    """Write a structured audit event."""
    get_audit_logger().info("audit", action=action, **fields)
