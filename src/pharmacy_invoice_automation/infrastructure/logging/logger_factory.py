"""
LoggerFactory: the shared logging facility for every other Infrastructure
module (Technical Design Document Section 11).

Provides one child logger per FR-10 category under the
``pharmacy_automation`` root: ocr, gemini_api, automation, database,
error, retry. Every logger returned has the RedactionFilter attached,
so no call site can accidentally leak a secret regardless of what it
logs.

Note: Domain no longer defines an ILogger port (removed during the
Stage 04 redesign -- Domain's architecture rules explicitly forbid it
from performing logging or knowing about configuration/DI). This class
is therefore a standalone Infrastructure utility, consumed directly by
other Infrastructure adapters and, later, by the Composition Root --
not an implementation of any Domain-defined abstraction.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from pharmacy_invoice_automation.infrastructure.logging.redaction_filter import (
    RedactionFilter,
)

CATEGORIES: tuple[str, ...] = ("ocr", "gemini_api", "automation", "database", "error", "retry")
_ROOT_LOGGER_NAME = "pharmacy_automation"


class LoggerFactory:
    """Builds and caches the six category loggers, each writing to a shared rotating file."""

    def __init__(
        self,
        log_directory: Path,
        *,
        log_level: str = "INFO",
        retention_days: int = 14,
    ) -> None:
        self._log_directory = log_directory
        self._log_level = log_level
        self._retention_days = retention_days
        self._redaction_filter = RedactionFilter()
        self._log_directory.mkdir(parents=True, exist_ok=True)

    def get_logger(self, category: str) -> logging.Logger:
        """
        Return the logger for ``category`` (one of CATEGORIES),
        configuring it with a rotating file handler and the shared
        RedactionFilter on first use.

        Checks the logger's own (globally-cached, per
        ``logging.getLogger``) handler list rather than any
        per-instance bookkeeping -- two LoggerFactory instances
        resolving the same category must never double up handlers.
        """
        if category not in CATEGORIES:
            raise ValueError(
                f"Unknown logging category {category!r}; expected one of {CATEGORIES}."
            )

        logger = logging.getLogger(f"{_ROOT_LOGGER_NAME}.{category}")
        if not logger.handlers:
            self._configure(logger, category)
        return logger

    def _configure(self, logger: logging.Logger, category: str) -> None:
        logger.setLevel(self._log_level)
        logger.propagate = False

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=self._log_directory / f"{category}.log",
            when="midnight",
            backupCount=self._retention_days,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(self._redaction_filter)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(self._redaction_filter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
