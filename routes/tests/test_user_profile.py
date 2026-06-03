from pydantic import ValidationError
import alembic.config
from unittest import IsolatedAsyncioTestCase

from fastapi.testclient import TestClient
from core.security import generate_hash_password, generate_token_from_user
from models import engine, db, get_db_sync, get_db_sync_for_test
from models.City import City
from models.Country import Country
from models.State import State
from models.User import MANAGEMENT_PARTICIPANT, User
from main import app
from schemas.user_profile import (
    DetailSearchUserProfile,
    JobCategory,
    SearchUserProfileResponse,
    UserProfileCreate,
    UserProfileDB,
)


class TestUserProfile(IsolatedAsyncioTestCase):
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

    async def test_search_user_profiles(self):
        # Given
        user_management = User(
            id="123e4567-e89b-12d3-a456-426614174000",
            username="admin",
            participant_type=MANAGEMENT_PARTICIPANT,
            email="admin@local.com",
        )
        self.db.add(user_management)
        new_user1 = User(
            id="223e4567-e89b-12d3-a456-426614174000",
            first_name="Test",
            last_name="User1",
            username="testuser1",
            email="testuser1@local.com",
        )
        self.db.add(new_user1)
        new_user2 = User(
            id="61df5dec-7c9d-4c93-9fc6-f5d82c420b58",
            first_name="Test",
            last_name="User2",
            username="testuser2",
            email="testuser2@local.com",
        )
        self.db.add(new_user2)
        new_user3 = User(
            id="2996c5c0-a01d-4eab-a28d-a4ea9875780b",
            first_name="Test",
            last_name="User3",
            username="testuser3",
            email="testuser3@local.com",
            participant_type="Speaker",
        )
        self.db.add(new_user3)
        self.db.commit()
        all_user = sorted(
            [user_management, new_user1, new_user2, new_user3], key=lambda u: u.email
        )
        (token, _) = await generate_token_from_user(db=self.db, user=user_management)
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1
        response = client.get(
            "/user-profile/search/", headers={"Authorization": f"Bearer {token}"}
        )

        # Expect 1
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(
            response.json(),
            SearchUserProfileResponse(
                results=[
                    DetailSearchUserProfile(
                        id=str(user.id),
                        username=user.username,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        email=user.email,
                    )
                    for user in all_user
                ]
            ).model_dump(),
        )

        # When 2
        response = client.get(
            "/user-profile/search/",
            headers={"Authorization": f"Bearer {token}"},
            params={"search": "user"},
        )

        # Expect 2
        all_user = sorted([new_user1, new_user2, new_user3], key=lambda u: u.email)
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(
            response.json(),
            SearchUserProfileResponse(
                results=[
                    DetailSearchUserProfile(
                        id=str(user.id),
                        username=user.username,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        email=user.email,
                    )
                    for user in all_user
                ]
            ).model_dump(),
        )

        # When 3
        response = client.get(
            "/user-profile/search/",
            headers={"Authorization": f"Bearer {token}"},
            params={"search": "user", "participant_type": "Speaker"},
        )

        # Expect 3
        all_user = sorted([new_user3], key=lambda u: u.email)
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(
            response.json(),
            SearchUserProfileResponse(
                results=[
                    DetailSearchUserProfile(
                        id=str(user.id),
                        username=user.username,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        email=user.email,
                    )
                    for user in all_user
                ]
            ).model_dump(),
        )

    async def test_update_user_profile(self):
        # Given
        new_user = User(
            username="testuser",
            email="testuser@local.com",
            password=generate_hash_password("password"),
            is_active=True,
        )
        self.db.add(new_user)

        dummy_country = Country(id=1, name="Indonesia", iso2="ID", iso3="IDN")
        self.db.merge(dummy_country)

        self.db.commit()
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)
        response = client.post(
            "/auth/email/signin/",
            json={"email": "testuser@local.com", "password": "password"},
        )
        token = response.json().get("token", None)

        # When 1
        response = client.put(
            "/user-profile/",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "profile_picture": (
                    "profile.jpg",
                    open("./routes/tests/data/bandungpy.jpg", "rb"),
                )
            },
            data={
                "first_name": "Citra",
                "last_name": "Wijaya",
                "email": "citra.w@email.com",
                "bio": "A creative designer focused on user experience and interface design.",
                "job_category": "Tech - Specialist",
                "job_title": "UI/UX Designer",
                "country_id": 1,
                "interest": "figma, design thinking, user research",  # Akan diubah jadi list
                "coc_acknowledged": True,
                "terms_agreed": True,
                "privacy_agreed": True,
                "share_my_location": True,
                "share_my_email_and_phone_number": True,
                "share_my_job_and_company": True,
                "share_my_interest": True,
                "share_my_public_social_media": True,
                "share_my_data_to_sponsor": True,
                "retain_my_data_for_next_pycon": True,
            },
        )

        # Expect 1
        self.assertEqual(response.status_code, 200)

        # new_user = self.db.query(User).where(User.email == new_user.email).first()
        # print(new_user.share_my_email_and_phone_number)
        self.assertEqual(new_user.share_my_email_and_phone_number, True)
        self.assertEqual(new_user.share_my_job_and_company, True)
        self.assertEqual(new_user.share_my_interest, True)
        self.assertEqual(new_user.share_my_public_social_media, True)
        self.assertEqual(new_user.share_my_data_to_sponsor, True)
        self.assertEqual(new_user.retain_my_data_for_next_pycon, True)

        # When 2
        response = client.put(
            "/user-profile/",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "profile_picture": (
                    "profile.jpg",
                    open("./routes/tests/data/bandungpy.jpg", "rb"),
                )
            },
            data={
                "profile_picture": "not-a-url",  # URL tidak valid
                "first_name": "Andi",
                "last_name": "Pratama",
                # "email": "andi@.com",  # Email tidak valid
                "bio": "Too short",  # Bio terlalu pendek (min_length=10)
                "job_category": "Tech - Managing",
                "job_title": "Developer Manager",
                "country_id": 1,
                "phone": "081234567890",  # Format telepon salah
                "github_username": "https://github.com/andipratama",  # Seharusnya username saja
                "coc_acknowledged": False,  # Harus True
                "terms_agreed": True,
                "privacy_agreed": True,
                "share_my_location": True,
                "share_my_email_and_phone_number": True,
                "share_my_job_and_company": True,
                "share_my_interest": True,
                "share_my_public_social_media": True,
                "share_my_data_to_sponsor": True,
                "retain_my_data_for_next_pycon": True,
            },
        )

        # Expect 2
        self.assertEqual(response.status_code, 422)

        # When 3
        response = client.get(
            f"/user-profile/{token}/profile-picture/",
        )

        # Expect 3
        self.assertEqual(response.status_code, 200)

    async def test_get_user_profile(self):
        # Given
        new_user = User(
            username="testuser",
            email="testuser@local.com",
            password=generate_hash_password("password"),
            # participant_type=MANAGEMENT_PARTICIPANT,
            is_active=True,
        )
        self.db.add(new_user)
        self.db.commit()
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)
        response = client.post(
            "/auth/email/signin/",
            json={"email": "testuser@local.com", "password": "password"},
        )
        token = response.json().get("token", None)

        # When 1
        response = client.get("/user-profile")
        # Expect 1
        # asser public profile checked
        self.assertEqual(response.status_code, 401)

        # When 2
        response = client.get(
            "/user-profile", headers={"Authorization": f"Bearer {token}"}
        )
        # Expect 2
        self.assertEqual(response.status_code, 200)
        self.assertIn("experience", response.json())
        self.assertIn("industry_categories", response.json())
        self.assertIn("gender", response.json())
        self.assertIn("city", response.json())
        self.assertIn("zip_code", response.json())
        self.assertIn("address", response.json())
        self.assertIn("date_of_birth", response.json())
        self.assertIn("t_shirt_size", response.json())
        self.assertIn("email", response.json())
        self.assertIn("phone", response.json())
        self.assertIn("github_username", response.json())
        self.assertIn("linkedin_username", response.json())
        self.assertIn("twitter_username", response.json())
        self.assertIn("facebook_username", response.json())
        self.assertNotIn("is_active", response.json())
        self.assertNotIn("created_at", response.json())
        self.assertNotIn("updated_at", response.json())
        self.assertIn("interest", response.json())
        self.assertIn("profile_picture", response.json())
        self.assertIn("first_name", response.json())
        self.assertIn("last_name", response.json())
        self.assertIn("job_category", response.json())
        self.assertIn("job_title", response.json())
        self.assertIn("country", response.json())
        self.assertIn("bio", response.json())
        self.assertIn("participant_type", response.json())
        self.assertIn("coc_acknowledged", response.json())
        self.assertIn("terms_agreed", response.json())
        self.assertIn("privacy_agreed", response.json())
        self.assertIn("share_my_email_and_phone_number", response.json())
        self.assertIn("share_my_job_and_company", response.json())
        self.assertIn("share_my_location", response.json())
        self.assertIn("share_my_interest", response.json())
        self.assertIn("share_my_public_social_media", response.json())
        self.assertIn("share_my_data_to_sponsor", response.json())
        self.assertIn("retain_my_data_for_next_pycon", response.json())

    async def test_update_profile_with_valid_location(self):
        """Test update user profile dengan location hierarchy yang valid"""
        # Given
        new_user = User(
            username="testuser",
            email="testuser@local.com",
            password=generate_hash_password("password"),
            is_active=True,
        )
        self.db.add(new_user)

        country = Country(id=102, name="Indonesia", iso2="ID", iso3="IDN")
        self.db.merge(country)

        state = State(id=1836, name="Jakarta", country_id=102, country_code="ID")
        self.db.merge(state)

        city = City(id=38932, name="Jakarta Pusat", state_id=1836, country_id=102)
        self.db.merge(city)

        self.db.commit()
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)

        client = TestClient(app)
        response = client.post(
            "/auth/email/signin/",
            json={"email": "testuser@local.com", "password": "password"},
        )
        token = response.json().get("token", None)

        # When
        response = client.put(
            "/user-profile/",
            headers={"Authorization": f"Bearer {token}"},
            files={"profile_picture": ("profile.jpg", b"filecontent")},
            data={
                "first_name": "Budi",
                "last_name": "Santoso",
                "email": "budi@email.com",
                "bio": "Software engineer with 5 years experience.",
                "job_category": "Tech - Specialist",
                "job_title": "Backend Developer",
                "country_id": 102,  # Indonesia
                "state_id": 1836,  # Jakarta
                "city_id": 38932,  # Jakarta Pusat
                "interest": "python, fastapi",
                "coc_acknowledged": True,
                "terms_agreed": True,
                "privacy_agreed": True,
            },
        )

        # Expect
        print(response.json())
        self.assertEqual(response.status_code, 200)

    async def test_update_profile_with_invalid_country(self):
        # Given
        new_user = User(
            username="testuser",
            email="testuser@local.com",
            password=generate_hash_password("password"),
            is_active=True,
        )
        self.db.add(new_user)

        country = Country(id=102, name="Indonesia", iso2="ID", iso3="IDN")
        self.db.merge(country)

        state = State(id=1836, name="Jakarta", country_id=102, country_code="ID")
        self.db.merge(state)

        city = City(id=38932, name="Jakarta Pusat", state_id=1836, country_id=102)
        self.db.merge(city)

        self.db.commit()

        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)

        client = TestClient(app)
        response = client.post(
            "/auth/email/signin/",
            json={"email": "testuser@local.com", "password": "password"},
        )
        token = response.json().get("token", None)

        # When
        response = client.put(
            "/user-profile/",
            headers={"Authorization": f"Bearer {token}"},
            files={"profile_picture": ("profile.jpg", b"filecontent")},
            data={
                "first_name": "Budi",
                "last_name": "Santoso",
                "email": "budi@email.com",
                "bio": "Software engineer with 5 years experience.",
                "job_category": "Tech - Specialist",
                "job_title": "Backend Developer",
                "country_id": 999,  # Invalid country!
                "interest": "python, fastapi",
                "coc_acknowledged": True,
                "terms_agreed": True,
                "privacy_agreed": True,
            },
        )

        # Expect
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid country_id", response.json()["message"])

    async def test_update_profile_with_mismatched_state(self):
        # Given
        new_user = User(
            username="testuser",
            email="testuser@local.com",
            password=generate_hash_password("password"),
            is_active=True,
        )
        self.db.add(new_user)

        country = Country(id=102, name="Indonesia", iso2="ID", iso3="IDN")
        self.db.merge(country)

        state = State(id=1836, name="Jakarta", country_id=102, country_code="ID")
        self.db.merge(state)

        city = City(id=38932, name="Jakarta Pusat", state_id=1836, country_id=102)
        self.db.merge(city)

        self.db.commit()

        # Add USA state
        usa_country = Country(id=231, name="United States", iso2="US", iso3="USA")
        self.db.merge(usa_country)
        california = State(
            id=1416, name="California", country_id=231, country_code="US"
        )
        self.db.merge(california)
        self.db.commit()

        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)

        client = TestClient(app)
        response = client.post(
            "/auth/email/signin/",
            json={"email": "testuser@local.com", "password": "password"},
        )
        token = response.json().get("token", None)

        # When
        response = client.put(
            "/user-profile/",
            headers={"Authorization": f"Bearer {token}"},
            files={"profile_picture": ("profile.jpg", b"filecontent")},
            data={
                "first_name": "Budi",
                "last_name": "Santoso",
                "email": "budi@email.com",
                "bio": "Software engineer with 5 years experience.",
                "job_category": "Tech - Specialist",
                "job_title": "Backend Developer",
                "country_id": 102,  # Indonesia
                "state_id": 1416,  # California (USA!) - MISMATCH!
                "interest": "python, fastapi",
                "coc_acknowledged": True,
                "terms_agreed": True,
                "privacy_agreed": True,
            },
        )

        # Expect
        self.assertEqual(response.status_code, 400)
        self.assertIn("does not belong to", response.json()["message"])

    async def test_update_user_profile_null_profile_picture(self):
        # Given
        new_user = User(
            username="testuser",
            email="testuser@local.com",
            password=generate_hash_password("password"),
            profile_picture="existing_profile.png",
            is_active=True,
        )
        self.db.add(new_user)

        dummy_country = Country(id=1, name="Indonesia", iso2="ID", iso3="IDN")
        self.db.merge(dummy_country)

        self.db.commit()
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)
        response = client.post(
            "/auth/email/signin/",
            json={"email": "testuser@local.com", "password": "password"},
        )
        token = response.json().get("token", None)

        # When 1
        response = client.put(
            "/user-profile/",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "first_name": "Citra",
                "last_name": "Wijaya",
                "email": "citra.w@email.com",
                "bio": "A creative designer focused on user experience and interface design.",
                "job_category": "Tech - Specialist",
                "job_title": "UI/UX Designer",
                "country_id": 1,
                "interest": "figma, design thinking, user research",  # Akan diubah jadi list
                "coc_acknowledged": True,
                "terms_agreed": True,
                "privacy_agreed": True,
            },
        )

        # Expect 1
        self.assertEqual(response.status_code, 200)
        self.assertEqual(new_user.profile_picture, "existing_profile.png")

    def tearDown(self):
        self.db.close()

        # rollback - everything that happened with the
        # Session above (including calls to commit())
        # is rolled back.
        self.trans.rollback()

        # return connection to the Engine
        self.connection.close()


