from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import ValidationError

from core.health_check import health_check
from core.log import logger
from core.rate_limiter.memory import InMemoryRateLimiter
from core.rate_limiter.middleware import RateLimitMiddleware

from settings import (
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_EXCLUDED_PATHS,
    RATE_LIMIT_PER_MINUTE,
    RATE_LIMIT_WINDOW,
)

from core.telemetry import setup_telemetry

otel_enabled = setup_telemetry()

health_check()

app = FastAPI(title="PyconId 2025 BE")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    RateLimitMiddleware,
    backend=InMemoryRateLimiter,
    enabled=RATE_LIMIT_ENABLED,
    limit=RATE_LIMIT_PER_MINUTE,
    window=RATE_LIMIT_WINDOW,
    exclude_paths=RATE_LIMIT_EXCLUDED_PATHS,
)

if otel_enabled:
    FastAPIInstrumentor.instrument_app(app)

from routes.auth import router as auth_router  # noqa: E402
from routes.locations import router as locations_router  # noqa: E402
from routes.organizer import router as organizer_router  # noqa: E402
from routes.organizer_type import router as organizer_type_router  # noqa: E402
from routes.payment import router as payment_router  # noqa: E402
from routes.room import router as room_router  # noqa: E402
from routes.schedule import router as schedule_router  # noqa: E402
from routes.schedule_type import router as schedule_type_router  # noqa: E402
from routes.speaker import router as speaker_router  # noqa: E402
from routes.speaker_type import router as speaker_type_router  # noqa: E402
from routes.streaming import router as streaming_router  # noqa: E402
from routes.ticket import router as ticket_router  # noqa: E402
from routes.user_profile import router as user_profile_router  # noqa: E402
from routes.volunteer import router as volunteer_router  # noqa: E402
from routes.voucher import router as voucher_router  # noqa: E402

app.include_router(auth_router)
app.include_router(user_profile_router)
app.include_router(locations_router)
app.include_router(ticket_router)
app.include_router(room_router)
app.include_router(speaker_router)
app.include_router(schedule_router)
app.include_router(payment_router)
app.include_router(streaming_router)
app.include_router(voucher_router)
app.include_router(speaker_type_router)
app.include_router(organizer_type_router)
app.include_router(organizer_router)
app.include_router(schedule_type_router)
app.include_router(volunteer_router)


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    # Logikanya hampir sama, hanya cara mengambil detail errornya sedikit berbeda
    error_details = []
    # exc.errors() dari pydantic.ValidationError sedikit berbeda strukturnya
    for error in exc.errors():
        field = error["loc"][0] if error["loc"] else "general"
        message = error["msg"]
        error_details.append({"field": field, "message": message})

    return JSONResponse(
        status_code=422,
        content={
            "message": "Terjadi kesalahan validasi pada data form (Pydantic validation).",
            "errors": error_details,
        },
    )


@app.get("/")
async def hello():
    logger.info("hello")
    return {"Hello": "from pyconid 2025 BE"}


@app.get("/health")
def health():
    return {"status": "ok"}
