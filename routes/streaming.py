import json
import traceback
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pytz import timezone
from sqlalchemy.orm import Session

from core.log import logger
from core.mux_service import mux_service
from core.responses import (
    BadRequest,
    InternalServerError,
    NotFound,
    Ok,
    Unauthorized,
    common_response,
    handle_http_exception,
)
from core.security import get_user_from_token, oauth2_scheme
from models import get_db_sync
from models.Stream import StreamStatus
from models.StreamWatchSession import WatchMode
from repository import streaming as streamingRepo
from repository import stream_watch as streamWatchRepo
from schemas.common import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
)
from schemas.streaming import (
    PlaybackURLResponse,
    WatchEndRequest,
    WatchEndResponse,
    WatchHeartbeatRequest,
    WatchHeartbeatResponse,
    WatchStartRequest,
    WatchStartResponse,
)
from schemas.user_profile import ParticipantType
from settings import TZ

router = APIRouter(prefix="/streaming", tags=["Streaming"])


@router.get(
    "/{stream_id}",
    responses={
        "200": {"model": PlaybackURLResponse},
        "400": {"model": BadRequestResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def get_stream_playback(
    stream_id: UUID,
    db: Session = Depends(get_db_sync),
    token: str = Depends(oauth2_scheme),
):
    try:
        current_user = get_user_from_token(db=db, token=token)
        if current_user is None:
            return common_response(Unauthorized(message="Unauthorized"))

        if (
            current_user.participant_type is None
            or current_user.participant_type == ParticipantType.NON_PARTICIPANT
        ):
            return common_response(
                BadRequest(message="You must purchase a ticket to access this stream.")
            )

        stream_asset = streamingRepo.get_stream_by_id(db, stream_id)
        if not stream_asset:
            return common_response(NotFound(message="Stream not found"))

        if stream_asset.schedule.deleted_at:
            return common_response(NotFound(message="Stream not found"))

        # if stream_asset.status not in [
        #     StreamStatus.READY.value,
        #     StreamStatus.STREAMING.value,
        #     StreamStatus.ENDED.value,
        # ]:
        #     return common_response(
        #         BadRequest(message="Stream is not ready for playback")
        #     )

        # Use asset playback ID for ended streams (replay/recording)
        # Use live stream playback ID for active/streaming streams
        playback_id = None
        if stream_asset.status == StreamStatus.ENDED.value:
            playback_id = (
                stream_asset.mux_asset_playback_id or stream_asset.mux_playback_id
            )
        else:
            playback_id = stream_asset.mux_playback_id

        if not playback_id:
            return common_response(
                InternalServerError(custom_response="Playback ID not available")
            )

        playback_token = None
        thumbnail_token = None
        token_expires_at = None
        if stream_asset.is_public:
            playback_url = mux_service.get_public_playback_url(playback_id)
            thumbnail_url = mux_service.get_public_thumbnail_url(playback_id)
        else:
            playback_token, playback_url, token_expires_at = (
                mux_service.generate_signed_playback_url(
                    playback_id, user_id=current_user.id
                )
            )
            thumbnail_token, thumbnail_url, _ = (
                mux_service.generate_signed_thumbnail_url(playback_id)
            )

        return common_response(
            Ok(
                data=PlaybackURLResponse(
                    stream_id=str(stream_id),
                    schedule_id=str(stream_asset.schedule_id),
                    playback=PlaybackURLResponse.Playback(
                        id=playback_id,
                        url=playback_url,
                        token=playback_token,
                    ),
                    thumbnail=PlaybackURLResponse.Thumbnail(
                        url=thumbnail_url,
                        token=thumbnail_token,
                    ),
                    metadata=PlaybackURLResponse.Metadata(
                        user_id=str(current_user.id),
                        title=stream_asset.schedule.title,
                    ),
                    status=StreamStatus(stream_asset.status),
                    token_expires_at=token_expires_at,
                ).model_dump(mode="json")
            )
        )
    except HTTPException as e:
        return handle_http_exception(e)
    except Exception as e:
        traceback.print_exc()
        return common_response(InternalServerError(error=str(e)))


@router.post("/webhook")
async def mux_webhook(request: Request, db: Session = Depends(get_db_sync)):
    try:
        payload = await request.body()
        signature = request.headers.get("Mux-Signature", "")

        if not mux_service.verify_webhook_signature(payload, signature, ""):
            return common_response(Unauthorized(message="Invalid webhook signature"))

        webhook_data = json.loads(payload)
        logger.info(f"Webhook Mux Data: {webhook_data}")
        event_type = webhook_data.get("type")
        data = webhook_data.get("data", {})

        if event_type == "video.asset.ready":
            asset_id = data.get("id")
            playback_ids = data.get("playback_ids", [])
            live_stream_id = data.get("live_stream_id")

            logger.info(
                f"Asset ready - Asset ID: {asset_id}, Live Stream ID: {live_stream_id}"
            )

            # Get the playback ID for the asset
            asset_playback_id = None
            if playback_ids and len(playback_ids) > 0:
                asset_playback_id = playback_ids[0].get("id")

            if live_stream_id and asset_playback_id:
                stream_asset = streamingRepo.get_stream_by_mux_id(db, live_stream_id)
                if stream_asset:
                    streamingRepo.update_stream(
                        db=db,
                        stream_asset=stream_asset,
                        mux_asset_id=asset_id,
                        mux_asset_playback_id=asset_playback_id,
                    )
                    logger.info(
                        f"Updated stream {stream_asset.id} with asset playback ID: {asset_playback_id}"
                    )
                else:
                    logger.warning(
                        f"Could not find stream for live_stream_id: {live_stream_id}"
                    )
            else:
                logger.warning(
                    "Missing live_stream_id or asset_playback_id in asset.ready event"
                )

        elif event_type == "video.live_stream.recording":
            # Live stream recording available
            stream_id = data.get("id")
            stream_asset = streamingRepo.get_stream_by_mux_id(db, stream_id)
            if stream_asset:
                streamingRepo.update_stream(
                    db=db,
                    stream_asset=stream_asset,
                    status=StreamStatus.READY,
                    stream_started_at=datetime.now(timezone(TZ)),
                )

        elif event_type == "video.live_stream.active":
            # Live stream started
            stream_id = data.get("id")
            stream_asset = streamingRepo.get_stream_by_mux_id(db, stream_id)
            if stream_asset:
                streamingRepo.update_stream(
                    db=db,
                    stream_asset=stream_asset,
                    status=StreamStatus.STREAMING,
                    stream_started_at=datetime.now(timezone(TZ)),
                )

        elif event_type == "video.live_stream.idle":
            # Live stream stopped
            stream_id = data.get("id")
            stream_asset = streamingRepo.get_stream_by_mux_id(db, stream_id)
            if stream_asset:
                duration = None
                if stream_asset.stream_started_at:
                    duration = int(
                        (
                            datetime.now(timezone(TZ)) - stream_asset.stream_started_at
                        ).total_seconds()
                    )

                streamingRepo.update_stream(
                    db=db,
                    stream_asset=stream_asset,
                    status=StreamStatus.ENDED,
                    stream_ended_at=datetime.now(timezone(TZ)),
                    duration=duration,
                )

        return common_response(Ok(data={"status": "success"}))
    except HTTPException:
        raise
    except Exception as e:
        return common_response(InternalServerError(error=str(e)))


@router.post(
    "/{stream_id}/watch/start",
    responses={
        "200": {"model": WatchStartResponse},
        "400": {"model": BadRequestResponse},
        "401": {"model": UnauthorizedResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def watch_start(
    stream_id: UUID,
    body: WatchStartRequest,
    request: Request,
    db: Session = Depends(get_db_sync),
    token: str = Depends(oauth2_scheme),
):
    try:
        current_user = get_user_from_token(db=db, token=token)
        if current_user is None:
            return common_response(Unauthorized(message="Unauthorized"))

        if (
            current_user.participant_type is None
            or current_user.participant_type == ParticipantType.NON_PARTICIPANT
        ):
            return common_response(
                BadRequest(message="You must purchase a ticket to access this stream.")
            )

        stream_asset = streamingRepo.get_stream_by_id(db, stream_id)
        if not stream_asset:
            return common_response(NotFound(message="Stream not found"))
        if stream_asset.schedule.deleted_at:
            return common_response(NotFound(message="Stream not found"))

        existing = streamWatchRepo.get_active_session(
            db, current_user.id, stream_asset.schedule_id, body.client_session_id
        )
        if existing:
            return common_response(
                Ok(
                    data=WatchStartResponse(
                        watch_session_id=str(existing.id),
                        mode=existing.mode,
                    ).model_dump(mode="json")
                )
            )

        if stream_asset.status == StreamStatus.STREAMING.value:
            mode = WatchMode.LIVE
        elif stream_asset.status == StreamStatus.ENDED.value:
            mode = WatchMode.REWATCH
        else:
            return common_response(BadRequest(message="Stream is not playable"))

        user_agent = request.headers.get("user-agent")
        session = streamWatchRepo.create_watch_session(
            db=db,
            stream_id=stream_id,
            schedule_id=stream_asset.schedule_id,
            user_id=current_user.id,
            mode=mode,
            client_session_id=body.client_session_id,
            user_agent=user_agent,
            position_seconds=body.position_seconds,
        )

        return common_response(
            Ok(
                data=WatchStartResponse(
                    watch_session_id=str(session.id),
                    mode=session.mode,
                ).model_dump(mode="json")
            )
        )
    except HTTPException as e:
        return handle_http_exception(e)
    except Exception as e:
        traceback.print_exc()
        return common_response(InternalServerError(error=str(e)))


@router.post(
    "/{stream_id}/watch/heartbeat",
    responses={
        "200": {"model": WatchHeartbeatResponse},
        "400": {"model": BadRequestResponse},
        "401": {"model": UnauthorizedResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def watch_heartbeat(
    stream_id: UUID,
    body: WatchHeartbeatRequest,
    db: Session = Depends(get_db_sync),
    token: str = Depends(oauth2_scheme),
):
    try:
        current_user = get_user_from_token(db=db, token=token)
        if current_user is None:
            return common_response(Unauthorized(message="Unauthorized"))

        session = streamWatchRepo.get_watch_session(db, body.watch_session_id)
        if not session:
            return common_response(NotFound(message="Watch session not found"))
        if str(session.user_id) != str(current_user.id):
            return common_response(Unauthorized(message="Unauthorized"))
        if str(session.stream_id) != str(stream_id):
            return common_response(NotFound(message="Watch session not found"))
        if session.client_session_id != body.client_session_id:
            return common_response(Unauthorized(message="Unauthorized"))
        if session.ended_at is not None:
            return common_response(
                BadRequest(message="Watch session has already ended")
            )

        streamWatchRepo.update_heartbeat(db, session, body.position_seconds)

        return common_response(
            Ok(
                data=WatchHeartbeatResponse(
                    watched_seconds=session.watched_seconds,
                    qualified=session.qualified,
                ).model_dump(mode="json")
            )
        )
    except HTTPException as e:
        return handle_http_exception(e)
    except Exception as e:
        traceback.print_exc()
        return common_response(InternalServerError(error=str(e)))


@router.post(
    "/{stream_id}/watch/end",
    responses={
        "200": {"model": WatchEndResponse},
        "400": {"model": BadRequestResponse},
        "401": {"model": UnauthorizedResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def watch_end(
    stream_id: UUID,
    body: WatchEndRequest,
    db: Session = Depends(get_db_sync),
    token: str = Depends(oauth2_scheme),
):
    try:
        current_user = get_user_from_token(db=db, token=token)
        if current_user is None:
            return common_response(Unauthorized(message="Unauthorized"))

        session = streamWatchRepo.get_watch_session(db, body.watch_session_id)
        if not session:
            return common_response(NotFound(message="Watch session not found"))
        if str(session.user_id) != str(current_user.id):
            return common_response(Unauthorized(message="Unauthorized"))
        if str(session.stream_id) != str(stream_id):
            return common_response(NotFound(message="Watch session not found"))
        if session.client_session_id != body.client_session_id:
            return common_response(Unauthorized(message="Unauthorized"))

        streamWatchRepo.end_watch_session(db, session, body.position_seconds)

        return common_response(
            Ok(
                data=WatchEndResponse(
                    watched_seconds=session.watched_seconds,
                    qualified=session.qualified,
                ).model_dump(mode="json")
            )
        )
    except HTTPException as e:
        return handle_http_exception(e)
    except Exception as e:
        traceback.print_exc()
        return common_response(InternalServerError(error=str(e)))
