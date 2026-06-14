import shutil
import uuid
import alembic.config
from unittest import IsolatedAsyncioTestCase

from fastapi.testclient import TestClient
from sqlalchemy import select
from core.security import generate_token_from_user
from models import engine, db, get_db_sync, get_db_sync_for_test
from models.Organizer import Organizer
from models.OrganizerType import OrganizerType
from models.User import MANAGEMENT_PARTICIPANT, User
from main import app
from schemas.organizer import OrganizerUserSchema
from settings import FILE_STORAGE_PATH


class TestOrganizer(IsolatedAsyncioTestCase):
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

    async def test_get_all_organizers(self):
        # Given
        user_management = User(
            id="123e4567-e89b-12d3-a456-426614174000",
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
        )
        self.db.add(user_management)
        organizer_type = OrganizerType(name="Core Team")
        self.db.add(organizer_type)
        user_1 = User(
            username="John Organizer",
            first_name="John",
            last_name="Organizer",
            bio="An organizer",
            profile_picture="http://example.com/photo.jpg",
            email="john@pycon.id",
            instagram_username="http://instagram.com/johnorg",
            twitter_username="http://x.com/johnorg",
        )
        self.db.add(user_1)
        organizer1 = Organizer(
            user=user_1,
            organizer_type=organizer_type,
        )
        self.db.add(organizer1)
        self.db.commit()

        user_2 = User(
            username="Jane Organizer",
            first_name="Jane",
            last_name="Organizer",
            bio="An organizer",
            profile_picture="http://example.com/photo.jpg",
            email="jane@pycon.id",
            instagram_username="http://instagram.com/janeorg",
            twitter_username="http://x.com/janeorg",
        )
        self.db.add(user_2)
        organizer2 = Organizer(
            user=user_2,
            organizer_type=organizer_type,
        )
        self.db.add(organizer2)
        self.db.commit()

        (token, _) = await generate_token_from_user(db=self.db, user=user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(
            "/organizer/",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["results"])

    async def test_get_organizer_by_id(self):
        # Given
        user_management = User(
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
        )
        self.db.add(user_management)
        user_non_management = User(
            username="non_admin",
            participant_type=None,
        )
        self.db.add(user_non_management)
        organizer_type = OrganizerType(name="Core Team")
        self.db.add(organizer_type)
        user = User(
            username="John Organizer",
            first_name="John",
            last_name="Organizer",
            bio="An organizer",
            profile_picture="http://example.com/photo.jpg",
            email="john@gmail.com",
            instagram_username="http://instagram.com/johnorg",
            twitter_username="http://x.com/johnorg",
        )
        self.db.add(user)
        organizer = Organizer(
            user=user,
            organizer_type=organizer_type,
        )
        self.db.add(organizer)
        self.db.commit()

        (token, _) = await generate_token_from_user(db=self.db, user=user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1 - Management user can get organizer
        response = client.get(
            f"/organizer/{organizer.id}", headers={"Authorization": f"Bearer {token}"}
        )

        # Expect 1
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(organizer.id))

        # When 2 - Non-management user cannot get organizer
        (token, _) = await generate_token_from_user(
            db=self.db, user=user_non_management
        )
        response = client.get(
            f"/organizer/{organizer.id}", headers={"Authorization": f"Bearer {token}"}
        )

        # Expect 2
        self.assertEqual(response.status_code, 403)

    async def test_create_organizer(self):
        # Given
        user_management = User(
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
        )
        self.db.add(user_management)
        user_non_management = User(
            username="non_admin",
            participant_type=None,
        )
        self.db.add(user_non_management)
        organizer_type = OrganizerType(name="Core Team")
        self.db.add(organizer_type)
        self.db.commit()

        (token, _) = await generate_token_from_user(db=self.db, user=user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1 - Management user creates organizer
        response = client.post(
            "/organizer/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "user_id": str(user_non_management.id),
                "organizer_type_id": str(organizer_type.id),
            },
        )

        # Expect 1
        self.assertEqual(response.status_code, 200)
        stmt = select(Organizer).where(Organizer.user_id == user_non_management.id)
        organizer = self.db.execute(stmt).scalar()
        self.assertIsNotNone(organizer)
        if organizer is not None:
            self.assertEqual(organizer.organizer_type_id, organizer_type.id)

        # When 2 - Non-management user cannot create organizer
        user_another = User(
            username="another_user",
            participant_type=None,
        )
        self.db.add(user_another)
        self.db.commit()

        (token, _) = await generate_token_from_user(
            db=self.db, user=user_non_management
        )
        response = client.post(
            "/organizer/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "user_id": str(user_another.id),
                "organizer_type_id": str(organizer_type.id),
            },
        )

        # Expect 2
        self.assertEqual(response.status_code, 403)

    async def test_create_organizer_duplicate_user(self):
        # Given
        user_management = User(
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
        )
        self.db.add(user_management)
        user_organizer = User(
            username="user_organizer",
            participant_type=None,
        )
        self.db.add(user_organizer)
        organizer_type = OrganizerType(name="Core Team")
        self.db.add(organizer_type)
        organizer = Organizer(
            user=user_organizer,
            organizer_type=organizer_type,
        )
        self.db.add(organizer)
        self.db.commit()

        (token, _) = await generate_token_from_user(db=self.db, user=user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When - Try to create organizer for user who is already an organizer
        response = client.post(
            "/organizer/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "user_id": str(user_organizer.id),
                "organizer_type_id": str(organizer_type.id),
            },
        )

        # Expect
        self.assertEqual(response.status_code, 400)

    async def test_get_users_for_organizer(self):
        # Given
        user_management = User(
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
            email="admin@pycon.id",
        )
        self.db.add(user_management)
        user_non_management = User(
            username="non_admin",
            participant_type=None,
            email="nonadmin@pycon.id",
        )
        self.db.add(user_non_management)

        user_available_1 = User(
            username="alice",
            first_name="Alice",
            last_name="Available",
            email="alice@pycon.id",
        )
        self.db.add(user_available_1)
        user_available_2 = User(
            username="bob",
            first_name="Bob",
            last_name="Available",
            email="bob@pycon.id",
        )
        self.db.add(user_available_2)

        organizer_type = OrganizerType(name="Core Team")
        self.db.add(organizer_type)

        self.db.add(Organizer(user=user_management, organizer_type=organizer_type))
        self.db.add(Organizer(user=user_non_management, organizer_type=organizer_type))
        self.db.commit()

        (management_token, _) = await generate_token_from_user(
            db=self.db, user=user_management
        )
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1 - Management user gets available users
        # Only show user thats not already assign as organizer
        response = client.get(
            "/organizer/user/",
            headers={"Authorization": f"Bearer {management_token}"},
        )

        # Expect 1
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(
            response.json(),
            OrganizerUserSchema(
                results=[
                    OrganizerUserSchema.UserSchema(
                        id=str(user_available_1.id),
                        username=user_available_1.username,
                        first_name=user_available_1.first_name,
                        last_name=user_available_1.last_name,
                        email=user_available_1.email,
                    ),
                    OrganizerUserSchema.UserSchema(
                        id=str(user_available_2.id),
                        username=user_available_2.username,
                        first_name=user_available_2.first_name,
                        last_name=user_available_2.last_name,
                        email=user_available_2.email,
                    ),
                ]
            ).model_dump(),
        )

        # When 2 - Search by user identity
        # Show searched user by user
        response = client.get(
            "/organizer/user/",
            headers={"Authorization": f"Bearer {management_token}"},
            params={"search": "bob"},
        )

        # Expect 2
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(
            response.json(),
            OrganizerUserSchema(
                results=[
                    OrganizerUserSchema.UserSchema(
                        id=str(user_available_2.id),
                        username=user_available_2.username,
                        first_name=user_available_2.first_name,
                        last_name=user_available_2.last_name,
                        email=user_available_2.email,
                    )
                ]
            ).model_dump(),
        )

        # When 3 - Non-management user cannot access
        (non_management_token, _) = await generate_token_from_user(
            db=self.db, user=user_available_1
        )
        response = client.get(
            "/organizer/user/",
            headers={"Authorization": f"Bearer {non_management_token}"},
        )

        # Expect 3
        self.assertEqual(response.status_code, 403)

    async def test_update_organizer(self):
        # Given
        user_management = User(
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
        )
        self.db.add(user_management)
        user_non_management = User(
            username="non_admin",
            participant_type=None,
        )
        self.db.add(user_non_management)
        organizer_type1 = OrganizerType(name="Core Team")
        organizer_type2 = OrganizerType(name="Volunteer")
        self.db.add(organizer_type1)
        self.db.add(organizer_type2)
        user = User(
            username="John Organizer",
            first_name="John",
            last_name="Organizer",
            bio="An organizer",
            profile_picture="http://example.com/photo.jpg",
            email="john@gmail.com",
            instagram_username="http://instagram.com/johnorg",
            twitter_username="http://x.com/johnorg",
        )
        self.db.add(user)
        organizer = Organizer(
            user=user,
            organizer_type=organizer_type1,
        )
        self.db.add(organizer)
        self.db.commit()

        (token, _) = await generate_token_from_user(db=self.db, user=user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1 - Management user updates organizer
        response = client.put(
            f"/organizer/{organizer.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "organizer_type_id": str(organizer_type2.id),
            },
        )
        print(response.json())

        # Expect 1
        self.assertEqual(response.status_code, 200)
        self.db.refresh(organizer)
        self.assertEqual(organizer.organizer_type_id, organizer_type2.id)

        # When 2 - Non-management user cannot update organizer
        (token, _) = await generate_token_from_user(
            db=self.db, user=user_non_management
        )
        response = client.put(
            f"/organizer/{organizer.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "organizer_type_id": str(organizer_type1.id),
            },
        )

        # Expect 2
        self.assertEqual(response.status_code, 403)

    async def test_delete_organizer(self):
        # Given
        user_management = User(
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
        )
        self.db.add(user_management)
        user_non_management = User(
            username="non_admin",
            participant_type=None,
        )
        self.db.add(user_non_management)
        organizer_type = OrganizerType(name="Core Team")
        self.db.add(organizer_type)
        user = User(
            username="John Organizer",
            first_name="John",
            last_name="Organizer",
            bio="An organizer",
            profile_picture="http://example.com/photo.jpg",
            email="john@gmail.com",
            instagram_username="http://instagram.com/johnorg",
            twitter_username="http://x.com/johnorg",
        )
        organizer = Organizer(
            id=uuid.uuid4(),
            user=user,
            organizer_type=organizer_type,
        )
        self.db.add(organizer)
        self.db.commit()

        (token, _) = await generate_token_from_user(db=self.db, user=user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1 - Management user deletes organizer
        response = client.delete(
            f"/organizer/{str(organizer.id)}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect 1
        self.assertEqual(response.status_code, 200)
        stmt = select(Organizer).where(Organizer.id == organizer.id)
        deleted_organizer = self.db.execute(stmt).scalar()
        self.assertIsNone(deleted_organizer)

        # When 2 - Non-management user cannot delete organizer
        (token, _) = await generate_token_from_user(
            db=self.db, user=user_non_management
        )
        response = client.delete(
            "/organizer/123e4567-e89b-12d3-a456-426614174000",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect 2
        self.assertEqual(response.status_code, 403)

    async def test_get_organizer_profile_picture(self):
        # Given
        user = User(
            username="John Organizer",
            first_name="John",
            last_name="Organizer",
            bio="An organizer",
            profile_picture=None,
            email="john@gmail.com",
            instagram_username="http://instagram.com/johnorg",
            twitter_username="http://x.com/johnorg",
        )
        organizer_type = OrganizerType(name="Core Team")
        self.db.add(organizer_type)
        organizer = Organizer(
            id=uuid.uuid4(),
            user=user,
            organizer_type=organizer_type,
        )
        self.db.add(organizer)
        self.db.commit()
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1 - Profile picture not found
        response = client.get(
            f"/organizer/{str(organizer.id)}/profile-picture",
        )

        # Expect 1
        self.assertEqual(response.status_code, 404)

        # Given 2 - Copy profile picture file
        shutil.copyfile(
            "./routes/tests/data/bandungpy.jpg",
            f"./{FILE_STORAGE_PATH}/bandungpy.jpg",
        )
        user.profile_picture = "bandungpy.jpg"
        self.db.add(user)
        self.db.commit()

        # When 2 - Profile picture found
        response = client.get(
            f"/organizer/{str(organizer.id)}/profile-picture",
        )

        # Expect 2
        self.assertEqual(response.status_code, 200)

    async def test_find_organizer_by_id_not_found(self):
        # Given
        user_management = User(
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
        )
        self.db.add(user_management)
        self.db.commit()

        (token, _) = await generate_token_from_user(db=self.db, user=user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When - Management user tries to get non-existent organizer
        response = client.get(
            "/organizer/123e4567-e89b-12d3-a456-426614174999",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["message"], "Organizer not found")

    async def test_find_organizer_by_id_response_structure(self):
        # Given
        user_management = User(
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
        )
        self.db.add(user_management)
        organizer_type = OrganizerType(name="Core Team")
        self.db.add(organizer_type)
        user = User(
            username="John Organizer",
            first_name="John",
            last_name="Organizer",
            bio="An organizer",
            profile_picture="http://example.com/photo.jpg",
            email="john@gmail.com",
            instagram_username="http://instagram.com/johnorg",
            twitter_username="http://x.com/johnorg",
        )
        self.db.add(user)
        organizer = Organizer(
            user=user,
            organizer_type=organizer_type,
        )
        self.db.add(organizer)
        self.db.commit()

        (token, _) = await generate_token_from_user(db=self.db, user=user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When
        response = client.get(
            f"/organizer/{organizer.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn("id", response_data)
        self.assertIn("user", response_data)
        self.assertIn("organizer_type", response_data)
        self.assertEqual(response_data["id"], str(organizer.id))

    async def test_find_organizer_by_id_without_authorization_header(self):
        # Given
        organizer_type = OrganizerType(name="Core Team")
        self.db.add(organizer_type)
        user = User(
            username="John Organizer",
            first_name="John",
            last_name="Organizer",
            bio="An organizer",
            profile_picture="http://example.com/photo.jpg",
            email="john@gmail.com",
            instagram_username="http://instagram.com/johnorg",
            twitter_username="http://x.com/johnorg",
        )
        self.db.add(user)
        organizer = Organizer(
            user=user,
            organizer_type=organizer_type,
        )
        self.db.add(organizer)
        self.db.commit()

        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When - No authorization header provided
        response = client.get(
            f"/organizer/{organizer.id}",
        )

        # Expect
        self.assertEqual(response.status_code, 401)

    def tearDown(self):
        self.db.close()

        # rollback - everything that happened with the
        # Session above (including calls to commit())
        # is rolled back.
        self.trans.rollback()

        # return connection to the Engine
        self.connection.close()
