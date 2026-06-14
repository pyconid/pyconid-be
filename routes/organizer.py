from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from core.file import get_file

from core.log import logger
from core.responses import (
    BadRequest,
    Forbidden,
    InternalServerError,
    NotFound,
    Ok,
    Unauthorized,
    common_response,
)

from core.security import check_permissions, get_current_user
from models import get_db_sync
from models.User import MANAGEMENT_PARTICIPANT, User
from repository.organizer import (
    delete_organizer_data,
    get_organizer_by_id,
    get_organizers_by_type,
    get_organizer_by_user_id,
    insert_organizer,
    update_organizer_data,
    get_all_organizers,
    get_organizer_by_type,
    organizers_by_type_response_from_models,
)
from repository.organizer_type import get_organizer_type_by_id
from repository.user import get_all_user, get_user_by_id
from schemas.auth import AuthorizationStatusEnum
from schemas.organizer import (
    OrganizerCreateRequest,
    OrganizerUpdateRequest,
    organizer_detail_response_from_model,
    organizer_response_item_from_model,
    organizer_detail_response_list_from_models,
    OrganizerQuery,
    OrganizerDetailResponseList,
    OrganizersByTypeAll,
    OrganizersByType,
    OrganizerResponseItem,
    OrganizerDetailResponse,
    OrganizerUserSchema,
)
from schemas.common import (
    InternalServerErrorResponse,
    BadRequestResponse,
    UnauthorizedResponse,
    NotFoundResponse,
    ForbiddenResponse,
    OkResponse,
)

router = APIRouter(prefix="/organizer", tags=["Organizer"])


