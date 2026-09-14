from datetime import datetime
from typing import Optional
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.security import hash_token
from models.ResetPassword import ResetPassword
from models.User import User


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def get_reset_password_by_user(db: Session, user: User) -> Optional[ResetPassword]:
    stmt = select(ResetPassword).where(ResetPassword.user == user)
    data = db.execute(stmt).scalar()
    return data


def get_reset_password_by_token(db: Session, token: str) -> Optional[ResetPassword]:
    token_hash = hash_token(token)
    stmt = select(ResetPassword).where(ResetPassword.token.in_([token_hash, token]))
    data = db.execute(stmt).scalar()
    if data and data.token != token_hash:
        data.token = token_hash
        db.add(data)
    return data


def create_reset_password(
    db: Session,
    user: User,
    token: str,
    expired_at: datetime,
    is_commit: bool = True,
) -> ResetPassword:
    new_reset_password = ResetPassword(
        user=user,
        token=hash_token(token),
        expired_at=expired_at,
    )
    db.add(new_reset_password)
    if is_commit:
        db.commit()
    return new_reset_password


def update_reset_password(
    db: Session,
    reset_password: ResetPassword,
    user: User,
    token: str,
    expired_at: datetime,
    is_commit: bool = True,
) -> ResetPassword:
    reset_password.user = user
    reset_password.token = hash_token(token)
    reset_password.expired_at = expired_at
    if is_commit:
        db.commit()
    return reset_password


def delete_reset_password(
    db: Session,
    reset_password: ResetPassword,
    is_commit: bool = True,
) -> None:
    db.delete(reset_password)
    if is_commit:
        db.commit()
