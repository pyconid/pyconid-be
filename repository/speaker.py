from datetime import datetime
from typing import List, Literal, Optional

from pytz import timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from models.Speaker import Speaker
from models.SpeakerType import SpeakerType
from models.User import User
from schemas.speaker import SpeakerResponseItem


def get_all_speakers(
    db: Session,
    order_dir: Literal["asc", "desc"] = "asc",
    search: Optional[str] = None,
):
    # Query dasar
    stmt = select(Speaker)

    # Atur order berdasarkan updated_at
    if order_dir == "asc":
        stmt = stmt.order_by(Speaker.updated_at.asc())
    else:
        stmt = stmt.order_by(Speaker.updated_at.desc())

    if search:
        search_pattern = f"%{search}%"
        stmt = stmt.join(User, Speaker.user).where(
            (User.username.ilike(search_pattern))
            | (User.first_name.ilike(search_pattern))
            | (User.last_name.ilike(search_pattern))
            | (User.email.ilike(search_pattern))
        )

    # Add pagination (offset + limit).
    # Count the total records before pagination.
    total_count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    # Execute the query and retrieve the results.
    results = db.scalars(stmt).all()
    # Convert ORM objects to Pydantic models.
    results_schema = [SpeakerResponseItem.model_validate(r) for r in results]
    # Hitung total halaman

    # Return the result as a dictionary ready for the API response.
    return {
        "page": 1,
        "page_size": 1,
        "count": total_count,  # total_count,
        "page_count": 1,  # page_count,
        "results": results_schema,
    }


def get_speaker_per_page_by_search(
    db: Session,
    page: int,
    page_size: int,
    order_dir: Literal["asc", "desc"] = "asc",
    search: Optional[str] = None,
):
    # Calculate the offset (starting row).
    offset = (page - 1) * page_size

    # Query dasar
    stmt = select(Speaker)

    # Atur order berdasarkan updated_at
    if order_dir == "asc":
        stmt = stmt.order_by(Speaker.updated_at.asc())
    else:
        stmt = stmt.order_by(Speaker.updated_at.desc())

    # Jika ada keyword pencarian
    if search:
        search_pattern = f"%{search}%"
        stmt = stmt.join(User, Speaker.user).where(
            (User.username.ilike(search_pattern))
            | (User.first_name.ilike(search_pattern))
            | (User.last_name.ilike(search_pattern))
            | (User.email.ilike(search_pattern))
        )

    # Hitung total data sebelum pagination
    total_count = db.scalar(select(func.count()).select_from(stmt.subquery()))

    # Tambahkan pagination (offset + limit)
    stmt = stmt.offset(offset).limit(page_size)

    # Execute the query and retrieve the results.
    results = db.scalars(stmt).all()
    # Convert ORM objects to Pydantic models.
    results_schema = [SpeakerResponseItem.model_validate(r) for r in results]
    # Hitung total halaman
    page_count = (total_count + page_size - 1) // page_size if total_count else 0

    # Return the result as a dictionary ready for the API response.
    return {
        "page": page,
        "page_size": page_size,
        "count": total_count,  # total_count,
        "page_count": page_count,  # page_count,
        "results": results_schema,
    }


def get_all_speakers_public(db: Session) -> List[Speaker]:
    stmt = (
        select(Speaker)
        .options(
            joinedload(Speaker.user),
            joinedload(Speaker.speaker_type),
        )
        .order_by(Speaker.speaker_type_id)
    )

    results = db.scalars(stmt).all()
    return results


def get_speaker_by_id(db: Session, id: str) -> Optional[Speaker]:
    stmt = select(Speaker).where(Speaker.id == id)
    return db.execute(stmt).scalar()


def create_speaker(
    db: Session,
    user: User,
    speaker_type: Optional[SpeakerType] = None,
    now: Optional[datetime] = None,
    is_commit: bool = True,
) -> Speaker:
    if now is None:
        now = datetime.now().astimezone(timezone("Asia/Jakarta"))
    new_speaker = Speaker(
        user=user,
        speaker_type=speaker_type,
        created_at=now,
        updated_at=now,
    )
    db.add(new_speaker)
    if is_commit:
        db.commit()
    return new_speaker


def update_speaker(
    db: Session,
    speaker: Speaker,
    user: User,
    speaker_type: Optional[SpeakerType] = None,
    now: Optional[datetime] = None,
    is_commit: bool = True,
) -> Speaker:
    if now is None:
        now = datetime.now().astimezone(timezone("Asia/Jakarta"))
    speaker.user = user
    speaker.speaker_type = speaker_type
    speaker.updated_at = now
    if is_commit:
        db.commit()
    return speaker


def delete_speaker(
    db: Session,
    speaker: Speaker,
    is_commit: bool = True,
) -> None:
    db.delete(speaker)
    if is_commit:
        db.commit()
