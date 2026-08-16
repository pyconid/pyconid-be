from datetime import datetime, timedelta
import hmac
import secrets
import traceback
from abc import ABC, abstractmethod
from typing import Optional, Tuple, TypedDict, Union
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
import jwt
import pytz
from sqlalchemy import or_, select
from models.User import User
from settings import (
    ALGORITHM,
    FRONTEND_BASE_URL,
    REGISTRATION_CLOSED_MESSAGE,
    REGISTRATION_ENABLED,
    SECRET_KEY,
    TZ,
)
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.orm import Session


class UserInfoResponse(TypedDict):
    id: str
    username: str
    email: Optional[str]
    name: Optional[str]


class HandleOauthResponse(TypedDict):
    user: User
    is_new_user: bool
    provider_user_info: UserInfoResponse


class OAuthTokenResponse(TypedDict, total=False):
    access_token: str
    refresh_token: Optional[str]
    expires_in: Optional[int]
    token_type: Optional[str]
    scope: Optional[str]


class BaseOAuthService(ABC):
    """Base OAuth service that must be inherited by all OAuth providers."""

    def __init__(self):
        self.oauth = OAuth()
        self._register_provider()

    @abstractmethod
    def _register_provider(self):
        """Register OAuth providers using authlib."""
        pass

    @abstractmethod
    async def _get_user_info(
        self, client, token: OAuthTokenResponse
    ) -> UserInfoResponse:
        """Get user info from the API provider."""
        pass

    @abstractmethod
    def _get_provider_name(self) -> str:
        """Return provider name (github, google, discord, etc)"""
        pass

    @abstractmethod
    def _get_user_by_provider_id(self, db: Session, provider_id: str) -> Optional[User]:
        """Find user by provider-specific ID field"""
        pass

    @abstractmethod
    def _update_user_provider_info(
        self, user: User, user_info: UserInfoResponse
    ) -> User:
        """Update user with provider-specific fields."""
        pass

    @abstractmethod
    def _set_user_provider_fields(
        self, user_data: dict, user_info: UserInfoResponse, provider_id: str
    ) -> dict:
        """Set provider-specific fields for a new user."""
        pass

    def _create_oauth_state(
        self, redirect_uri: Optional[str] = None, provider: Optional[str] = None
    ) -> str:
        payload = {
            "redirect_uri": redirect_uri,
            "provider": provider,
            "nonce": secrets.token_urlsafe(16),
            "exp": datetime.now(tz=pytz.timezone("UTC")) + timedelta(minutes=10),
            "iat": datetime.now(tz=pytz.timezone("UTC")),
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    def _verify_oauth_state(
        self,
        state: str,
        expected_state: Optional[str] = None,
        expected_provider: Optional[str] = None,
    ) -> dict:
        try:
            payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
            if not expected_state or not hmac.compare_digest(state, expected_state):
                raise HTTPException(status_code=400, detail="Invalid OAuth state")
            if expected_provider and payload.get("provider") != expected_provider:
                raise HTTPException(status_code=400, detail="Invalid OAuth state")
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=400, detail="OAuth state expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=400, detail="Invalid OAuth state")

    async def initiate_oauth(
        self, request: Request, follow_redirect: Optional[bool] = False
    ) -> Union[RedirectResponse, str]:
        """
        Initiate OAuth flow.

        The same general logic for all providers.
        """
        provider_name = self._get_provider_name()

        if not hasattr(self.oauth, provider_name):
            raise HTTPException(
                status_code=500,
                detail=f"OAuth provider '{provider_name}' is not properly configured",
            )

        client = getattr(self.oauth, provider_name)

        if FRONTEND_BASE_URL is None:
            raise HTTPException(status_code=500, detail="FRONTEND_BASE_URL is not set")

        try:
            redirect_uri = (
                f"{FRONTEND_BASE_URL.rstrip('/')}/auth/{provider_name}/callback/"
            )

            state = self._create_oauth_state(
                redirect_uri=redirect_uri, provider=provider_name
            )
            request.state.oauth_state = state

            if follow_redirect:
                return await client.authorize_redirect(
                    request, redirect_uri, state=state
                )

            authorization_url = await client.create_authorization_url(
                redirect_uri, state=state
            )
            return authorization_url.get("url", None)
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to initiate {provider_name} OAuth: {str(e)}",
            )

    async def handle_verified(
        self, request: Request, db: Session
    ) -> HandleOauthResponse:
        """
        Handle OAuth callbacks and create/update users.

        The same general logic for all providers.
        Provider-specific logic is delegated to abstract methods.
        """
        provider_name = self._get_provider_name()

        if not hasattr(self.oauth, provider_name):
            raise HTTPException(
                status_code=500,
                detail=f"OAuth provider '{provider_name}' is not properly configured",
            )

        client = getattr(self.oauth, provider_name)
        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            raise HTTPException(
                status_code=400,
                detail="Missing 'code' or 'state' in OAuth callback request",
            )

        try:
            state_payload = self._verify_oauth_state(
                state=state,
                expected_state=request.cookies.get("oauth_state"),
                expected_provider=provider_name,
            )
            redirect_uri = state_payload.get("redirect_uri")
        except HTTPException as e:
            raise e

        try:
            # Get access token
            token = await client.fetch_access_token(
                code=code, redirect_uri=redirect_uri
            )

            # Get user info from provider
            user_info = await self._get_user_info(client, token)

            # Find or create user
            user, is_new_user = await self._find_or_create_user(db, user_info)

            return {
                "user": user,
                "is_new_user": is_new_user,
                "provider_user_info": user_info,
            }

        except Exception as e:
            traceback.print_exc()
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(
                status_code=400,
                detail=f"OAuth verification for {provider_name} failed: {str(e)}",
            )

    async def _find_or_create_user(
        self, db: Session, user_info: UserInfoResponse
    ) -> Tuple[User, bool]:
        """
        Common user finding/creation logic.
        """
        provider_id = user_info.get("id")
        provider_username = user_info.get("username")
        provider_email = user_info.get("email")

        existing_user = self._get_user_by_provider_id(db, provider_id)

        if existing_user:
            # Update existing user info
            updated_user = self._update_user_provider_info(existing_user, user_info)
            updated_user.updated_at = datetime.now(pytz.timezone(TZ))
            db.commit()
            return updated_user, False

        user: Optional[User] = None
        if provider_email:
            stmt = select(User).where(
                or_(
                    User.username == provider_email,
                    User.email == provider_email,
                    User.google_email == provider_email,
                )
            )
            user = db.execute(stmt).scalar()

        is_new_user = False

        if not user:
            if not REGISTRATION_ENABLED:
                raise HTTPException(status_code=403, detail=REGISTRATION_CLOSED_MESSAGE)

            user_data = {
                "username": provider_email if provider_email else provider_username,
                "password": None,
                "is_active": True,
                "created_at": datetime.now(pytz.timezone(TZ)),
                "updated_at": datetime.now(pytz.timezone(TZ)),
            }

            # Set provider-specific fields
            user_data = self._set_user_provider_fields(
                user_data, user_info, provider_id
            )

            user = User(**user_data)
            db.add(user)
            db.flush()
            is_new_user = True

        else:
            user = self._update_user_provider_info(user, user_info)

            user.updated_at = datetime.now(pytz.timezone(TZ))
            db.add(user)

        db.commit()
        return user, is_new_user