class TestUserProfileBase(IsolatedAsyncioTestCase):
    def setUp(self):
        """Menyiapkan data valid yang akan digunakan berulang kali."""
        self.valid_data = {
            "first_name": "Budi",
            "last_name": "Santoso",
            "email": "budi.santoso@example.com",
            "bio": "Seorang software engineer handal dengan pengalaman lebih dari 5 tahun.",
            "job_category": JobCategory.TECH_SPECIALIST,
            "job_title": "Senior Backend Developer",
            "country_id": 1,
            "phone": "+6281234567890",
            "interest": "python, fastapi, testing",
            "github_username": "budisan",
            "coc_acknowledged": True,
            "terms_agreed": True,
            "privacy_agreed": True,
        }

    async def test_valid_data_parses_correctly(self):
        """Tes Happy Path: Memastikan data yang sepenuhnya valid berhasil di-parse."""
        try:
            model = UserProfileCreate(**self.valid_data)
            self.assertEqual(model.first_name, "Budi")
            self.assertEqual(model.phone, "+6281234567890")
            # Cek validator tags
            self.assertEqual(model.interest, ["python", "fastapi", "testing"])
        except ValidationError as e:
            self.fail(f"UserProfileCreate raised ValidationError unexpectedly! \n{e}")

    async def test_missing_required_field_raises_error(self):
        """Tes Validasi Wajib: Memastikan error jika field wajib (first_name) hilang."""
        data = self.valid_data.copy()
        del data["first_name"]
        with self.assertRaises(ValidationError) as context:
            UserProfileCreate(**data)
        # Cek apakah error yang muncul benar untuk field 'first_name'
        self.assertIn("first_name", str(context.exception))

    async def test_field_constraints_validation(self):
        """Tes Validasi Batasan: Menguji min_length, max_length, ge."""
        # Kasus 1: Bio terlalu pendek
        data = self.valid_data.copy()
        data["bio"] = "terlalu"
        with self.assertRaises(
            ValidationError, msg="Bio should be at least 10 characters"
        ):
            UserProfileCreate(**data)

        # Kasus 2: Experience bernilai negatif
        data = self.valid_data.copy()
        data["experience"] = -1
        with self.assertRaises(ValidationError, msg="Experience should be >= 0"):
            UserProfileCreate(**data)

    async def test_phone_number_validator(self):
        """Tes Validasi Kustom: Nomor telepon."""
        # Kasus Salah: tidak ada kode negara
        data = self.valid_data.copy()
        data["phone"] = "08123456789"
        with self.assertRaises(ValidationError):
            UserProfileCreate(**data)

    async def test_tags_validator(self):
        """Tes Validasi Kustom: Tags (interest/expertise)."""
        data = self.valid_data.copy()
        data["expertise"] = " docker ,  kubernetes  "
        model = UserProfileCreate(**data)
        self.assertEqual(model.expertise, ["docker", "kubernetes"])

    async def test_username_validator(self):
        """Tes Validasi Kustom: Username sosial media."""
        data = self.valid_data.copy()
        data["github_username"] = "https://github.com/username"
        with self.assertRaises(ValidationError):
            UserProfileCreate(**data)

    async def test_agreement_validator(self):
        """Tes Validasi Kustom: Checkbox persetujuan."""
        data = self.valid_data.copy()
        data["privacy_agreed"] = False
        with self.assertRaises(ValidationError) as context:
            UserProfileCreate(**data)
        self.assertIn("This field must be checked", str(context.exception))


