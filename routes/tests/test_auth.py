from unittest.mock import MagicMock, patch
import alembic.config
from unittest import IsolatedAsyncioTestCase
from datetime import datetime, timedelta
import jwt
import secrets
import pytz

from fastapi.testclient import TestClient
from sqlalchemy import select
from core.oauth import github_service, google_service
from core.security import generate_hash_password
from models import engine, db, get_db_sync, get_db_sync_for_test
from models.Token import Token
from models.User import User
from main import app
from routes.auth import (
    auth_rate_limiter,
    forgot_password_rate_limiter,
    signup_rate_limiter,
)
from settings import SECRET_KEY, ALGORITHM, FRONTEND_BASE_URL


def create_test_oauth_state(redirect_uri=None, provider="github"):
    """Helper function to create valid JWT state for testing"""
    if redirect_uri is None:
        redirect_uri = (
            f"{FRONTEND_BASE_URL or 'http://localhost:3000'}/auth/{provider}/callback/"
        )

    payload = {
        "redirect_uri": redirect_uri,
        "provider": provider,
        "nonce": secrets.token_urlsafe(16),
        "exp": datetime.now(tz=pytz.timezone("UTC")) + timedelta(minutes=10),
        "iat": datetime.now(tz=pytz.timezone("UTC")),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


class TestAuth(IsolatedAsyncioTestCase):
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
        for limiter in (
            auth_rate_limiter,
            forgot_password_rate_limiter,
            signup_rate_limiter,
        ):
            limiter._requests.clear()

    def assert_token_expirations(self, data):
        self.assertEqual(
            data["token_exp"],
            jwt.decode(data["token"], SECRET_KEY, algorithms=[ALGORITHM])["exp"],
        )
        self.assertEqual(
            data["refresh_token_exp"],
            jwt.decode(data["refresh_token"], SECRET_KEY, algorithms=[ALGORITHM])[
                "exp"
            ],
        )

    async def test_login_then_logout(self):
        # Given
        new_user = User(
            username="testuser",
            email="testuser@example.com",
            password=generate_hash_password("password"),
            is_active=True,
        )
        self.db.add(new_user)
        self.db.commit()
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1
        response = client.post(
            "/auth/email/signin/",
            json={"email": "testuser@example.com", "password": "password"},
        )

        # Expect 1
        self.assertEqual(response.status_code, 200)
        user_id = response.json().get("id", None)
        self.assertEqual(user_id, str(new_user.id))
        token = response.json().get("token", None)
        self.assertIsNotNone(token)
        session = self.db.query(Token).where(Token.user_id == user_id).scalar()
        self.assertIsNotNone(session)
        self.assertNotEqual(session.token, token)

        refresh_token = response.json()["refresh_token"]

        # When 2
        response = client.post(
            "/auth/email/signin/",
            json={"email": "unregistered@example.com", "password": "wrongpassword"},
        )

        # Expect 2
        self.assertEqual(response.status_code, 400)

        # When 3
        response = client.get(
            "/auth/me/",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect 3
        self.assertEqual(response.status_code, 200)

        # When 4
        response = client.post(
            "/auth/logout/",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect 4
        self.assertEqual(response.status_code, 200)
        stmt = select(Token).where(Token.user_id == new_user.id)
        token_row = self.db.execute(stmt).scalar()
        self.assertIsNone(token_row)

        refresh_response = client.post(
            "/auth/refresh-token/", json={"refresh_token": refresh_token}
        )
        self.assertEqual(refresh_response.status_code, 401)

        # When 5
        response = client.get(
            "/auth/me/",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Expect 5
        self.assertEqual(response.status_code, 401)

    # Oauth Github
    async def test_github_oauth_signin_endpoint(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        with patch.object(github_service, "initiate_oauth") as mock_initiate:
            mock_initiate.return_value = "https://github.com/login/oauth/authorize?client_id=test&redirect_uri=..."

            response = client.post("/auth/github/signin/")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("redirect", data)
            self.assertTrue(data["redirect"].startswith("https://github.com"))

    @patch("main.REGISTRATION_ENABLED", False)
    async def test_github_oauth_signin_remains_available_when_registration_closed(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        with patch.object(github_service, "initiate_oauth") as mock_initiate:
            mock_initiate.return_value = (
                "https://github.com/login/oauth/authorize?client_id=test"
            )

            response = client.post("/auth/github/signin/")

            self.assertEqual(response.status_code, 200)
            self.assertIn("redirect", response.json())

    async def test_github_oauth_verified_endpoint_new_user(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        mock_oauth_client = MagicMock()

        async def mock_fetch_access_token(code, redirect_uri=None):
            return {
                "access_token": "github_access_token_123",
                "refresh_token": "github_refresh_token_456",
                "token_type": "bearer",
                "scope": "user:email",
            }

        mock_oauth_client.fetch_access_token = mock_fetch_access_token

        mock_user_response = MagicMock()
        mock_user_response.status_code = 200
        mock_user_response.json.return_value = {
            "id": 12345,
            "login": "testuser",
            "email": "test@example.com",
            "name": "Test User",
        }

        mock_emails_response = MagicMock()
        mock_emails_response.status_code = 200
        mock_emails_response.json.return_value = [
            {"email": "test@example.com", "primary": True, "verified": True}
        ]

        async def mock_get(url, token=None):
            if "user/emails" in url:
                return mock_emails_response
            return mock_user_response

        mock_oauth_client.get = mock_get

        mock_oauth = MagicMock()
        mock_oauth.github = mock_oauth_client

        # Create valid JWT state for testing
        valid_state = create_test_oauth_state(provider="github")
        client.cookies.set("oauth_state", valid_state)

        with patch.object(github_service, "oauth", mock_oauth):
            response = client.post(
                f"/auth/github/verified/?code=auth_code&state={valid_state}"
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertIn("token", data)
            self.assertIn("refresh_token", data)
            self.assertIn("id", data)
            self.assertEqual(data["username"], "test@example.com")
            self.assertTrue(data["is_new_user"])
            self.assertEqual(data["github_username"], "testuser")
            self.assert_token_expirations(data)

            stmt = select(User).where(User.username == "test@example.com")
            created_user = self.db.execute(stmt).scalar()
            self.assertIsNotNone(created_user)
            self.assertTrue(created_user.is_active)
            self.assertEqual(created_user.github_username, "testuser")
            self.assertEqual(created_user.github_id, "12345")

    async def test_github_oauth_verified_endpoint_existing_user(self):
        existing_user = User(
            username="existing@example.com",
            password=generate_hash_password(""),
            github_id="54321",
            github_username="existinguser",
            is_active=True,
        )
        self.db.add(existing_user)
        self.db.commit()

        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        mock_oauth_client = MagicMock()

        async def mock_fetch_access_token(code, redirect_uri=None):
            return {
                "access_token": "new_github_access_token",
                "refresh_token": "new_github_refresh_token",
                "token_type": "bearer",
                "scope": "user:email",
            }

        mock_oauth_client.fetch_access_token = mock_fetch_access_token

        mock_user_response = MagicMock()
        mock_user_response.status_code = 200
        mock_user_response.json.return_value = {
            "id": 54321,
            "login": "existinguser",
            "email": "existing@example.com",
            "name": "Updated Name",
        }

        mock_emails_response = MagicMock()
        mock_emails_response.status_code = 200
        mock_emails_response.json.return_value = [
            {"email": "existing@example.com", "primary": True, "verified": True}
        ]

        async def mock_get(url, token=None):
            if "user/emails" in url:
                return mock_emails_response
            return mock_user_response

        mock_oauth_client.get = mock_get

        mock_oauth = MagicMock()
        mock_oauth.github = mock_oauth_client

        # Create valid JWT state for testing
        valid_state = create_test_oauth_state(provider="github")
        client.cookies.set("oauth_state", valid_state)

        with patch.object(github_service, "oauth", mock_oauth):
            response = client.post(
                f"/auth/github/verified/?code=auth_code&state={valid_state}"
            )
            print(response.json())

            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertIn("token", data)
            self.assertIn("refresh_token", data)
            self.assertEqual(data["id"], str(existing_user.id))
            self.assertEqual(data["username"], "existing@example.com")
            self.assertFalse(data["is_new_user"])
            self.assertEqual(data["github_username"], "existinguser")

    async def test_github_oauth_verified_missing_code(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        response = client.post("/auth/github/verified/")

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["message"], "Code not found")

    async def test_github_oauth_verified_token_exchange_failure(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        mock_oauth_client = MagicMock()

        async def mock_fetch_access_token_fail(**kwargs):
            raise Exception("Token exchange failed")

        mock_oauth_client.fetch_access_token = mock_fetch_access_token_fail

        mock_oauth = MagicMock()
        mock_oauth.github = mock_oauth_client

        # Create valid JWT state for testing
        valid_state = create_test_oauth_state(provider="github")
        client.cookies.set("oauth_state", valid_state)

        with patch.object(github_service, "oauth", mock_oauth):
            response = client.post(
                f"/auth/github/verified/?code=invalid_code&state={valid_state}"
            )

            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertIn(
                "OAuth verification for github failed: Token exchange failed",
                str(data["message"]),
            )

    async def test_github_oauth_verified_user_info_fetch_failure(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        mock_oauth_client = MagicMock()

        async def mock_fetch_access_token(**kwargs):
            return {"access_token": "github_access_token_123", "token_type": "bearer"}

        mock_oauth_client.fetch_access_token = mock_fetch_access_token

        async def mock_get_fail(url, token=None):
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.side_effect = Exception("API Error")
            return mock_response

        mock_oauth_client.get = mock_get_fail

        mock_oauth = MagicMock()
        mock_oauth.github = mock_oauth_client

        # Create valid JWT state for testing
        valid_state = create_test_oauth_state(provider="github")
        client.cookies.set("oauth_state", valid_state)

        with patch.object(github_service, "oauth", mock_oauth):
            response = client.post(
                f"/auth/github/verified/?code=auth_code&state={valid_state}"
            )

            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertIn(
                "Failed to fetch GitHub user info",
                str(data["message"]),
            )

    # Oauth Google
    async def test_google_oauth_signin_endpoint(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        with patch.object(google_service, "initiate_oauth") as mock_initiate:
            mock_initiate.return_value = "https://accounts.google.com/o/oauth2/v2/auth?client_id=test&redirect_uri=..."

            response = client.post("/auth/google/signin/")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("redirect", data)
            self.assertTrue(data["redirect"].startswith("https://accounts.google.com"))

    async def test_google_oauth_verified_endpoint_new_user(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        mock_oauth_client = MagicMock()

        async def mock_fetch_access_token(code, redirect_uri=None):
            return {
                "access_token": "google_access_token_123",
                "refresh_token": "google_refresh_token_456",
                "token_type": "bearer",
                "scope": "openid email profile",
            }

        mock_oauth_client.fetch_access_token = mock_fetch_access_token

        mock_user_response = MagicMock()
        mock_user_response.status_code = 200
        mock_user_response.json.return_value = {
            "sub": "67890",
            "email": "testuser@gmail.com",
            "name": "Test Google User",
            "given_name": "Test",
            "family_name": "User",
            "picture": "https://lh3.googleusercontent.com/a/example",
            "email_verified": True,
        }

        async def mock_get(url, token=None):
            return mock_user_response

        mock_oauth_client.get = mock_get

        mock_oauth = MagicMock()
        mock_oauth.google = mock_oauth_client

        # Create valid JWT state for testing
        valid_state = create_test_oauth_state(provider="google")
        client.cookies.set("oauth_state", valid_state)

        with patch.object(google_service, "oauth", mock_oauth):
            response = client.post(
                f"/auth/google/verified/?code=auth_code&state={valid_state}"
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertIn("token", data)
            self.assertIn("refresh_token", data)
            self.assertIn("id", data)
            self.assertEqual(data["username"], "testuser@gmail.com")
            self.assertTrue(data["is_new_user"])
            self.assertEqual(data["google_email"], "testuser@gmail.com")
            self.assert_token_expirations(data)

            stmt = select(User).where(User.username == "testuser@gmail.com")
            created_user = self.db.execute(stmt).scalar()
            self.assertIsNotNone(created_user)
            self.assertTrue(created_user.is_active)
            self.assertEqual(created_user.google_email, "testuser@gmail.com")
            self.assertEqual(created_user.google_id, "67890")

    async def test_google_oauth_verified_endpoint_existing_user(self):
        existing_user = User(
            username="existing.google@gmail.com",
            password=generate_hash_password(""),
            google_id="98765",
            google_email="existing.google@gmail.com",
            is_active=True,
        )
        self.db.add(existing_user)
        self.db.commit()

        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        mock_oauth_client = MagicMock()

        async def mock_fetch_access_token(code, redirect_uri=None):
            return {
                "access_token": "new_google_access_token",
                "refresh_token": "new_google_refresh_token",
                "token_type": "bearer",
                "scope": "openid email profile",
            }

        mock_oauth_client.fetch_access_token = mock_fetch_access_token

        mock_user_response = MagicMock()
        mock_user_response.status_code = 200
        mock_user_response.json.return_value = {
            "sub": "98765",
            "email": "existing.google@gmail.com",
            "name": "Updated Google User",
            "given_name": "Updated",
            "family_name": "User",
            "picture": "https://lh3.googleusercontent.com/a/updated",
            "email_verified": True,
        }

        async def mock_get(url, token=None):
            return mock_user_response

        mock_oauth_client.get = mock_get

        mock_oauth = MagicMock()
        mock_oauth.google = mock_oauth_client

        # Create valid JWT state for testing
        valid_state = create_test_oauth_state(provider="google")
        client.cookies.set("oauth_state", valid_state)

        with patch.object(google_service, "oauth", mock_oauth):
            response = client.post(
                f"/auth/google/verified/?code=auth_code&state={valid_state}"
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertIn("token", data)
            self.assertIn("refresh_token", data)
            self.assertEqual(data["id"], str(existing_user.id))
            self.assertEqual(data["username"], "existing.google@gmail.com")
            self.assertFalse(data["is_new_user"])
            self.assertEqual(data["google_email"], "existing.google@gmail.com")

    async def test_google_oauth_verified_missing_code(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        response = client.post("/auth/google/verified/")

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["message"], "Code not found")

    async def test_google_oauth_verified_token_exchange_failure(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        mock_oauth_client = MagicMock()

        async def mock_fetch_access_token_fail(code, redirect_uri=None):
            raise Exception("Token exchange failed")

        mock_oauth_client.fetch_access_token = mock_fetch_access_token_fail

        mock_oauth = MagicMock()
        mock_oauth.google = mock_oauth_client

        # Create valid JWT state for testing
        valid_state = create_test_oauth_state(provider="google")
        client.cookies.set("oauth_state", valid_state)

        with patch.object(google_service, "oauth", mock_oauth):
            response = client.post(
                f"/auth/google/verified/?code=invalid_code&state={valid_state}"
            )

            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertIn(
                "OAuth verification for google failed: Token exchange failed",
                str(data["message"]),
            )

    async def test_google_oauth_verified_user_info_fetch_failure(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        mock_oauth_client = MagicMock()

        async def mock_fetch_access_token(code, redirect_uri=None):
            return {"access_token": "google_access_token_123", "token_type": "bearer"}

        mock_oauth_client.fetch_access_token = mock_fetch_access_token

        async def mock_get_fail(url, token=None):
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.side_effect = Exception("API Error")
            return mock_response

        mock_oauth_client.get = mock_get_fail

        mock_oauth = MagicMock()
        mock_oauth.google = mock_oauth_client

        # Create valid JWT state for testing
        valid_state = create_test_oauth_state(provider="google")
        client.cookies.set("oauth_state", valid_state)

        with patch.object(google_service, "oauth", mock_oauth):
            response = client.post(
                f"/auth/google/verified/?code=auth_code&state={valid_state}"
            )

            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertIn(
                "Failed to fetch Google user info",
                str(data["message"]),
            )

    async def test_google_oauth_verified_fallback_userinfo_endpoint(self):
        """Test fallback to the second userinfo endpoint if the first one fails"""
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        mock_oauth_client = MagicMock()

        async def mock_fetch_access_token(code, redirect_uri=None):
            return {
                "access_token": "google_access_token_123",
                "token_type": "bearer",
                "scope": "openid email profile",
            }

        mock_oauth_client.fetch_access_token = mock_fetch_access_token

        # Mock untuk endpoint pertama gagal, kedua berhasil
        first_response = MagicMock()
        first_response.status_code = 400

        second_response = MagicMock()
        second_response.status_code = 200
        second_response.json.return_value = {
            "id": "11111",
            "email": "fallback@gmail.com",
            "name": "Fallback User",
            "given_name": "Fallback",
            "family_name": "User",
            "picture": "https://lh3.googleusercontent.com/a/fallback",
            "verified_email": True,
        }

        call_count = 0

        async def mock_get(url, token=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # First call ke openidconnect endpoint
                return first_response
            else:  # Second call ke oauth2/v2 endpoint
                return second_response

        mock_oauth_client.get = mock_get

        mock_oauth = MagicMock()
        mock_oauth.google = mock_oauth_client

        # Create valid JWT state for testing
        valid_state = create_test_oauth_state(provider="google")
        client.cookies.set("oauth_state", valid_state)

        with patch.object(google_service, "oauth", mock_oauth):
            response = client.post(
                f"/auth/google/verified/?code=auth_code&state={valid_state}"
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertIn("token", data)
            self.assertIn("refresh_token", data)
            self.assertEqual(data["username"], "fallback@gmail.com")
            self.assertTrue(data["is_new_user"])
            self.assertEqual(data["google_email"], "fallback@gmail.com")

            stmt = select(User).where(User.username == "fallback@gmail.com")
            created_user = self.db.execute(stmt).scalar()
            self.assertIsNotNone(created_user)
            self.assertEqual(created_user.google_id, "11111")

    def tearDown(self):
        self.db.close()

        # rollback - everything that happened with the
        # Session above (including calls to commit())
        # is rolled back.
        self.trans.rollback()

        # return connection to the Engine
        self.connection.close()
