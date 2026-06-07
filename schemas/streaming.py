from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from models.Stream import StreamStatus


class PlaybackURLResponse(BaseModel):
    class Playback(BaseModel):
        id: str
        url: str
        token: Optional[str]

    playback: Playback

    class Thumbnail(BaseModel):
        url: Optional[str]
        token: Optional[str]

    thumbnail: Thumbnail

    class Metadata(BaseModel):
        user_id: Optional[str]
        title: Optional[str]

    metadata: Metadata

    status: StreamStatus
    token_expires_at: Optional[datetime] = Field(
        None, description="Token expiration time for private streams"
    )


class WatchStartRequest(BaseModel):
    client_session_id: str = Field(min_length=1, max_length=255)
    position_seconds: Optional[float] = Field(default=None, ge=0)


class WatchStartResponse(BaseModel):
    watch_session_id: str
    mode: str
    heartbeat_interval: int = 15


class WatchHeartbeatRequest(BaseModel):
    watch_session_id: UUID
    client_session_id: str = Field(min_length=1, max_length=255)
    position_seconds: float = Field(ge=0)


class WatchHeartbeatResponse(BaseModel):
    ok: bool = True
    watched_seconds: int
    qualified: bool


class WatchEndRequest(BaseModel):
    watch_session_id: UUID
    client_session_id: str = Field(min_length=1, max_length=255)
    position_seconds: Optional[float] = Field(default=None, ge=0)


class WatchEndResponse(BaseModel):
    ok: bool = True
    watched_seconds: int
    qualified: bool


class StreamAnalyticsItem(BaseModel):
    stream_id: str
    schedule_title: Optional[str] = None
    room: Optional[str] = None
    status: Optional[str] = None
    live_qualified_watchers: int = 0
    rewatch_qualified_watchers: int = 0
    total_qualified_watchers: int = 0
    total_watched_minutes: int = 0


class StreamAnalyticsAggregate(BaseModel):
    live_qualified_watchers: int = 0
    rewatch_qualified_watchers: int = 0
    total_qualified_watchers: int = 0
    total_watched_minutes: int = 0


class StreamAnalyticsSummaryResponse(BaseModel):
    overall: StreamAnalyticsAggregate
    streams: list[StreamAnalyticsItem]


class WatcherDetail(BaseModel):
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    mode: str
    watched_seconds: int
    qualified: bool
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class StreamAnalyticsDetailResponse(BaseModel):
    stream_id: str
    watchers: list[WatcherDetail]
    live_qualified_watchers: int = 0
    rewatch_qualified_watchers: int = 0
    total_qualified_watchers: int = 0
    total_watched_minutes: int = 0
