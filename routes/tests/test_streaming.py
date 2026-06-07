import uuid
from datetime import datetime, timedelta
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import alembic.config
from fastapi.testclient import TestClient

from core.security import generate_token_from_user
from main import app
from models import db, engine, get_db_sync, get_db_sync_for_test
from models.Room import Room
from models.Schedule import Schedule
from models.ScheduleType import ScheduleType
from models.Speaker import Speaker
from models.SpeakerType import SpeakerType
from models.Stream import Stream, StreamStatus
from models.StreamWatchSession import StreamWatchSession, WatchMode
from models.User import MANAGEMENT_PARTICIPANT, User
from schemas.user_profile import ParticipantType


class TestStreaming(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        alembic_args = ["upgrade", "head"]
        alembic.config.main(argv=alembic_args)
        # connect to the database
        self.connection = engine.connect()

        # begin a non-ORM transaction
        self.trans = self.connection.begin()

        # bind an individual Session to the connection, selecting
        # "create_savepoint" join_transaction_mode
        self.db = db(bind=self.connection, join_transaction_mode="create_savepoint")

        # Create test data
        self.user_management = User(
            id="123e4567-e89b-12d3-a456-426614174000",
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
        )
        self.db.add(self.user_management)

        self.user_participant = User(
            username="participant_user",
            participant_type=ParticipantType.ONLINE,
        )
        self.db.add(self.user_participant)

        self.user_non_participant = User(
            username="non_participant",
            participant_type=None,
        )
        self.db.add(self.user_non_participant)

        self.speaker_type = SpeakerType(name="Keynote Speaker")
        self.db.add(self.speaker_type)

        self.room = Room(name="Main Hall")
        self.db.add(self.room)

        self.schedule_type = ScheduleType(name="Talk")
        self.db.add(self.schedule_type)

        self.user_speaker = User(
            username="speaker_user",
            first_name="Jane",
            last_name="Doe",
            bio="Expert speaker",
        )
        self.db.add(self.user_speaker)

        self.speaker = Speaker(
            user=self.user_speaker,
            speaker_type=self.speaker_type,
        )
        self.db.add(self.speaker)

        self.db.commit()

    @patch("core.mux_service.mux_service.get_public_playback_url")
    @patch("core.mux_service.mux_service.get_public_thumbnail_url")
    async def test_get_stream_playback_public_streaming(
        self, mock_get_thumbnail, mock_get_playback
    ):
        # Given
        mock_get_playback.return_value = "https://stream.mux.com/playback_123.m3u8"
        mock_get_thumbnail.return_value = (
            "https://image.mux.com/playback_123/thumbnail.jpg"
        )

        start_time = datetime.now() + timedelta(hours=1)
        end_time = start_time + timedelta(hours=1)

        schedule = Schedule(
            title="Test Schedule",
            speaker_id=self.speaker.id,
            room_id=self.room.id,
            schedule_type_id=self.schedule_type.id,
            description="Test description",
            presentation_language="English",
            slide_language="English",
            tags=["python"],
            start=start_time,
            end=end_time,
        )
        self.db.add(schedule)
        self.db.commit()

        stream = Stream(
            schedule_id=schedule.id,
            is_public=True,
            mux_live_stream_id="mux_stream_123",
            mux_playback_id="playback_123",
            mux_stream_key="stream_key_123",
            status=StreamStatus.STREAMING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.db.add(stream)
        self.db.commit()

        token, _ = await generate_token_from_user(
            db=self.db, user=self.user_participant
        )
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(
            f"/streaming/{stream.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["playback"]["id"], "playback_123")
        self.assertEqual(
            data["playback"]["url"], "https://stream.mux.com/playback_123.m3u8"
        )
        self.assertIsNone(data["playback"]["token"])
        self.assertEqual(data["status"], StreamStatus.STREAMING.value)
        mock_get_playback.assert_called_once_with("playback_123")
        mock_get_thumbnail.assert_called_once_with("playback_123")

    @patch("core.mux_service.mux_service.get_public_playback_url")
    @patch("core.mux_service.mux_service.get_public_thumbnail_url")
    async def test_get_stream_playback_public_ready(
        self, mock_get_thumbnail, mock_get_playback
    ):
        # Given
        mock_get_playback.return_value = "https://stream.mux.com/playback_123.m3u8"
        mock_get_thumbnail.return_value = (
            "https://image.mux.com/playback_123/thumbnail.jpg"
        )

        start_time = datetime.now() + timedelta(hours=1)
        end_time = start_time + timedelta(hours=1)

        schedule = Schedule(
            title="Test Schedule",
            speaker_id=self.speaker.id,
            room_id=self.room.id,
            schedule_type_id=self.schedule_type.id,
            description="Test description",
            presentation_language="English",
            slide_language="English",
            tags=["python"],
            start=start_time,
            end=end_time,
        )
        self.db.add(schedule)
        self.db.commit()

        stream = Stream(
            schedule_id=schedule.id,
            is_public=True,
            mux_live_stream_id="mux_stream_123",
            mux_playback_id="playback_123",
            mux_stream_key="stream_key_123",
            status=StreamStatus.READY,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.db.add(stream)
        self.db.commit()

        token, _ = await generate_token_from_user(
            db=self.db, user=self.user_participant
        )
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(
            f"/streaming/{stream.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], StreamStatus.READY.value)

    @patch("core.mux_service.mux_service.get_public_playback_url")
    @patch("core.mux_service.mux_service.get_public_thumbnail_url")
    async def test_get_stream_playback_ended_with_asset(
        self, mock_get_thumbnail, mock_get_playback
    ):
        # Given
        mock_get_playback.return_value = (
            "https://stream.mux.com/asset_playback_456.m3u8"
        )
        mock_get_thumbnail.return_value = (
            "https://image.mux.com/asset_playback_456/thumbnail.jpg"
        )

        start_time = datetime.now() - timedelta(hours=2)
        end_time = start_time + timedelta(hours=1)

        schedule = Schedule(
            title="Ended Schedule",
            speaker_id=self.speaker.id,
            room_id=self.room.id,
            schedule_type_id=self.schedule_type.id,
            description="Test description",
            presentation_language="English",
            slide_language="English",
            tags=["python"],
            start=start_time,
            end=end_time,
        )
        self.db.add(schedule)
        self.db.commit()

        stream = Stream(
            schedule_id=schedule.id,
            is_public=True,
            mux_live_stream_id="mux_stream_123",
            mux_playback_id="playback_123",
            mux_stream_key="stream_key_123",
            mux_asset_id="asset_123",
            mux_asset_playback_id="asset_playback_456",
            status=StreamStatus.ENDED,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.db.add(stream)
        self.db.commit()

        token, _ = await generate_token_from_user(
            db=self.db, user=self.user_participant
        )
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(
            f"/streaming/{stream.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["playback"]["id"], "asset_playback_456")
        self.assertEqual(data["status"], StreamStatus.ENDED.value)
        mock_get_playback.assert_called_once_with("asset_playback_456")

    @patch("core.mux_service.mux_service.generate_signed_playback_url")
    @patch("core.mux_service.mux_service.generate_signed_thumbnail_url")
    async def test_get_stream_playback_private(
        self, mock_get_thumbnail, mock_get_playback
    ):
        # Given
        mock_get_playback.return_value = (
            "playback_token_123",
            "https://stream.mux.com/playback_123.m3u8?token=playback_token_123",
            datetime.now() + timedelta(hours=1),
        )
        mock_get_thumbnail.return_value = (
            "thumbnail_token_123",
            "https://image.mux.com/playback_123/thumbnail.jpg?token=thumbnail_token_123",
            None,
        )

        start_time = datetime.now() + timedelta(hours=1)
        end_time = start_time + timedelta(hours=1)

        schedule = Schedule(
            title="Private Stream Schedule",
            speaker_id=self.speaker.id,
            room_id=self.room.id,
            schedule_type_id=self.schedule_type.id,
            description="Test description",
            presentation_language="English",
            slide_language="English",
            tags=["python"],
            start=start_time,
            end=end_time,
        )
        self.db.add(schedule)
        self.db.commit()

        stream = Stream(
            schedule_id=schedule.id,
            is_public=False,
            mux_live_stream_id="mux_stream_123",
            mux_playback_id="playback_123",
            mux_stream_key="stream_key_123",
            status=StreamStatus.STREAMING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.db.add(stream)
        self.db.commit()

        token, _ = await generate_token_from_user(
            db=self.db, user=self.user_participant
        )
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(
            f"/streaming/{stream.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["playback"]["token"], "playback_token_123")
        self.assertIn("token=playback_token_123", data["playback"]["url"])
        mock_get_playback.assert_called_once_with(
            "playback_123", user_id=self.user_participant.id
        )

    async def test_get_stream_playback_unauthorized(self):
        # Given
        start_time = datetime.now() + timedelta(hours=1)
        end_time = start_time + timedelta(hours=1)

        schedule = Schedule(
            title="Test Schedule",
            speaker_id=self.speaker.id,
            room_id=self.room.id,
            schedule_type_id=self.schedule_type.id,
            description="Test description",
            presentation_language="English",
            slide_language="English",
            tags=["python"],
            start=start_time,
            end=end_time,
        )
        self.db.add(schedule)
        self.db.commit()

        stream = Stream(
            schedule_id=schedule.id,
            is_public=True,
            mux_live_stream_id="mux_stream_123",
            mux_playback_id="playback_123",
            mux_stream_key="stream_key_123",
            status=StreamStatus.STREAMING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.db.add(stream)
        self.db.commit()

        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(f"/streaming/{stream.id}")

        # Expect
        self.assertEqual(response.status_code, 401)

    async def test_get_stream_playback_non_participant(self):
        # Given
        start_time = datetime.now() + timedelta(hours=1)
        end_time = start_time + timedelta(hours=1)

        schedule = Schedule(
            title="Test Schedule",
            speaker_id=self.speaker.id,
            room_id=self.room.id,
            schedule_type_id=self.schedule_type.id,
            description="Test description",
            presentation_language="English",
            slide_language="English",
            tags=["python"],
            start=start_time,
            end=end_time,
        )
        self.db.add(schedule)
        self.db.commit()

        stream = Stream(
            schedule_id=schedule.id,
            is_public=True,
            mux_live_stream_id="mux_stream_123",
            mux_playback_id="playback_123",
            mux_stream_key="stream_key_123",
            status=StreamStatus.STREAMING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.db.add(stream)
        self.db.commit()

        token, _ = await generate_token_from_user(
            db=self.db, user=self.user_non_participant
        )
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(
            f"/streaming/{stream.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 400)
        self.assertIn("purchase a ticket", response.json()["message"])

    async def test_get_stream_playback_not_found(self):
        # Given
        token, _ = await generate_token_from_user(
            db=self.db, user=self.user_participant
        )
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())

        # When
        response = client.get(
            f"/streaming/{non_existent_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 404)

    # async def test_get_stream_playback_pending_status(self):
    #     # Given
    #     start_time = datetime.now() + timedelta(hours=1)
    #     end_time = start_time + timedelta(hours=1)

    #     schedule = Schedule(
    #         title="Pending Stream",
    #         speaker_id=self.speaker.id,
    #         room_id=self.room.id,
    #         schedule_type_id=self.schedule_type.id,
    #         description="Test description",
    #         presentation_language="English",
    #         slide_language="English",
    #         tags=["python"],
    #         start=start_time,
    #         end=end_time,
    #     )
    #     self.db.add(schedule)
    #     self.db.commit()

    #     stream = Stream(
    #         schedule_id=schedule.id,
    #         is_public=True,
    #         mux_live_stream_id="mux_stream_123",
    #         mux_playback_id="playback_123",
    #         mux_stream_key="stream_key_123",
    #         status=StreamStatus.PENDING,
    #         created_at=datetime.now(),
    #         updated_at=datetime.now(),
    #     )
    #     self.db.add(stream)
    #     self.db.commit()

    #     token, _ = await generate_token_from_user(
    #         db=self.db, user=self.user_participant
    #     )
    #     app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
    #     client = TestClient(app)

    #     # When
    #     response = client.get(
    #         f"/streaming/{stream.id}",
    #         headers={"Authorization": f"Bearer {token}"},
    #     )

    #     # Expect
    #     self.assertEqual(response.status_code, 400)
    #     self.assertIn("not ready for playback", response.json()["message"])

    async def test_get_stream_playback_deleted_schedule(self):
        # Given
        start_time = datetime.now() + timedelta(hours=1)
        end_time = start_time + timedelta(hours=1)

        schedule = Schedule(
            title="Deleted Schedule",
            speaker_id=self.speaker.id,
            room_id=self.room.id,
            schedule_type_id=self.schedule_type.id,
            description="Test description",
            presentation_language="English",
            slide_language="English",
            tags=["python"],
            start=start_time,
            end=end_time,
            deleted_at=datetime.now(),
        )
        self.db.add(schedule)
        self.db.commit()

        stream = Stream(
            schedule_id=schedule.id,
            is_public=True,
            mux_live_stream_id="mux_stream_123",
            mux_playback_id="playback_123",
            mux_stream_key="stream_key_123",
            status=StreamStatus.STREAMING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.db.add(stream)
        self.db.commit()

        token, _ = await generate_token_from_user(
            db=self.db, user=self.user_participant
        )
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(
            f"/streaming/{stream.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 404)

    async def test_get_streaming_analytics_summary_includes_overall(self):
        # Given
        user_participant_two = User(
            username="participant_user_two",
            participant_type=ParticipantType.ONLINE,
        )
        self.db.add(user_participant_two)

        start_time = datetime.now() - timedelta(hours=2)
        end_time = start_time + timedelta(hours=1)

        schedule_one = Schedule(
            title="First Stream Schedule",
            speaker_id=self.speaker.id,
            room_id=self.room.id,
            schedule_type_id=self.schedule_type.id,
            description="Test description",
            presentation_language="English",
            slide_language="English",
            tags=["python"],
            start=start_time,
            end=end_time,
        )
        schedule_two = Schedule(
            title="Second Stream Schedule",
            speaker_id=self.speaker.id,
            room_id=self.room.id,
            schedule_type_id=self.schedule_type.id,
            description="Test description",
            presentation_language="English",
            slide_language="English",
            tags=["python"],
            start=start_time,
            end=end_time,
        )
        self.db.add(schedule_one)
        self.db.add(schedule_two)
        self.db.commit()

        stream_one = Stream(
            schedule_id=schedule_one.id,
            is_public=True,
            mux_live_stream_id="mux_stream_analytics_1",
            mux_playback_id="playback_analytics_1",
            mux_stream_key="stream_key_analytics_1",
            status=StreamStatus.ENDED,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        stream_two = Stream(
            schedule_id=schedule_two.id,
            is_public=True,
            mux_live_stream_id="mux_stream_analytics_2",
            mux_playback_id="playback_analytics_2",
            mux_stream_key="stream_key_analytics_2",
            status=StreamStatus.ENDED,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.db.add(stream_one)
        self.db.add(stream_two)
        self.db.commit()

        now = datetime.now()
        self.db.add_all(
            [
                StreamWatchSession(
                    stream_id=stream_one.id,
                    schedule_id=schedule_one.id,
                    user_id=self.user_participant.id,
                    mode=WatchMode.LIVE,
                    started_at=now,
                    last_heartbeat_at=now,
                    ended_at=now,
                    watched_seconds=120,
                    last_position_seconds=120,
                    qualified=True,
                    client_session_id="analytics-live-1",
                    created_at=now,
                    updated_at=now,
                ),
                StreamWatchSession(
                    stream_id=stream_two.id,
                    schedule_id=schedule_two.id,
                    user_id=user_participant_two.id,
                    mode=WatchMode.REWATCH,
                    started_at=now,
                    last_heartbeat_at=now,
                    ended_at=now,
                    watched_seconds=180,
                    last_position_seconds=180,
                    qualified=True,
                    client_session_id="analytics-rewatch-1",
                    created_at=now,
                    updated_at=now,
                ),
                StreamWatchSession(
                    stream_id=stream_two.id,
                    schedule_id=schedule_two.id,
                    user_id=self.user_participant.id,
                    mode=WatchMode.REWATCH,
                    started_at=now,
                    last_heartbeat_at=now,
                    ended_at=now,
                    watched_seconds=30,
                    last_position_seconds=30,
                    qualified=False,
                    client_session_id="analytics-unqualified-1",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        self.db.commit()

        token, _ = await generate_token_from_user(db=self.db, user=self.user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(
            "/admin/streaming/analytics/summary",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["overall"]["live_qualified_watchers"], 1)
        self.assertEqual(data["overall"]["rewatch_qualified_watchers"], 1)
        self.assertEqual(data["overall"]["total_qualified_watchers"], 2)
        self.assertEqual(data["overall"]["total_watched_minutes"], 5)
        self.assertGreaterEqual(len(data["streams"]), 2)

    def tearDown(self) -> None:
        self.db.close()

        # rollback - everything that happened with the
        # Session above (including calls to commit())
        # is rolled back.
        self.trans.rollback()

        # return connection to the Engine
        self.connection.close()
