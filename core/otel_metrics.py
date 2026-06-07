from core.telemetry import get_meter

meter = get_meter("pyconid25-be")

payment_created_counter = meter.create_counter(
    "payment.created",
    description="Total payments created",
    unit="1",
)
payment_status_counter = meter.create_counter(
    "payment.status_change",
    description="Payment status transitions",
    unit="1",
)
payment_webhook_counter = meter.create_counter(
    "payment.webhook_received",
    description="Payment webhooks received",
    unit="1",
)
streaming_webhook_counter = meter.create_counter(
    "streaming.webhook_received",
    description="Streaming webhooks received",
    unit="1",
)
