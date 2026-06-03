from datetime import date, datetime
from typing import Optional
from fastapi import Form, UploadFile, File
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import EmailStr
from pytz import timezone
from core.file import get_file, is_over_max_file_size, upload_file
from models.User import MANAGEMENT_PARTICIPANT, User
from schemas.user_profile import (
    DetailSearchUserProfile,
    Gender,
    IndustryCategory,
    JobCategory,
    LookingForOption,
    ParticipantType,
    ParticipantTypeDropdownResponse,
    SearchUserProfileResponse,
    TShirtSize,
    UserProfileCreate,
    UserProfileDB,
    UserProfileEditSuccessResponse,
    UserProfilePrivate,
    EnumDropdownItem,
    IndustryCategoryDropdownResponse,
    JobCategoryDropdownResponse,
)
from sqlalchemy.orm import Session
from core.responses import (
    BadRequest,
    Forbidden,
    InternalServerError,
    NotFound,
    Ok,
    common_response,
    Unauthorized,
)
from core.security import (
    get_current_user,
    get_user_from_token,
)
from models import get_db_sync
from schemas.common import (
    BadRequestResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    UnauthorizedResponse,
    ValidationErrorResponse,
)
from repository import user as userRepo
from settings import MAX_FILE_SIZE_MB
from validators.location import LocationValidationError, validate_location_hierarchy

router = APIRouter(prefix="/user-profile", tags=["UserProfile"])


