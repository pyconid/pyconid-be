from datetime import datetime, timedelta
from typing import Optional, Union
from uuid import UUID

from pytz import timezone
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from models.Stream import Stream, StreamStatus
from models.StreamWatchSession import StreamWatchSession, WatchMode
from settings import TZ


def now_tz() -> datetime:
    return datetime.now(timezone(TZ))


def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return timezone(TZ).localize(dt)
    return dt.astimezone(timezone(TZ))


def create_watch_session(
    db: Session,
    stream_id: Union[UUID, str],
    schedule_id: Union[UUID, str],
    user_id: Union[UUID, str],
    mode: WatchMode,
    client_session_id: str,
    user_agent: Optional[str] = None,
    position_seconds: Optional[float] = None,
) -> StreamWatchSession:
    now = now_tz()
    session = StreamWatchSession(
        stream_id=stream_id,
        schedule_id=schedule_id,
        user_id=user_id,
        mode=mode,
        client_session_id=client_session_id,
        user_agent=user_agent,
        started_at=now,
        last_heartbeat_at=now,
        watched_seconds=0,
        last_position_seconds=position_seconds or 0,
        qualified=False,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_watch_session(
    db: Session, session_id: Union[UUID, str]
) -> Optional[StreamWatchSession]:
    stmt = select(StreamWatchSession).where(StreamWatchSession.id == session_id)
    return db.execute(stmt).scalar_one_or_none()


def get_active_session(
    db: Session,
    user_id: Union[UUID, str],
    schedule_id: Union[UUID, str],
    client_session_id: str,
) -> Optional[StreamWatchSession]:
    stmt = (
        select(StreamWatchSession)
        .where(
            StreamWatchSession.user_id == user_id,
            StreamWatchSession.schedule_id == schedule_id,
            StreamWatchSession.client_session_id == client_session_id,
            StreamWatchSession.ended_at.is_(None),
        )
        .order_by(StreamWatchSession.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def update_heartbeat(
    db: Session,
    session: StreamWatchSession,
    position_seconds: float,
) -> None:
    now = now_tz()
    previous_heartbeat = ensure_aware(session.last_heartbeat_at)
    server_delta = int((now - previous_heartbeat).total_seconds())
    position_delta = int(position_seconds - session.last_position_seconds)

    if server_delta < 0:
        server_delta = 0
    if position_delta < 0:
        position_delta = 0

    delta = min(server_delta, position_delta, 20)
    session.watched_seconds += delta
    session.last_position_seconds = max(session.last_position_seconds, position_seconds)
    session.last_heartbeat_at = now
    session.qualified = session.watched_seconds >= 60
    session.updated_at = now
    db.commit()
    db.refresh(session)


def end_watch_session(
    db: Session, session: StreamWatchSession, position_seconds: Optional[float] = None
) -> None:
    if session.ended_at is not None:
        return
    if position_seconds is not None:
        update_heartbeat(db, session, position_seconds)
    now = now_tz()
    session.ended_at = now
    session.updated_at = now
    db.commit()
    db.refresh(session)


def get_analytics_by_schedule(
    db: Session,
    schedule_id: Union[UUID, str],
    mode: Optional[WatchMode] = None,
) -> dict:
    filters = [
        StreamWatchSession.schedule_id == schedule_id,
        StreamWatchSession.qualified.is_(True),
    ]
    if mode:
        filters.append(StreamWatchSession.mode == mode)

    stats = (
        db.query(
            func.count(func.distinct(StreamWatchSession.user_id)).label(
                "total_watchers"
            ),
            func.sum(StreamWatchSession.watched_seconds).label("total_watched_seconds"),
        )
        .filter(*filters)
        .first()
    )

    live = 0
    rewatch = 0
    if mode in [None, WatchMode.LIVE]:
        live = (
            db.query(func.count(func.distinct(StreamWatchSession.user_id)))
            .filter(
                StreamWatchSession.schedule_id == schedule_id,
                StreamWatchSession.mode == WatchMode.LIVE,
                StreamWatchSession.qualified.is_(True),
            )
            .scalar()
            or 0
        )
    if mode in [None, WatchMode.REWATCH]:
        rewatch = (
            db.query(func.count(func.distinct(StreamWatchSession.user_id)))
            .filter(
                StreamWatchSession.schedule_id == schedule_id,
                StreamWatchSession.mode == WatchMode.REWATCH,
                StreamWatchSession.qualified.is_(True),
            )
            .scalar()
            or 0
        )

    return {
        "stream_id": str(schedule_id), # We don't have a specific stream_id for a schedule, but we need it for the response model
        "schedule_id": str(schedule_id),
        "live_qualified_watchers": live,
        "rewatch_qualified_watchers": rewatch,
        "total_qualified_watchers": stats.total_watchers or 0,
        "total_watched_minutes": int((stats.total_watched_seconds or 0) / 60),
    }


def get_analytics_overall(
    db: Session,
    schedule_id: Optional[Union[UUID, str]] = None,
    mode: Optional[WatchMode] = None,
) -> dict:
    filters = [StreamWatchSession.qualified.is_(True)]
    if schedule_id:
        filters.append(StreamWatchSession.schedule_id == schedule_id)
    if mode:
        filters.append(StreamWatchSession.mode == mode)

    stats = (
        db.query(
            func.count(func.distinct(StreamWatchSession.user_id)).label(
                "total_watchers"
            ),
            func.sum(StreamWatchSession.watched_seconds).label("total_watched_seconds"),
        )
        .filter(*filters)
        .first()
    )

    live = 0
    rewatch = 0
    if mode in [None, WatchMode.LIVE]:
        live_filters = [
            StreamWatchSession.mode == WatchMode.LIVE,
            StreamWatchSession.qualified.is_(True),
        ]
        if schedule_id:
            live_filters.append(StreamWatchSession.schedule_id == schedule_id)
        live = (
            db.query(func.count(func.distinct(StreamWatchSession.user_id)))
            .filter(*live_filters)
            .scalar()
            or 0
        )
    if mode in [None, WatchMode.REWATCH]:
        rewatch_filters = [
            StreamWatchSession.mode == WatchMode.REWATCH,
            StreamWatchSession.qualified.is_(True),
        ]
        if schedule_id:
            rewatch_filters.append(StreamWatchSession.schedule_id == schedule_id)
        rewatch = (
            db.query(func.count(func.distinct(StreamWatchSession.user_id)))
            .filter(*rewatch_filters)
            .scalar()
            or 0
        )

    return {
        "live_qualified_watchers": live,
        "rewatch_qualified_watchers": rewatch,
        "total_qualified_watchers": stats.total_watchers or 0,
        "total_watched_minutes": int((stats.total_watched_seconds or 0) / 60),
    }


def get_analytics_all_streams(
    db: Session,
    schedule_id: Optional[Union[UUID, str]] = None,
    mode: Optional[WatchMode] = None,
) -> list[dict]:
    stmt = select(Stream).order_by(
        case((Stream.status == StreamStatus.STREAMING.value, 0), else_=1),
        Stream.created_at.desc(),
    )
    if schedule_id:
        stmt = stmt.where(Stream.schedule_id == schedule_id)
    streams = db.execute(stmt).scalars().all()

    data = []
    for stream in streams:
        if not stream.schedule_id:
            continue
        analytics = get_analytics_by_schedule(db, stream.schedule_id, mode=mode)
        analytics.update(
            {
                "stream_id": str(stream.id),
                "schedule_title": stream.schedule.title if stream.schedule else None,
                "room": stream.schedule.room.name
                if stream.schedule and stream.schedule.room
                else None,
                "status": stream.status,
            }
        )
        data.append(analytics)
    return data


def get_watch_detail_by_schedule(db: Session, schedule_id: Union[UUID, str]) -> list[dict]:
    stmt = (
        select(StreamWatchSession)
        .where(
            StreamWatchSession.schedule_id == schedule_id,
            StreamWatchSession.qualified.is_(True),
        )
        .order_by(StreamWatchSession.watched_seconds.desc())
    )
    sessions = db.execute(stmt).scalars().all()

    return [
        {
            "client_session_id": s.client_session_id,
            "user_id": str(s.user_id),
            "email": s.user.email if s.user else None,
            "name": (
                f"{s.user.first_name or ''} {s.user.last_name or ''}".strip()
                if s.user
                else None
            ),
            "mode": s.mode,
            "watched_seconds": s.watched_seconds,
            "qualified": s.qualified,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
        }
        for s in sessions
    ]


def end_abandoned_sessions(db: Session, timeout_minutes: int = 5) -> int:
    timeout_threshold = now_tz() - timedelta(minutes=timeout_minutes)

    stmt = (
        update(StreamWatchSession)
        .where(
            StreamWatchSession.ended_at.is_(None),
            StreamWatchSession.last_heartbeat_at < timeout_threshold,
        )
        .values(
            ended_at=StreamWatchSession.last_heartbeat_at,
            updated_at=now_tz()
        )
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount


def get_live_analytics_snapshot(db: Session) -> dict:
    two_min_ago = now_tz() - timedelta(minutes=2)

    active_sessions = (
        db.query(StreamWatchSession)
        .filter(
            StreamWatchSession.last_heartbeat_at >= two_min_ago,
            StreamWatchSession.ended_at.is_(None),
        )
        .all()
    )

    streams_data = {}
    for s in active_sessions:
        sid = str(s.stream_id)
        if sid not in streams_data:
            streams_data[sid] = {
                "stream_id": sid,
                "schedule_id": str(s.schedule_id) if s.schedule_id else None,
                "schedule_title": s.schedule.title if s.schedule else None,
                "room": s.schedule.room.name
                if s.schedule and s.schedule.room
                else None,
                "status": s.stream.status if s.stream else None,
                "live_viewers_now": set(),
            }
        streams_data[sid]["live_viewers_now"].add(str(s.user_id))

    result = []
    for data in streams_data.values():
        data["live_viewers_now"] = len(data["live_viewers_now"])
        result.append(data)

    return {"streams": result}
