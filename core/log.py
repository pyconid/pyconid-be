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
    def format(self, record: logging.LogRecord) -> str:
        trace_id = getattr(record, "requestTraceID", None) or getattr(
            record, "otelTraceID", "0"
        )
        span_id = getattr(record, "requestSpanID", None) or getattr(
            record, "otelSpanID", "0"
        )

        if trace_id == "0":
            span_context = trace.get_current_span().get_span_context()
            if span_context.is_valid:
                trace_id = format(span_context.trace_id, "032x")
                span_id = format(span_context.span_id, "016x")

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "message": _redact_sensitive(record.getMessage()),
            "logger": record.name,
            "trace_id": trace_id,
            "span_id": span_id,
            "service": getattr(
                record,
                "otelServiceName",
                os.environ.get("OTEL_SERVICE_NAME", "pyconid25-be"),
            ),
        }
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
