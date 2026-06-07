import enum
import uuid
from datetime import datetime

from sqlalchemy import UUID, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base


class WatchMode(enum.StrEnum):
    LIVE = "LIVE"
    REWATCH = "REWATCH"


class StreamWatchSession(Base):
    __tablename__ = "stream_watch_session"

    id: Mapped[str] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4
    )
    stream_id: Mapped[str] = mapped_column(
        "stream_id",
        UUID(as_uuid=True),
        ForeignKey("stream.id"),
        nullable=False,
        index=True,
    )
    schedule_id: Mapped[str] = mapped_column(
        "schedule_id",
        UUID(as_uuid=True),
        ForeignKey("schedule.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("user.id"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column("mode", String(20), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        "started_at", DateTime(timezone=True), nullable=False
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        "last_heartbeat_at", DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime] = mapped_column(
        "ended_at", DateTime(timezone=True), nullable=True
    )
    watched_seconds: Mapped[int] = mapped_column(
        "watched_seconds", Integer, nullable=False, default=0
    )
    last_position_seconds: Mapped[float] = mapped_column(
        "last_position_seconds", Float, nullable=False, default=0
    )
    qualified: Mapped[bool] = mapped_column(
        "qualified", Boolean, nullable=False, default=False
    )
    client_session_id: Mapped[str] = mapped_column(
        "client_session_id", String(255), nullable=False, index=True
    )
    user_agent: Mapped[str] = mapped_column("user_agent", String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at", DateTime(timezone=True), nullable=False, default=datetime.now
    )

    stream = relationship("Stream", backref="watch_sessions")
    schedule = relationship("Schedule", backref="watch_sessions")
    user = relationship("User", backref="watch_sessions")