@router.get(
    "/search/",
    responses={
        "200": {"model": SearchUserProfileResponse},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def search_user_profiles(
    search: Optional[str] = None,
    participant_type: Optional[ParticipantType] = None,
    db: Session = Depends(get_db_sync),
    user: User = Depends(get_current_user),
):
    if user is None:
        return common_response(Unauthorized(message="Unauthorized"))

    if user.participant_type != MANAGEMENT_PARTICIPANT:
        return common_response(Forbidden())

    all_user = userRepo.get_all_user(
        db=db, search=search, paritcipant_type=participant_type
    )
    return common_response(
        Ok(
            data=SearchUserProfileResponse(
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
            ).model_dump()
        )
    )


# === PUT endpoint ===


@router.put(
    "/",
    responses={
        "200": {"model": UserProfileEditSuccessResponse},
        "400": {"model": BadRequestResponse},
        "422": {"model": ValidationErrorResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def update_user_profile(
    profile_picture: Optional[UploadFile] = File(None),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: Optional[EmailStr] = Form(None),
    share_my_email_and_phone_number: Optional[bool] = Form(None),
    industry_categories: Optional[IndustryCategory] = Form(None),
    company: Optional[str] = Form(None),
    job_category: JobCategory = Form(...),
    job_title: str = Form(...),
    share_my_job_and_company: Optional[bool] = Form(None),
    experience: Optional[int] = Form(None),
    t_shirt_size: Optional[TShirtSize] = Form(None),
    gender: Optional[Gender] = Form(None),
    date_of_birth: Optional[date] = Form(None),
    phone: Optional[str] = Form(None),
    country_id: int = Form(...),
    state_id: Optional[int] = Form(None),
    city_id: Optional[int] = Form(None),
    zip_code: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    share_my_location: Optional[bool] = Form(None),
    bio: str = Form(...),
    interest: Optional[str] = Form(None),  # comma separated
    share_my_interest: Optional[bool] = Form(None),
    looking_for: Optional[LookingForOption] = Form(None),
    expertise: Optional[str] = Form(None),  # comma separated
    website: Optional[str] = Form(None),
    github_username: Optional[str] = Form(None),
    facebook_username: Optional[str] = Form(None),
    linkedin_username: Optional[str] = Form(None),
    twitter_username: Optional[str] = Form(None),
    instagram_username: Optional[str] = Form(None),
    share_my_public_social_media: Optional[bool] = Form(None),
    share_my_data_to_sponsor: Optional[bool] = Form(None),
    retain_my_data_for_next_pycon: Optional[bool] = Form(None),
    coc_acknowledged: bool = Form(...),
    terms_agreed: bool = Form(...),
    privacy_agreed: bool = Form(...),
    db: Session = Depends(get_db_sync),
    user: User = Depends(get_current_user),
):
    if user is None:
        return common_response(Unauthorized(message="Unauthorized"))
    if country_id:
        try:
            validate_location_hierarchy(
                db=db,
                country_id=country_id,
                state_id=state_id,
                city_id=city_id,
                zip_code=zip_code,
            )
        except LocationValidationError as e:
            return common_response(BadRequest(message=str(e)))

    # semua field dari UserProfileCreate.
    user_profile_pydantic = UserProfileCreate(
        first_name=first_name,
        last_name=last_name,
        email=email,
        share_my_email_and_phone_number=share_my_email_and_phone_number,
        industry_categories=industry_categories,
        company=company,
        share_my_job_and_company=share_my_job_and_company,
        share_my_interest=share_my_interest,
        job_category=job_category,
        job_title=job_title,
        experience=experience,
        t_shirt_size=t_shirt_size,
        gender=gender,
        date_of_birth=date_of_birth,
        phone=phone,
        country_id=country_id,
        state_id=state_id,
        city_id=city_id,
        zip_code=zip_code,
        address=address,
        share_my_location=share_my_location,
        bio=bio,
        interest=interest,
        looking_for=looking_for,
        expertise=expertise,
        website=website,
        github_username=github_username,
        facebook_username=facebook_username,
        linkedin_username=linkedin_username,
        twitter_username=twitter_username,
        instagram_username=instagram_username,
        share_my_public_social_media=share_my_public_social_media,
        share_my_data_to_sponsor=share_my_data_to_sponsor,
        retain_my_data_for_next_pycon=retain_my_data_for_next_pycon,
        coc_acknowledged=coc_acknowledged,
        terms_agreed=terms_agreed,
        privacy_agreed=privacy_agreed,
    )
    # 1. Simpan file dan dapatkan URL
    profile_picture_url = None
    if profile_picture:
        if is_over_max_file_size(upload_file=profile_picture):
            return common_response(
                BadRequest(
                    message=f"File size exceeds the maximum limit ({MAX_FILE_SIZE_MB} mb)"
                )
            )
        now = datetime.now().astimezone(timezone("Asia/Jakarta"))
        profile_picture_url = f"{first_name}-{last_name}-profile-photo-{now.strftime('%Y%m%d%H%M%S')}-{profile_picture.filename}"
        await upload_file(upload_file=profile_picture, path=profile_picture_url)
        # profile_picture_url = save_file_and_get_url(profile_picture)

    # 2. Gabungkan data. user_form.model_dump() akan berisi
    user_profile_dict = user_profile_pydantic.model_dump()
    user_profile_dict["participant_type"] = user.participant_type
    if profile_picture_url:
        user_profile_dict["profile_picture"] = profile_picture_url

    # 3. Validasi dengan model DB
    # UserProfileDB akan mengharapkan semua field dari Create + profile_picture
    validated_profile = UserProfileDB(**user_profile_dict)

    # ... simpan ke database ...
    # Simpan ke posgres
    try:
        userRepo.update_user_profile(
            db=db, user_id=user.id, profile_data=validated_profile
        )
    except Exception as e:
        return common_response(
            InternalServerError(error=f"Failed to update profile {str(e)}")
        )

    return validated_profile


# === GET endpoint ===


@router.get(
    "/",
    responses={
        "200": {"model": UserProfilePrivate},
        "401": {"model": UnauthorizedResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def get_user_profile(user: User = Depends(get_current_user)):
    if user is None:
        return common_response(Unauthorized(message="Unauthorized"))
    user_schema = UserProfilePrivate.model_validate(user)
    return user_schema


@router.get("/{token}/profile-picture/", response_class=FileResponse)
async def get_user_profile_picture(token: str, db: Session = Depends(get_db_sync)):
    user = get_user_from_token(db, token)
    if user is None:
        return common_response(Unauthorized(message="Unauthorized"))
    if user.profile_picture is None:
        return common_response(NotFound(message="Profile picture not found"))

    photo = get_file(path=user.profile_picture)
    if photo is None:
        return common_response(NotFound(message="Profile picture file not found"))

    return photo


@router.get(
    "/options/industries",
    responses={"200": {"model": IndustryCategoryDropdownResponse}},
)
async def get_industry_options():
    items = [
        EnumDropdownItem(value=category.value, label=category.value)
        for category in IndustryCategory
    ]
    return IndustryCategoryDropdownResponse(results=items)


@router.get("/options/jobs", responses={"200": {"model": JobCategoryDropdownResponse}})
async def get_job_options():
    items = [
        EnumDropdownItem(value=category.value, label=category.value)
        for category in JobCategory
    ]
    return JobCategoryDropdownResponse(results=items)


@router.get(
    "/options/participation-types",
    responses={"200": {"model": ParticipantTypeDropdownResponse}},
)
async def get_participant_type_options():
    items = [
        EnumDropdownItem(value=ptype.value, label=ptype.value)
        for ptype in ParticipantType
    ]
    return ParticipantTypeDropdownResponse(results=items)
