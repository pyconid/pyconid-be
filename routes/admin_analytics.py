import json
from asyncio import sleep
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from core.log import logger
from core.responses import (
    BadRequest,
    Forbidden,
    InternalServerError,
    Ok,
    Unauthorized,
    common_response,
)
from core.security import check_permissions, get_current_user
from models import db as db_factory, get_db_sync
from models.StreamWatchSession import WatchMode
from models.User import MANAGEMENT_PARTICIPANT, User
from repository import stream_watch as streamWatchRepo
from schemas.auth import AuthorizationStatusEnum
from schemas.common import (
    BadRequestResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    UnauthorizedResponse,
)
from schemas.streaming import (
    StreamAnalyticsDetailResponse,
    StreamAnalyticsSummaryResponse,
)

router = APIRouter(
    prefix="/admin/streaming/analytics", tags=["Admin Streaming Analytics"]
)


def validate_admin(current_user: User | None):
    auth_status = check_permissions(current_user, MANAGEMENT_PARTICIPANT)
    if auth_status == AuthorizationStatusEnum.UNAUTHORIZED:
        return common_response(Unauthorized(message="Unauthorized"))
    if auth_status == AuthorizationStatusEnum.FORBIDDEN:
        return common_response(Forbidden(custom_response={"message": "Forbidden"}))
    return None


@router.get(
    "/summary",
    responses={
        "200": {"model": StreamAnalyticsSummaryResponse},
        "400": {"model": BadRequestResponse},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def get_streaming_analytics_summary(
    schedule_id: Optional[UUID] = None,
    mode: Optional[str] = None,
    db: Session = Depends(get_db_sync),
    current_user: User | None = Depends(get_current_user),
):
    admin_error = validate_admin(current_user)
    if admin_error:
        return admin_error

    try:
        watch_mode = None
        if mode:
            try:
                watch_mode = WatchMode(mode.upper())
            except ValueError:
                return common_response(
                    BadRequest(message="mode must be LIVE or REWATCH")
                )

        overall = streamWatchRepo.get_analytics_overall(
            db=db, schedule_id=schedule_id, mode=watch_mode
        )
        streams = streamWatchRepo.get_analytics_all_streams(
            db=db, schedule_id=schedule_id, mode=watch_mode
        )
        return common_response(
            Ok(
                data=StreamAnalyticsSummaryResponse(
                    overall=overall,
                    streams=streams,
                ).model_dump(mode="json")
            )
        )
    except Exception as e:
        logger.error(f"Error fetching streaming analytics summary: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.get(
    "/{schedule_id}/detail",
    responses={
        "200": {"model": StreamAnalyticsDetailResponse},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def get_streaming_analytics_detail(
    schedule_id: UUID,
    db: Session = Depends(get_db_sync),
    current_user: User | None = Depends(get_current_user),
):
    admin_error = validate_admin(current_user)
    if admin_error:
        return admin_error

    try:
        analytics = streamWatchRepo.get_analytics_by_schedule(db, schedule_id)
        watchers = streamWatchRepo.get_watch_detail_by_schedule(db, schedule_id)
        return common_response(
            Ok(
                data=StreamAnalyticsDetailResponse(
                    stream_id=analytics["stream_id"],
                    schedule_id=str(schedule_id),
                    watchers=watchers,
                    live_qualified_watchers=analytics["live_qualified_watchers"],
                    rewatch_qualified_watchers=analytics["rewatch_qualified_watchers"],
                    total_qualified_watchers=analytics["total_qualified_watchers"],
                    total_watched_minutes=analytics["total_watched_minutes"],
                ).model_dump(mode="json")
            )
        )
    except Exception as e:
        logger.error(f"Error fetching streaming analytics detail: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.get(
    "/live",
    responses={
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def get_streaming_analytics_live(
    request: Request,
    current_user: User | None = Depends(get_current_user),
):
    admin_error = validate_admin(current_user)
    if admin_error:
        return admin_error

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            sse_db = db_factory()
            try:
                data = streamWatchRepo.get_live_analytics_snapshot(sse_db)
            finally:
                sse_db.close()
            yield f"event: viewer_update\ndata: {json.dumps(data)}\n\n"
            await sleep(5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