class TestUserProfileCreate(IsolatedAsyncioTestCase):
    async def test_inherits_validations_from_base(self):
        """Tes Inheritance: Memastikan UserProfileCreate punya validasi yang sama dengan Base."""
        # Cukup uji satu kasus, misalnya field wajib, untuk membuktikan pewarisan.
        invalid_data = {
            "last_name": "Santoso",
            "bio": "Seorang software engineer handal dengan pengalaman lebih dari 5 tahun.",
            "job_category": JobCategory.TECH_SPECIALIST,
            "job_title": "Senior Backend Developer",
            "country_id": 1,
            "coc_acknowledged": True,
            "terms_agreed": True,
            "privacy_agreed": True,
        }
        with self.assertRaises(ValidationError):
            UserProfileCreate(**invalid_data)


class TestUserProfileDB(IsolatedAsyncioTestCase):
    def setUp(self):
        self.valid_base_data = TestUserProfileBase().setUp()
        self.valid_db_data = self.valid_data = {
            "first_name": "Budi",
            "last_name": "Santoso",
            "email": "budi.santoso@example.com",
            "bio": "Seorang software engineer handal dengan pengalaman lebih dari 5 tahun.",
            "job_category": JobCategory.TECH_SPECIALIST,
            "job_title": "Senior Backend Developer",
            "country_id": 1,
            "phone": "+6281234567890",
            "interest": "python, fastapi, testing",
            "github_username": "budisan",
            "coc_acknowledged": True,
            "terms_agreed": True,
            "privacy_agreed": True,
        }
        self.valid_db_data["profile_picture"] = "https://example.com/profile.png"

    async def test_valid_db_data_parses_correctly(self):
        """Tes Happy Path: Memastikan data valid untuk DB (dengan profile_picture) berhasil."""
        try:
            model = UserProfileDB(**self.valid_db_data)
            self.assertEqual(model.first_name, "Budi")
            self.assertEqual(
                str(model.profile_picture), "https://example.com/profile.png"
            )
        except ValidationError as e:
            self.fail(f"UserProfileDB raised ValidationError unexpectedly! \n{e}")
