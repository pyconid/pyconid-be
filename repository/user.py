from sqlalchemy import UUID
from sqlalchemy.inspection import inspect
import datetime
from enum import Enum
from pydantic import HttpUrl
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.User import VOLUNTEER_PARTICIPANT, User
from models.Volunteer import Volunteer
from schemas.user_profile import UserProfileDB


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    stmt = select(User).where(User.username == username)
    data = db.execute(stmt).scalar()
    return data


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    stmt = select(User).where(User.email == email)
    data = db.execute(stmt).scalar()
    return data


def get_all_user(
    db: Session, search: Optional[str] = None, paritcipant_type: Optional[str] = None
) -> list[User]:
    stmt = select(User)
    if search:
        search_pattern = f"%{search}%"
        stmt = stmt.where(
            (User.username.ilike(search_pattern))
            | (User.first_name.ilike(search_pattern))
            | (User.last_name.ilike(search_pattern))
            | (User.email.ilike(search_pattern))
        )
    if paritcipant_type:
        stmt = stmt.where(User.participant_type == paritcipant_type)
    stmt = stmt.order_by(User.email.asc())
    results = db.execute(stmt).scalars().all()
    return results


def get_user_by_id(db: Session, id: str) -> Optional[User]:
    stmt = select(User).where(User.id == id)
    return db.execute(stmt).scalar()


def create_user(
    db: Session,
    username: str = None,
    password: str = None,
    is_active: bool = False,
    github_id: str = None,
    github_username: str = None,
    google_id: str = None,
    google_email: str = None,
    profile_picture: str = None,
    first_name: str = None,
    last_name: str = None,
    email: str = None,
    industry_categories: str = None,
    company: str = None,
    job_category: str = None,
    job_title: str = None,
    experience: int = None,
    t_shirt_size: str = None,
    gender: str = None,
    date_of_birth: str = None,
    phone: str = None,
    country: str = None,
    state: str = None,
    city: str = None,
    zip_code: int = None,
    address: str = None,
    bio: str = None,
    interest: str = None,
    looking_for: str = None,
    expertise: str = None,
    website: str = None,
    facebook_username: str = None,
    linkedin_username: str = None,
    twitter_username: str = None,
    instagram_username: str = None,
    share_my_data_to_sponsor: bool = False,
    retain_my_data_for_next_pycon: bool = False,
    terms_agreed: bool = False,
    privacy_agreed: bool = False,
    coc_acknowledged: bool = False,
    participant_type: str = "Non Participant",
    created_at=None,
    updated_at=None,
    deleted_at=None,
    is_commit: bool = True,
) -> User:
    """
    Create a new user in the database using all User model columns except id.
    """
    user = User(
        username=username,
        password=password,
        is_active=is_active,
        github_id=github_id,
        github_username=github_username,
        google_id=google_id,
        google_email=google_email,
        profile_picture=profile_picture,
        first_name=first_name,
        last_name=last_name,
        email=email,
        industry_categories=industry_categories,
        company=company,
        job_category=job_category,
        job_title=job_title,
        experience=experience,
        t_shirt_size=t_shirt_size,
        gender=gender,
        date_of_birth=date_of_birth,
        phone=phone,
        country=country,
        state=state,
        city=city,
        zip_code=zip_code,
        address=address,
        bio=bio,
        interest=interest,
        looking_for=looking_for,
        expertise=expertise,
        website=website,
        facebook_username=facebook_username,
        linkedin_username=linkedin_username,
        twitter_username=twitter_username,
        instagram_username=instagram_username,
        share_my_data_to_sponsor=share_my_data_to_sponsor,
        retain_my_data_for_next_pycon=retain_my_data_for_next_pycon,
        terms_agreed=terms_agreed,
        privacy_agreed=privacy_agreed,
        coc_acknowledged=coc_acknowledged,
        participant_type=participant_type,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )
    db.add(user)
    if is_commit:
        db.commit()
    return user


def update_user_profile(
    db: Session, user_id: UUID, profile_data: UserProfileDB
) -> Optional[User]:
    stmt = select(User).where(User.id == user_id)
    user = db.execute(stmt).scalar()
    if user is None:
        return None
    valid_columns = {c.key for c in inspect(User).mapper.column_attrs}
    profile_data_dict = profile_data.model_dump()
    for key, value in profile_data_dict.items():
        if key not in valid_columns:
            continue

        # Skip updating profile_picture if value is None
        if key == "profile_picture" and value is None:
            continue

        # Convert Pydantic types to native
        if isinstance(value, HttpUrl):
            value = str(value)
        elif isinstance(value, Enum):
            value = value.value
        elif isinstance(value, list):
            value = ",".join(map(str, value))
        elif isinstance(value, datetime.date):
            value = value  # SQLAlchemy Date / DateTime accepts date object

        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return user


def get_user_for_volunteer(db: Session, search: Optional[str] = None) -> list[User]:
    stmt = (
        select(User)
        .where(User.participant_type == VOLUNTEER_PARTICIPANT)
        .join(Volunteer, User.volunteer, isouter=True)
        .where(Volunteer.id.is_(None))
    )
    if search:
        search_pattern = f"%{search}%"
        stmt = stmt.where(
            (User.username.ilike(search_pattern))
            | (User.first_name.ilike(search_pattern))
            | (User.last_name.ilike(search_pattern))
            | (User.email.ilike(search_pattern))
        )
    stmt = stmt.order_by(User.email.asc())
    results = db.execute(stmt).scalars().all()
    return results
