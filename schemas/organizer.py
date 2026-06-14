from pydantic import BaseModel
from typing import Optional, Literal, Sequence

from fastapi import Query
from models.Organizer import Organizer
from models.OrganizerType import OrganizerType
from models.User import User


class OrganizerQuery(BaseModel):
    search: Optional[str] = Query(None, description="Search by organizer name")
    order_dir: Literal["asc", "desc"] = Query(
        "asc", description="Order direction: asc or desc"
    )


class OrganizerDetailUser(BaseModel):
    id: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    bio: str | None = None
    profile_picture: str | None = None
    email: str | None = None
    website: str | None = None
    facebook_username: str | None = None
    linkedin_username: str | None = None
    instagram_username: str | None = None
    twitter_username: str | None = None


class OrganizerDetailType(BaseModel):
    id: str
    name: str


class OrganizerDetailResponse(BaseModel):
    id: str
    user: OrganizerDetailUser
    organizer_type: OrganizerDetailType


class OrganizerDetailResponseList(BaseModel):
    results: list[OrganizerDetailResponse]


class OrganizerCreateRequest(BaseModel):
    user_id: str
    organizer_type_id: str


class OrganizerUpdateRequest(BaseModel):
    user_id: str | None = None
    organizer_type_id: str | None = None


class OrganizerResponseItem(BaseModel):
    id: str
    user_id: str
    organizer_type_id: str
    created_at: str | None = None
    updated_at: str | None = None


class OrganizersByType(BaseModel):
    organizer_type: OrganizerDetailType
    organizers: list[OrganizerDetailUser]


class OrganizersByTypeAll(BaseModel):
    results: list[OrganizersByType]


def organizer_response_item_from_model(organizer: Organizer) -> OrganizerResponseItem:
    """Convert Organizer ORM model to OrganizerResponseItem Pydantic model."""
    return OrganizerResponseItem(
        id=str(organizer.id),
        user_id=str(organizer.user_id),
        organizer_type_id=str(organizer.organizer_type_id),
        created_at=organizer.created_at.isoformat() if organizer.created_at else None,
        updated_at=organizer.updated_at.isoformat() if organizer.updated_at else None,
    )


def organizer_detail_user_from_model(organizer: Organizer) -> OrganizerDetailUser:
    """Convert Organizer ORM model to OrganizerDetailUser Pydantic model."""
    user: User = organizer.user

    return OrganizerDetailUser(
        id=str(user.id),
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        bio=user.bio,
        profile_picture=user.profile_picture,
        email=user.email if user.share_my_email_and_phone_number else None,
        website=user.website if user.share_my_public_social_media else None,
        facebook_username=user.facebook_username
        if user.share_my_public_social_media
        else None,
        linkedin_username=user.linkedin_username
        if user.share_my_public_social_media
        else None,
        instagram_username=user.instagram_username
        if user.share_my_public_social_media
        else None,
        twitter_username=user.twitter_username
        if user.share_my_public_social_media
        else None,
    )


def organizer_detail_response_from_model(
    organizer: Organizer,
) -> OrganizerDetailResponse:
    """Convert Organizer ORM model to OrganizerDetailResponse Pydantic model."""
    organizer_type = organizer.organizer_type
    return OrganizerDetailResponse(
        id=str(organizer.id),
        user=organizer_detail_user_from_model(organizer),
        organizer_type=OrganizerDetailType(
            id=str(organizer_type.id),
            name=organizer_type.name,
        ),
    )


def organizer_detail_response_list_from_models(
    organizers: Sequence[Organizer],
) -> OrganizerDetailResponseList:
    """Convert list of Organizer ORM models to OrganizerDetailResponseList Pydantic model."""
    return OrganizerDetailResponseList(
        results=[organizer_detail_response_from_model(org) for org in organizers],
    )


def organizers_by_type_response_from_models(
    organizer_type: OrganizerType, organizers: Sequence[Organizer]
) -> OrganizersByType:
    """Convert OrganizerType and list of Organizer ORM models to OrganizersByType Pydantic model."""
    return OrganizersByType(
        organizer_type=OrganizerDetailType(
            id=str(organizer_type.id),
            name=organizer_type.name,
        ),
        organizers=[organizer_detail_user_from_model(org) for org in organizers],
    )


class OrganizerUserSchema(BaseModel):
    class UserSchema(BaseModel):
        id: str
        username: Optional[str] = None
        first_name: Optional[str] = None
        last_name: Optional[str] = None
        email: Optional[str] = None

    results: list[UserSchema]
