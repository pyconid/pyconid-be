from unittest.mock import AsyncMock, patch
import alembic.config
import jwt
from fastapi.testclient import TestClient
from unittest import IsolatedAsyncioTestCase
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select
from core.security import generate_hash_password, validated_password
from models import engine, db, get_db_sync, get_db_sync_for_test
from main import app
from models.EmailVerification import EmailVerification
from models.ResetPassword import ResetPassword
from models.User import User
from routes.auth import (
    auth_rate_limiter,
    forgot_password_rate_limiter,
    signup_rate_limiter,
)
from settings import ALGORITHM, FRONTEND_BASE_URL, SECRET_KEY


class TestAuthEmail(IsolatedAsyncioTestCase):
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

    @patch("main.REGISTRATION_ENABLED", False)
    async def test_registration_endpoints_are_closed(self):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        for path in ("/auth/email/signup/",):
            response = client.post(path)

            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.json(), {"message": "Registration is temporarily closed"}
            )

        verification_response = client.get("/auth/email/verified/")
        self.assertEqual(verification_response.status_code, 400)
        self.assertEqual(verification_response.json()["message"], "Token not found")

    @patch("routes.auth.send_email_verfication", new_callable=AsyncMock)
    async def test_signup(self, mock_send_email_verfication):
        # Given
        new_user = User(
            username="someuser",
            password=generate_hash_password("password"),
            is_active=True,
        )
        self.db.add(new_user)
        self.db.commit()
        mock_send_email_verfication.return_value = None
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1 - create new verification
        response = client.post(
            "/auth/email/signup/",
            json={
                "username": "testuser",
                "email": "user@local.com",
                "password": "password",
            },
        )

        # Expect 1
        self.assertEqual(response.status_code, 204)
        stmt = select(EmailVerification).where(
            EmailVerification.email == "user@local.com",
            EmailVerification.username == "testuser",
        )
        email_verification = self.db.execute(stmt).scalar()
        self.assertIsNotNone(email_verification)
        self.assertTrue(validated_password(email_verification.password, "password"))
        activation_link = mock_send_email_verfication.call_args.kwargs[
            "activation_link"
        ]
        self.assertTrue(
            activation_link.startswith(
                f"{FRONTEND_BASE_URL}/email-verification/?token="
            )
        )
        mock_send_email_verfication.assert_called_once_with(
            recipient=email_verification.email, activation_link=activation_link
        )

        # When 2 - Only one verification per email
        response = client.post(
            "/auth/email/signup/",
            json={
                "username": "testuser",
                "email": "user@local.com",
                "password": "new_password",
            },
        )

        # Expect 2
        self.assertEqual(response.status_code, 204)
        stmt = select(func.count(EmailVerification.id)).where(
            EmailVerification.email == "user@local.com",
            EmailVerification.username == "testuser",
        )
        email_verification = self.db.execute(stmt).scalar()
        self.assertEqual(email_verification, 1)
        stmt = select(EmailVerification).where(
            EmailVerification.email == "user@local.com",
            EmailVerification.username == "testuser",
        )
        email_verification = self.db.execute(stmt).scalar()
        self.assertIsNotNone(email_verification)
        self.assertTrue(validated_password(email_verification.password, "new_password"))
        activation_link = mock_send_email_verfication.call_args.kwargs[
            "activation_link"
        ]
        verification_token = parse_qs(urlparse(activation_link).query)["token"][0]

        # When 3 - verify email with invalid code
        response = client.get(
            "/auth/email/verified/",
            params={
                "token": "invalid_code",
            },
        )

        # Expect 3
        self.assertEqual(response.status_code, 400)

        # When 4 - verify email with valid code
        response = client.get(
            "/auth/email/verified/",
            params={
                "token": verification_token,
            },
        )

        # Expect 4
        self.assertEqual(response.status_code, 200)
        stmt = select(EmailVerification).where(
            EmailVerification.email == "user@local.com",
            EmailVerification.username == "testuser",
        )
        email_verification = self.db.execute(stmt).scalar()
        self.assertIsNone(email_verification)

        # When 5 - login with email
        response = client.post(
            "/auth/email/signin/",
            json={
                "email": "user@local.com",
                "password": "new_password",
            },
        )

        # Expect 5
        self.assertEqual(response.status_code, 200)
        signin_data = response.json()
        self.assertEqual(
            signin_data["token_exp"],
            jwt.decode(signin_data["token"], SECRET_KEY, algorithms=[ALGORITHM])["exp"],
        )
        self.assertEqual(
            signin_data["refresh_token_exp"],
            jwt.decode(
                signin_data["refresh_token"], SECRET_KEY, algorithms=[ALGORITHM]
            )["exp"],
        )

    async def test_refresh_token_rotates_and_returns_expiry(self):
        new_user = User(
            username="refresh-user",
            email="refresh-user@local.com",
            password=generate_hash_password("password"),
            is_active=True,
        )
        self.db.add(new_user)
        self.db.commit()
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        signin_response = client.post(
            "/auth/email/signin/",
            json={
                "email": "refresh-user@local.com",
                "password": "password",
            },
        )
        self.assertEqual(signin_response.status_code, 200)
        old_refresh_token = signin_response.json()["refresh_token"]

        response = client.post(
            "/auth/refresh-token/",
            json={"refresh_token": old_refresh_token},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotEqual(data["refresh_token"], old_refresh_token)
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

        replay_response = client.post(
            "/auth/refresh-token/",
            json={"refresh_token": old_refresh_token},
        )
        self.assertEqual(replay_response.status_code, 401)

    @patch("routes.auth.send_reset_password_email", new_callable=AsyncMock)
    async def test_reset_password(self, mock_send_reset_password_email):
        # Given
        new_user = User(
            username="someuser",
            email="someuser@local.com",
            password=generate_hash_password("password"),
            is_active=True,
        )
        self.db.add(new_user)
        self.db.commit()
        mock_send_reset_password_email.return_value = None
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        # When 1 - request reset password with invalid email
        response = client.post(
            "/auth/email/forgot-password/",
            json={
                "email": "invalid_email@local.com",
            },
        )
        # Expect 1
        self.assertEqual(response.status_code, 200)

        # When 2 - request reset password with valid email
        response = client.post(
            "/auth/email/forgot-password/",
            json={
                "email": "someuser@local.com",
            },
        )
        # Expect 2
        self.assertEqual(response.status_code, 200)
        stmt = select(ResetPassword).where(ResetPassword.user == new_user)
        reset_password = self.db.execute(stmt).scalar()
        self.assertIsNotNone(reset_password)
        reset_link = mock_send_reset_password_email.call_args.kwargs["reset_link"]
        reset_token = parse_qs(urlparse(reset_link).query)["token"][0]
        self.assertNotEqual(reset_token, reset_password.token)
        mock_send_reset_password_email.assert_called_once_with(
            recipient=new_user.email, reset_link=reset_link
        )

        # When 3 - reset password with invalid token
        response = client.post(
            "/auth/email/reset-password/",
            json={
                "token": "invalid_token",
                "new_password": "new_password",
            },
        )
        # Expect 3
        self.assertEqual(response.status_code, 400)

        # When 4 - reset password with valid token
        response = client.post(
            "/auth/email/reset-password/",
            json={
                "token": reset_token,
                "new_password": "new_password",
            },
        )
        # Expect 4
        self.assertEqual(response.status_code, 200)
        stmt = select(ResetPassword).where(ResetPassword.user == new_user)
        reset_password = self.db.execute(stmt).scalar()
        self.assertIsNone(reset_password)
        self.assertTrue(new_user.password != generate_hash_password("new_password"))

    @patch(
        "routes.auth.forgot_password_rate_limiter.is_allowed",
        new_callable=AsyncMock,
        side_effect=[(True, None), (False, 30)],
    )
    async def test_forgot_password_is_rate_limited_by_email(self, mock_is_allowed):
        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.db)
        client = TestClient(app)

        response = client.post(
            "/auth/email/forgot-password/",
            json={"email": "Limit-Test@local.com"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["message"], "Too many password reset requests")
        self.assertEqual(mock_is_allowed.await_count, 2)
        self.assertTrue(
            mock_is_allowed.call_args_list[1]
            .args[0]
            .startswith("forgot-password:identifier:")
        )

    def tearDown(self):
        self.db.close()

        # rollback - everything that happened with the
        # Session above (including calls to commit())
        # is rolled back.
        self.trans.rollback()

        # return connection to the Engine
        self.connection.close()
