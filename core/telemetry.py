import os
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanProcessor,
)

from core.log import configure_logging

_initialized = False
_enabled = False


class PCISafeSpanProcessor(SpanProcessor):
    SCRUB_KEYS = {
        "http.request.body",
        "http.response.body",
        "http.request.header.authorization",
        "http.request.header.x-callback-token",
        "http.request.header.mux-signature",
        "http.response.header.authorization",
        "http.response.header.x-callback-token",
        "http.response.header.mux-signature",
        "payment_link",
        "payment.link",
        "mayar_api_key",
        "net.peer.name",
        "net.sock.peer.addr",
        "db.statement",
    }
    SCRUB_PREFIXES = (
        "card",
        "account",
        "payment_link",
        "mayar_api_key",
        "customer_email",
        "customer_phone",
        "customer_mobile",
        "customer_name",
        "mayar_payment_id",
        "mayar_transaction_id",
        "mux_stream_id",
        "mux_asset_id",
        "mux_live_stream_id",
        "mux_playback_id",
        "exception_message",
        "exception_stacktrace",
        "user_email",
        "user_phone",
        "user_mobile",
    )

    def __init__(self, exporter: SpanExporter):
        self._delegate = BatchSpanProcessor(exporter)

    def on_start(self, span, parent_context=None) -> None:
        self._delegate.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        span._attributes = self._scrub_attributes(span.attributes)  # noqa: SLF001
        self._delegate.on_end(span)

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)

    def _scrub_attributes(self, attributes: Any) -> dict[str, Any]:
        scrubbed = {}
        for key, value in dict(attributes or {}).items():
            normalized_key = key.lower().replace(".", "_").replace("-", "_")
            should_scrub = key in self.SCRUB_KEYS or any(
                normalized_key.startswith(prefix) for prefix in self.SCRUB_PREFIXES
            )
            scrubbed[key] = "[REDACTED]" if should_scrub else value
        return scrubbed


def setup_telemetry() -> bool:
    global _enabled, _initialized
    if _initialized:
        return _enabled

    configure_logging()

    if not _env_bool("OTEL_ENABLED", default=False):
        _initialized = True
        return False

    resource = Resource.create(
        {
            SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", "pyconid25-be"),
            "deployment.environment": os.environ.get("ENVIRONTMENT", "file"),
        }
    )
    _setup_traces(resource)
    _setup_metrics(resource)
    _setup_auto_instrumentation()

    _enabled = True
    _initialized = True
    return True


def get_tracer(name: str = "pyconid25-be"):
    return trace.get_tracer(name)


def get_meter(name: str = "pyconid25-be"):
    return metrics.get_meter(name)


def amount_bucket(amount: int | None) -> str:
    if not amount or amount <= 0:
        return "free"
    if amount <= 100_000:
        return "0-100k"
    if amount <= 500_000:
        return "100k-500k"
    if amount <= 1_000_000:
        return "500k-1m"
    return "1m+"


def _setup_traces(resource: Resource) -> None:
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(PCISafeSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def _setup_metrics(resource: Resource) -> None:
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(),
        export_interval_millis=int(
            os.environ.get("OTEL_METRIC_EXPORT_INTERVAL_MS", "30000")
        ),
    )
    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[reader])
    )


def _setup_auto_instrumentation() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    from models import engine

    SQLAlchemyInstrumentor().instrument(engine=engine)
    HTTPXClientInstrumentor().instrument()
    LoggingInstrumentor().instrument(set_logging_format=False)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}
