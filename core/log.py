import json
import logging
import logging.config
import os
import re
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

_REDACTION_PATTERNS = (
    re.compile(
        r"(?i)(authorization|x-callback-token|mux-signature)"
        r"([\s:=]+)(bearer\s+)?([^\s,;}]+)"
    ),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)(mayar_api_key|mayar_webhook_secret|mux_token_secret|"
        r"mux_webhook_secret|mux_signing_key_private|secret_key)"
        r"([\s:=]+)([^\s,;}]+)"
    ),
    re.compile(
        r"(?i)(payment_link|link|redirect_url|redirecturl|url)"
        r"([\s:=]+)(https?://[^\s,;}]+)"
    ),
    re.compile(r"(?i)(transactionid|transaction_id)([\s:=]+)([^\s,;}]+)"),
    re.compile(r"(?i)(email)([\s:=]+)([^\s,;}]+@[^\s,;}]+)"),
    re.compile(r"(?i)(phone|mobile)([\s:=]+)(\+?[0-9][0-9\s().-]{5,})"),
    re.compile(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"),
)


def _redact_sensitive(value: str) -> str:
    redacted = value
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub(_replace_sensitive_match, redacted)
    return redacted


def _replace_sensitive_match(match: re.Match[str]) -> str:
    if match.re.pattern.startswith("(?i)bearer"):
        return "Bearer [REDACTED]"
    if match.re.pattern.startswith("eyJ"):
        return "[REDACTED]"
    if match.lastindex and match.lastindex >= 2:
        return f"{match.group(1)}{match.group(2)}[REDACTED]"
    return "[REDACTED]"


class JsonFormatter(logging.Formatter):
    """JSON log formatter with optional Datadog-compatible field names.

    When ``DD_ENABLED=true``, outputs ``dd.trace_id`` and ``dd.span_id``
    as **decimal** strings (lower 64-bit of the 128-bit OTel trace-id)
    so that Datadog Agent can correlate logs ↔ APM traces automatically.

    When ``DD_ENABLED=false`` (default), outputs standard ``trace_id``
    and ``span_id`` in hex format for generic OTel-compatible backends.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._dd_enabled = os.environ.get("DD_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _hex_to_dd_trace_id(hex_trace_id: str) -> str:
        """Convert a 128-bit hex trace-id to Datadog's 64-bit decimal."""
        try:
            return str(int(hex_trace_id[-16:], 16))
        except (ValueError, IndexError):
            return "0"

    @staticmethod
    def _hex_to_dd_span_id(hex_span_id: str) -> str:
        """Convert a hex span-id to Datadog's decimal format."""
        try:
            return str(int(hex_span_id, 16))
        except (ValueError, IndexError):
            return "0"

    def format(self, record: logging.LogRecord) -> str:
        hex_trace_id = getattr(record, "requestTraceID", None) or getattr(
            record, "otelTraceID", "0"
        )
        hex_span_id = getattr(record, "requestSpanID", None) or getattr(
            record, "otelSpanID", "0"
        )

        if hex_trace_id == "0":
            span_context = trace.get_current_span().get_span_context()
            if span_context.is_valid:
                hex_trace_id = format(span_context.trace_id, "032x")
                hex_span_id = format(span_context.span_id, "016x")

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "status": record.levelname,
            "message": _redact_sensitive(record.getMessage()),
            "logger.name": record.name,
            "service": getattr(
                record,
                "otelServiceName",
                os.environ.get("OTEL_SERVICE_NAME", "pyconid25-be"),
            ),
        }

        if self._dd_enabled:
            payload["dd.trace_id"] = self._hex_to_dd_trace_id(hex_trace_id)
            payload["dd.span_id"] = self._hex_to_dd_span_id(hex_span_id)
            payload["dd.env"] = os.environ.get(
                "DD_ENV", os.environ.get("ENVIRONTMENT", "")
            )
        else:
            payload["trace_id"] = hex_trace_id
            payload["span_id"] = hex_span_id

        if record.exc_info:
            payload["exception"] = _redact_sensitive(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    log_level = os.environ.get("OTEL_LOG_LEVEL", "INFO").upper()
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "level": log_level,
                }
            },
            "root": {"handlers": ["console"], "level": log_level},
            "loggers": {
                "uvicorn": {
                    "handlers": ["console"],
                    "level": log_level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console"],
                    "level": log_level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": "WARNING",
                    "propagate": False,
                },
            },
        }
    )


logger = logging.getLogger("uvicorn.error")