@router.get(
    "/type",
    responses={
        "200": {"model": OrganizersByTypeAll},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def get_organizers_grouped_by_type(
    db: Session = Depends(get_db_sync),
    current_user: User | None = Depends(get_current_user),
):
    logger.info("Fetching organizers grouped by type")
    auth_status = check_permissions(current_user, MANAGEMENT_PARTICIPANT)
    if auth_status == AuthorizationStatusEnum.UNAUTHORIZED:
        return common_response(Unauthorized(message="Unauthorized"))
    if auth_status == AuthorizationStatusEnum.FORBIDDEN:
        return common_response(
            Forbidden(custom_response="Forbidden: Insufficient permissions")
        )
    try:
        data = get_organizers_by_type(db=db)
        if data is None:
            logger.error("No organizers found grouped by type")
            return common_response(NotFound(message="No organizers found"))
        return common_response(Ok(data=data.model_dump()))
    except Exception as e:
        logger.error(f"Error fetching organizers by type: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.get(
    "/public",
    responses={
        "200": {"model": OrganizerDetailResponseList},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def get_organizers_public(
    db: Session = Depends(get_db_sync),
    query: OrganizerQuery = Depends(),
):
    logger.info("Fetching all organizers")
    try:
        data = get_all_organizers(db=db, search=query.search, order_dir=query.order_dir)
        if data is None:
            return common_response(NotFound(message="No organizers found"))

        model_data = organizer_detail_response_list_from_models(data)
        return common_response(Ok(data=model_data.model_dump()))
    except Exception as e:
        logger.error(f"Error fetching organizers by type: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.get(
    "/",
    responses={
        "200": {"model": OrganizerDetailResponseList},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def get_organizers(
    db: Session = Depends(get_db_sync),
    query: OrganizerQuery = Depends(),
    current_user: User | None = Depends(get_current_user),
):
    logger.info("Fetching all organizers")
    auth_status = check_permissions(current_user, MANAGEMENT_PARTICIPANT)
    if auth_status == AuthorizationStatusEnum.UNAUTHORIZED:
        return common_response(Unauthorized(message="Unauthorized"))
    if auth_status == AuthorizationStatusEnum.FORBIDDEN:
        return common_response(
            Forbidden(custom_response="Forbidden: Insufficient permissions")
        )
    try:
        data = get_all_organizers(db=db, search=query.search, order_dir=query.order_dir)
        if data is None:
            return common_response(NotFound(message="No organizers found"))

        model_data = organizer_detail_response_list_from_models(data)
        return common_response(Ok(data=model_data.model_dump()))
    except Exception as e:
        logger.error(f"Error fetching organizers by type: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.get(
    "/type/{organizer_type_id}",
    responses={
        "200": {"model": OrganizersByType},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def find_organizer_by_type(
    organizer_type_id: str,
    db: Session = Depends(get_db_sync),
    current_user: User | None = Depends(get_current_user),
):
    logger.info("Fetching all organizers")
    auth_status = check_permissions(current_user, MANAGEMENT_PARTICIPANT)
    if auth_status == AuthorizationStatusEnum.UNAUTHORIZED:
        return common_response(Unauthorized(message="Unauthorized"))
    if auth_status == AuthorizationStatusEnum.FORBIDDEN:
        return common_response(
            Forbidden(custom_response="Forbidden: Insufficient permissions")
        )
    try:
        orgnizer_type = get_organizer_type_by_id(db=db, id=organizer_type_id)
        if not orgnizer_type:
            logger.error(f"Organizer type with ID {organizer_type_id} not found")
            return common_response(NotFound(message="Organizer type not found"))
        data = get_organizer_by_type(db=db, organizer_type=orgnizer_type)
        if data is None:
            return common_response(NotFound(message="No organizers found"))

        model_data = organizers_by_type_response_from_models(
            organizer_type=orgnizer_type, organizers=data
        )
        return common_response(Ok(data=model_data.model_dump()))
    except Exception as e:
        logger.error(f"Error fetching organizers by type: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.post(
    "/",
    responses={
        "200": {"model": OrganizerResponseItem},
        "400": {"model": BadRequestResponse},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def create_organizer(
    create_request: OrganizerCreateRequest,
    db: Session = Depends(get_db_sync),
    current_user: User | None = Depends(get_current_user),
):
    logger.info("Creating a new organizer")
    auth_status = check_permissions(current_user, MANAGEMENT_PARTICIPANT)
    if auth_status == AuthorizationStatusEnum.UNAUTHORIZED:
        return common_response(Unauthorized(message="Unauthorized"))
    if auth_status == AuthorizationStatusEnum.FORBIDDEN:
        return common_response(
            Forbidden(custom_response="Forbidden: Insufficient permissions")
        )
    try:
        organizer_type = get_organizer_type_by_id(db, create_request.organizer_type_id)

        if not organizer_type:
            logger.error(
                f"Organizer type with ID {create_request.organizer_type_id} not found"
            )
            return common_response(NotFound(message="Organizer type not found"))

        user = get_user_by_id(db, create_request.user_id)
        if not user:
            logger.error(f"User with ID {create_request.user_id} not found")
            return common_response(NotFound(message="User not found"))

        existing_organizer = get_organizer_by_user_id(db, create_request.user_id)
        if existing_organizer:
            logger.error(
                f"User with ID {create_request.user_id} is already an organizer"
            )
            return common_response(
                BadRequest(
                    custom_response=f"Organizer for user id {create_request.user_id} already exists"
                )
            )
        new_organizer = insert_organizer(db, user, organizer_type)
        response = organizer_response_item_from_model(new_organizer)
        return common_response(Ok(data=response.model_dump()))
        logger.info(f"Organizer created with ID: {new_organizer.id}")
    except ValueError as ve:
        logger.error(f"Value error: User already an organizer of this type - {ve}")
        return common_response(
            BadRequest(custom_response="User already an organizer of this type")
        )
    except Exception as e:
        logger.error(f"Error creating organizer: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.get(
    "/user/",
    responses={
        "200": {"model": OrganizerUserSchema},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def get_users_for_organizer(
    search: str | None = Query(
        None, description="Search users by name, username, or email"
    ),
    db: Session = Depends(get_db_sync),
    current_user: User | None = Depends(get_current_user),
):
    logger.info("Fetching users not assigned as organizer")
    auth_status = check_permissions(current_user, MANAGEMENT_PARTICIPANT)
    if auth_status == AuthorizationStatusEnum.UNAUTHORIZED:
        return common_response(Unauthorized(message="Unauthorized"))
    if auth_status == AuthorizationStatusEnum.FORBIDDEN:
        return common_response(
            Forbidden(custom_response="Forbidden: Insufficient permissions")
        )

    try:
        users = get_all_user(db=db, search=search, is_organizer=False)
        available_users = OrganizerUserSchema(
            results=[
                OrganizerUserSchema.UserSchema(
                    id=str(user.id),
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    email=user.email,
                )
                for user in users
                if not user.organizer
            ]
        )
        return common_response(Ok(data=available_users.model_dump()))
    except Exception as e:
        logger.error(f"Error fetching users for organizer: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.get(
    "/{organizer_id}",
    responses={
        "200": {"model": OrganizerDetailResponse},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def find_organizer_by_id(
    organizer_id: str,
    db: Session = Depends(get_db_sync),
    current_user: User | None = Depends(get_current_user),
):
    logger.info(f"Fetching organizer with ID: {organizer_id}")
    auth_status = check_permissions(current_user, MANAGEMENT_PARTICIPANT)
    if auth_status == AuthorizationStatusEnum.UNAUTHORIZED:
        return common_response(Unauthorized(message="Unauthorized"))
    if auth_status == AuthorizationStatusEnum.FORBIDDEN:
        return common_response(
            Forbidden(custom_response="Forbidden: Insufficient permissions")
        )
    try:
        organizer = get_organizer_by_id(db, organizer_id)
        if not organizer:
            logger.error(f"Organizer with ID {organizer_id} not found")
            return common_response(NotFound(message="Organizer not found"))
        response = organizer_detail_response_from_model(organizer)
        return common_response(Ok(data=response.model_dump()))
    except Exception as e:
        logger.error(f"Error fetching organizer: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.put(
    "/{organizer_id}",
    responses={
        "200": {"model": OrganizerDetailResponse},
        "400": {"model": BadRequestResponse},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def update_organizer_by_id(
    organizer_id: str,
    payload: OrganizerUpdateRequest,
    db: Session = Depends(get_db_sync),
    current_user: User | None = Depends(get_current_user),
):
    logger.info(f"Updating organizer with ID: {organizer_id}")
    auth_status = check_permissions(current_user, MANAGEMENT_PARTICIPANT)
    if auth_status == AuthorizationStatusEnum.UNAUTHORIZED:
        return common_response(Unauthorized(message="Unauthorized"))
    if auth_status == AuthorizationStatusEnum.FORBIDDEN:
        return common_response(
            Forbidden(custom_response="Forbidden: Insufficient permissions")
        )
    try:
        organizer = get_organizer_by_id(id=organizer_id, db=db)
        if not organizer:
            logger.error(f"Organizer with ID {organizer_id} not found")
            return common_response(NotFound(message="Organizer not found"))
        organizer_type_id = payload.organizer_type_id or organizer.organizer_type_id
        organizer_type = get_organizer_type_by_id(db=db, id=organizer_type_id)

        if not organizer_type:
            logger.error(f"Organizer type with ID {organizer_type_id} not found")
            return common_response(NotFound(message="Organizer type not found"))

        user_id = payload.user_id or organizer.user_id
        user = get_user_by_id(db=db, id=user_id)
        if not user:
            logger.error(f"User with ID {user_id} not found")
            return common_response(NotFound(message="User not found"))
        existing_organizer = get_organizer_by_user_id(db, user.id)

        if existing_organizer is not None and existing_organizer.id != organizer.id:
            logger.error(f"User with ID {user_id} is already an organizer")
            return common_response(
                BadRequest(
                    custom_response=f"Organizer for user id {user_id} already exists"
                )
            )
        update_organizer = update_organizer_data(
            db=db,
            organizer=organizer,
            user=user,
            organizer_type=organizer_type,
        )
        response = organizer_detail_response_from_model(update_organizer)
        return common_response(Ok(data=response.model_dump()))
    except Exception as e:
        logger.error(f"Error updating organizer: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.delete(
    "/{organizer_id}",
    responses={
        "200": {"model": OkResponse},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def delete_organizer(
    organizer_id: str,
    db: Session = Depends(get_db_sync),
    current_user: User | None = Depends(get_current_user),
):
    logger.info(f"Deleting organizer with ID: {organizer_id}")
    auth_status = check_permissions(current_user, MANAGEMENT_PARTICIPANT)
    if auth_status == AuthorizationStatusEnum.UNAUTHORIZED:
        return common_response(Unauthorized(message="Unauthorized"))
    if auth_status == AuthorizationStatusEnum.FORBIDDEN:
        return common_response(
            Forbidden(custom_response="Forbidden: Insufficient permissions")
        )
    try:
        organizer = get_organizer_by_id(id=organizer_id, db=db)
        if not organizer:
            logger.error(f"Organizer with ID {organizer_id} not found")
            return common_response(NotFound(message="Organizer not found"))
        delete_organizer_data(db, organizer)
        logger.info(f"Organizer with ID: {organizer_id} deleted successfully")
        return common_response(Ok(data={"message": "Organizer deleted successfully"}))
    except Exception as e:
        logger.error(f"Error deleting organizer: {e}")
        return common_response(InternalServerError(error=str(e)))


@router.get(
    "/{organizer_id}/profile-picture",
    response_class=FileResponse,
    responses={
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "404": {"model": NotFoundResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
def get_organizer_profile_picture(
    organizer_id: str, db: Session = Depends(get_db_sync)
):
    logger.info(f"Getting profile picture for organizer ID: {organizer_id}")
    try:
        organizer = get_organizer_by_id(db, organizer_id)
        if not organizer:
            logger.error(f"Organizer with ID {organizer_id} not found")
            return common_response(NotFound(message="Organizer not found"))

        if organizer.user.profile_picture is None:
            logger.error(f"Organizer with ID {organizer_id} has no profile picture")
            return common_response(NotFound(message="Profile picture not found"))
        profile_picture = get_file(organizer.user.profile_picture)
        if profile_picture is None:
            logger.error(
                f"Profile picture file for organizer ID {organizer_id} not found"
            )
            return common_response(NotFound(message="Profile picture not found"))
        return profile_picture
    except Exception as e:
        logger.error(f"Error fetching profile picture: {e}")
        return common_response(InternalServerError(error=str(e)))
