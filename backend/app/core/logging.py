"""Centralized logging.

Every log line is a single JSON object (easy to search in CloudWatch) and carries the
current request's ID, so all lines produced while serving one request can be grouped.
"""

import json
import logging
import logging.config
from contextvars import ContextVar
from datetime import UTC, datetime

# Holds the ID of the request currently being processed (set by RequestContextMiddleware).
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed via `extra=` and is included.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RequestIdFilter(logging.Filter):
    """Adds request_id to records for the human-readable (non-JSON) format."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get() or "-"
        return True


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {
                "json": {"()": JsonFormatter},
                "plain": {
                    "format": "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json" if json_logs else "plain",
                    "filters": ["request_id"],
                }
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                # We write our own access log line per request (see middleware).
                "uvicorn.access": {"handlers": [], "propagate": False},
                "uvicorn.error": {"level": level},
                "sqlalchemy.engine": {"level": "WARNING"},
            },
        }
    )
