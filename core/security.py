from datetime import datetime, timedelta
import hashlib
import uuid
from typing import Optional, Tuple

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from pytz import timezone
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import Session as SQLAlchemySession

from models import get_db_sync
from models.RefreshToken import RefreshToken
from models.Token import Token
from models.User import User
from schemas.auth import AuthorizationStatusEnum
from settings import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_MINUTES,
    SECRET_KEY,
    TZ,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token/", auto_error=False)


def generate_hash_password(password: str) -> str:
    hash = bcrypt.hashpw(str.encode(password), bcrypt.gensalt())
    return hash.decode()


def validated_password(hash: str, password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hash.encode())
    except Exception:
        return False


def hash_token(token: str) -> str:
    """Hash one-time tokens before storing or comparing them in the database."""
    return hashlib.sha256(token.encode()).hexdigest()


async def generate_token_from_user(
    db: SQLAlchemySession, user: User, ignore_timezone: bool = False
) -> Tuple[str, str]:
    now = datetime.now()
    if ignore_timezone is False:  # For testing
        now = now.astimezone(timezone(TZ))

    expire = now + timedelta(minutes=float(ACCESS_TOKEN_EXPIRE_MINUTES))
    """
    {
        "user_id": "aaaa-bbbb-cccc-dddd",
        "username": "someusername",
        "exp": 1641455971,
    }
    """
    payload = {
        "id": str(user.id),
        "username": user.username,
        "exp": expire,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    new_token = Token(user=user, token=hash_token(token), expired_at=expire)
    db.add(new_token)
    refresh_expire = now + timedelta(minutes=float(REFRESH_TOKEN_EXPIRE_MINUTES))
    payload = {
        "id": str(user.id),
        "username": user.username,
        "jti": str(uuid.uuid4()),
        "exp": refresh_expire,
    }
    refresh_token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    new_refresh_token = RefreshToken(
        user=user,
        refresh_token=hash_token(refresh_token),
        token=new_token,
        expired_at=refresh_expire,
    )
    db.add(new_refresh_token)
    db.commit()
    return (token, refresh_token)


def get_token_exp(token: str) -> int:
    """Return the JWT expiry as a Unix timestamp for API responses."""
    payload = jwt.decode(
        jwt=token,
        key=SECRET_KEY,
        algorithms=[ALGORITHM],
        options={"verify_exp": False},
    )
    return int(payload["exp"])


def get_refresh_token_session(
    db: SQLAlchemySession, refresh_token: str
) -> Optional[RefreshToken]:
    """Validate a refresh token against its signed claims and DB session."""
    try:
        # The database expiry is authoritative for tokens issued before the
        # refresh-token JWT expiry bug was fixed.
        payload = jwt.decode(
            jwt=refresh_token,
            key=SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        return None

    user_id = payload.get("id")
    if not user_id:
        return None

    refresh_token_hash = hash_token(refresh_token)
    stmt = (
        select(RefreshToken)
        .where(
            RefreshToken.refresh_token.in_([refresh_token_hash, refresh_token]),
            RefreshToken.user_id == user_id,
        )
        .with_for_update()
    )
    refresh_session = db.execute(stmt).scalar()
    if refresh_session is None:
        return None
    if refresh_session.refresh_token != refresh_token_hash:
        refresh_session.refresh_token = refresh_token_hash
        db.flush()

    now = datetime.now().astimezone(timezone(TZ))
    if refresh_session.expired_at <= now:
        db.delete(refresh_session)
        db.commit()
        return None

    return refresh_session


async def rotate_refresh_token(
    db: SQLAlchemySession, refresh_session: RefreshToken
) -> Tuple[str, str]:
    """Replace a refresh-token session with a new access/refresh-token pair."""
    user = refresh_session.user
    db.delete(refresh_session)
    db.flush()
    return await generate_token_from_user(db=db, user=user)


def get_user_from_token(db: SQLAlchemySession, token: str) -> Optional[User]:
    if not token:
        return None

    now = datetime.now().astimezone(timezone(TZ))
    try:
        payload = jwt.decode(jwt=token, key=SECRET_KEY, algorithms=[ALGORITHM])
        id = payload.get("id")
    except (jwt.InvalidTokenError, TypeError, ValueError):
        return None

    token_hash = hash_token(token)
    stmt = select(Token).where(
        Token.token.in_([token_hash, token]),
        Token.user_id == id,
    )
    session = db.execute(stmt).scalar()
    if session is None:
        return None
    if session.expired_at <= now:
        return None
    if session.token != token_hash:
        session.token = token_hash
        db.flush()
    if session.user is None or session.user.is_active is False:
        return None

    return session.user


def get_current_user(
    db: Session = Depends(get_db_sync), token: str = Depends(oauth2_scheme)
) -> Optional[User]:
    return get_user_from_token(db, token)


def invalidate_token(db: SQLAlchemySession, token: str):
    now = datetime.now().astimezone(timezone(TZ))
    token_hash = hash_token(token)
    token_row = db.execute(
        select(Token).where(Token.token == token_hash)
    ).scalar_one_or_none()

    if token_row is not None:
        db.execute(delete(RefreshToken).where(RefreshToken.token_id == token_row.id))
        db.delete(token_row)

    db.execute(delete(Token).where(Token.expired_at <= now))
    db.execute(delete(RefreshToken).where(RefreshToken.expired_at <= now))
    db.commit()


def invalidate_user_tokens(db: SQLAlchemySession, user_id: str) -> None:
    db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    db.execute(delete(Token).where(Token.user_id == user_id))
    db.commit()


def check_permissions(
    current_user: User | None, required_participant_type: str
) -> AuthorizationStatusEnum:
    """Check if the current user has the required permissions.
    Args:
        current_user (User | None): The current authenticated user.
        required_participant_type (str): The required participant type for access.
    Returns:
        AuthorizationStatusEnum: The authorization status.
    """
    if current_user is None:
        return AuthorizationStatusEnum.UNAUTHORIZED
    if current_user.participant_type != required_participant_type:
        return AuthorizationStatusEnum.FORBIDDEN
    return AuthorizationStatusEnum.PASSED
