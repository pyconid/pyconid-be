from datetime import datetime, timedelta
import hashlib
import traceback
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from pytz import timezone
from sqlalchemy.orm import Session
from core.email import send_email_verfication, send_reset_password_email
from core.oauth import github_service, google_service
from core.responses import (
    InternalServerError,
    NoContent,
    common_response,
    Ok,
    BadRequest,
    Forbidden,
    Unauthorized,
    handle_http_exception,
)
from core.security import (
    generate_hash_password,
    generate_token_from_user,
    get_refresh_token_session,
    get_token_exp,
    get_user_from_token,
    invalidate_token,
    invalidate_user_tokens,
    rotate_refresh_token,
    validated_password,
    oauth2_scheme,
)
from core.rate_limiter.memory import InMemoryRateLimiter
from models import get_db_sync
from models.User import User
from schemas.common import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NoContentResponse,
    UnauthorizedResponse,
    ForbiddenResponse,
)
from schemas.auth import (
    EmailVerifiedSuccessResponse,
    ForgotPasswordRequest,
    ForgotPasswordSuccessResponse,
    GoogleSignInResponse,
    GoogleVerifiedResponse,
    LoginEmailRequest,
    LoginSuccessResponse,
    MeResponse,
    GithubVerifiedResponse,
    GithubSignInResponse,
    OauthSignInRequest,
    ResetPasswordRequest,
    ResetPasswordSuccessResponse,
    RefreshTokenRequest,
    SignUpRequest,
    SwaggerTokenResponse,
)
from repository import user as userRepo
from repository import email_verification as emailVerificationRepo
from repository import reset_password as resetPasswordRepo
from settings import (
    AUTH_RATE_LIMIT_PER_WINDOW,
    AUTH_RATE_LIMIT_WINDOW,
    FORGOT_PASSWORD_RATE_LIMIT_PER_EMAIL,
    FORGOT_PASSWORD_RATE_LIMIT_WINDOW,
    FRONTEND_BASE_URL,
    REGISTRATION_CLOSED_MESSAGE,
    REGISTRATION_ENABLED,
    SIGNUP_RATE_LIMIT_PER_WINDOW,
    SIGNUP_RATE_LIMIT_WINDOW,
    TZ,
)

router = APIRouter(prefix="/auth", tags=["Auth"])
auth_rate_limiter = InMemoryRateLimiter()
forgot_password_rate_limiter = InMemoryRateLimiter()
signup_rate_limiter = InMemoryRateLimiter()


def set_oauth_state_cookie(response, request: Request):
    oauth_state = getattr(request.state, "oauth_state", None)
    if oauth_state:
        response.set_cookie(
            key="oauth_state",
            value=oauth_state,
            max_age=600,
            httponly=True,
            secure=(FRONTEND_BASE_URL or "").startswith("https://"),
            samesite="lax",
            path="/auth",
        )
    return response


def clear_oauth_state_cookie(response):
    response.delete_cookie("oauth_state", path="/auth")
    return response


async def check_request_rate_limit(
    limiter: InMemoryRateLimiter,
    request: Request,
    identifier: str,
    scope: str,
    limit: int,
    window: int,
    message: str,
) -> Optional[JSONResponse]:
    client_ip = request.client.host if request.client else "unknown"
    identifier_hash = hashlib.sha256(identifier.strip().lower().encode()).hexdigest()

    for key in (
        f"{scope}:ip:{client_ip}",
        f"{scope}:identifier:{identifier_hash}",
    ):
        is_allowed, retry_after = await limiter.is_allowed(key, limit, window)
        if not is_allowed:
            return JSONResponse(
                status_code=429,
                content={"message": message},
                headers={
                    "Retry-After": str(int(retry_after or 0)),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

    return None


@router.post("/token/", response_model=SwaggerTokenResponse)
async def swagger_form_token(
    http_request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db_sync),
):
    rate_limit_response = await check_request_rate_limit(
        auth_rate_limiter,
        http_request,
        form_data.username,
        "auth",
        AUTH_RATE_LIMIT_PER_WINDOW,
        AUTH_RATE_LIMIT_WINDOW,
        "Too many login attempts",
    )
    if rate_limit_response is not None:
        return rate_limit_response

    user = userRepo.get_user_by_username(db=db, username=form_data.username)
    if user is None:
        return common_response(BadRequest(message="Invalid Credentials"))

    if not user.is_active:
        return common_response(BadRequest(message="Invalid Credentials"))

    is_valid = validated_password(user.password, form_data.password)
    if not is_valid:
        return common_response(BadRequest(message="Invalid Credentials"))

    token, refresh_token = await generate_token_from_user(db=db, user=user)

    return {
        "access_token": token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "token_exp": get_token_exp(token),
        "refresh_token_exp": get_token_exp(refresh_token),
    }


@router.post(
    "/refresh-token/",
    responses={
        "200": {"model": LoginSuccessResponse},
        "401": {"model": UnauthorizedResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
@router.post("/token/refresh/", include_in_schema=False)
async def refresh_token(
    request: RefreshTokenRequest, db: Session = Depends(get_db_sync)
):
    refresh_session = get_refresh_token_session(
        db=db, refresh_token=request.refresh_token
    )
    if refresh_session is None or refresh_session.user is None:
        return common_response(Unauthorized(message="Invalid refresh token"))

    user = refresh_session.user
    if not user.is_active:
        return common_response(Unauthorized(message="Invalid refresh token"))

    token, new_refresh_token = await rotate_refresh_token(
        db=db, refresh_session=refresh_session
    )

    return common_response(
        Ok(
            data={
                "id": str(user.id),
                "username": user.username,
                "is_active": user.is_active,
                "token": token,
                "refresh_token": new_refresh_token,
                "token_exp": get_token_exp(token),
                "refresh_token_exp": get_token_exp(new_refresh_token),
            }
        )
    )


@router.get(
    "/me/",
    responses={
        "200": {"model": MeResponse},
        "401": {"model": UnauthorizedResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def me(db: Session = Depends(get_db_sync), token: str = Depends(oauth2_scheme)):
    user = get_user_from_token(db=db, token=token)
    if user is None:
        return common_response(Unauthorized(message="Invalid Credentials"))

    return common_response(
        Ok(
            data={
                "id": str(user.id),
                "username": user.username,
                "participant_type": user.participant_type,
            }
        )
    )


@router.post(
    "/logout/",
    responses={
        "200": {"model": LoginSuccessResponse},
        "401": {"model": UnauthorizedResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def logout(
    db: Session = Depends(get_db_sync), token: str = Depends(oauth2_scheme)
):
    user = get_user_from_token(db=db, token=token)
    if user is None:
        return common_response(Unauthorized(message="Invalid Credentials"))

    invalidate_token(db=db, token=token)
    return common_response(Ok(data={"message": "logout successfully"}))


@router.post(
    "/email/signup/",
    responses={
        "204": {"model": NoContentResponse},
        "400": {"model": BadRequestResponse},
        "403": {"model": ForbiddenResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def email_signup(
    request: SignUpRequest,
    http_request: Request,
    db: Session = Depends(get_db_sync),
):
    if not REGISTRATION_ENABLED:
        return common_response(
            Forbidden(custom_response={"message": REGISTRATION_CLOSED_MESSAGE})
        )

    rate_limit_response = await check_request_rate_limit(
        signup_rate_limiter,
        http_request,
        request.email,
        "signup",
        SIGNUP_RATE_LIMIT_PER_WINDOW,
        SIGNUP_RATE_LIMIT_WINDOW,
        "Too many registration attempts",
    )
    if rate_limit_response is not None:
        return rate_limit_response

    existing_user = userRepo.get_user_by_email(db=db, email=request.email)
    if existing_user:
        return common_response(BadRequest(message="Email already registered"))

    verification_code = emailVerificationRepo.generate_verification_code()
    expired_at = datetime.now().astimezone(timezone(TZ)) + timedelta(hours=12)
    existing_verification = emailVerificationRepo.get_email_verification_by_email(
        db=db, email=request.email
    )
    if existing_verification:
        emailVerificationRepo.update_email_verification(
            db=db,
            email_verification=existing_verification,
            email=request.email,
            username=request.username,
            password=generate_hash_password(request.password),
            verification_code=verification_code,
            expired_at=expired_at,
            is_commit=False,
        )
    else:
        emailVerificationRepo.create_email_verification(
            db=db,
            email=request.email,
            username=request.username,
            password=generate_hash_password(request.password),
            verification_code=verification_code,
            expired_at=expired_at,
            is_commit=False,
        )
    activation_link = (
        f"{FRONTEND_BASE_URL}/email-verification/?token={verification_code}"
    )
    await send_email_verfication(
        recipient=request.email, activation_link=activation_link
    )
    db.commit()
    return common_response(NoContent())


@router.get(
    "/email/verified/",
    responses={
        "200": {"model": EmailVerifiedSuccessResponse},
        "400": {"model": BadRequestResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def email_verified(
    token: str = None,
    db: Session = Depends(get_db_sync),
):
    if not token:
        return common_response(BadRequest(message="Token not found"))

    email_verification = (
        emailVerificationRepo.get_email_verification_by_verfication_code(
            db=db, verification_code=token
        )
    )
    if not email_verification:
        return common_response(BadRequest(message="Invalid token"))

    if email_verification.expired_at < datetime.now().astimezone(timezone(TZ)):
        emailVerificationRepo.delete_email_verification(
            db=db, email_verification=email_verification
        )
        return common_response(
            BadRequest(message="Token expired. Please register again.")
        )

    existing_user = userRepo.get_user_by_email(db=db, email=email_verification.email)
    if existing_user:
        return common_response(BadRequest(message="Email already registered"))

    now = datetime.now().astimezone(timezone(TZ))
    userRepo.create_user(
        db=db,
        username=email_verification.username,
        password=email_verification.password,
        email=email_verification.email,
        is_active=True,
        created_at=now,
        updated_at=now,
        deleted_at=None,
        is_commit=False,
    )
    emailVerificationRepo.delete_email_verification(
        db=db, email_verification=email_verification, is_commit=False
    )
    db.commit()
    return common_response(Ok(data={"message": "Email verified successfully"}))


@router.post(
    "/email/signin/",
    responses={
        "200": {"model": LoginSuccessResponse},
        "400": {"model": BadRequestResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def email_signin(
    request: LoginEmailRequest,
    http_request: Request,
    db: Session = Depends(get_db_sync),
):
    rate_limit_response = await check_request_rate_limit(
        auth_rate_limiter,
        http_request,
        request.email,
        "auth",
        AUTH_RATE_LIMIT_PER_WINDOW,
        AUTH_RATE_LIMIT_WINDOW,
        "Too many login attempts",
    )
    if rate_limit_response is not None:
        return rate_limit_response

    user = userRepo.get_user_by_email(db=db, email=request.email)
    if user is None:
        return common_response(BadRequest(message="Invalid Credentials"))

    if user.password is None:
        return common_response(BadRequest(message="Invalid Credentials"))

    if not user.is_active:
        return common_response(BadRequest(message="Invalid Credentials"))

    is_valid = validated_password(user.password, request.password)
    if not is_valid:
        return common_response(BadRequest(message="Invalid Credentials"))

    (token, refresh_token) = await generate_token_from_user(db=db, user=user)
    return common_response(
        Ok(
            data={
                "id": str(user.id),
                "username": user.username,
                "is_active": user.is_active,
                "token": token,
                "refresh_token": refresh_token,
                "token_exp": get_token_exp(token),
                "refresh_token_exp": get_token_exp(refresh_token),
            }
        )
    )


@router.post(
    "/email/forgot-password/",
    responses={
        "200": {"model": ForgotPasswordSuccessResponse},
        "400": {"model": BadRequestResponse},
        "429": {"description": "Too many password reset requests"},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def forgot_password(
    request: ForgotPasswordRequest,
    http_request: Request,
    db: Session = Depends(get_db_sync),
):
    rate_limit_response = await check_request_rate_limit(
        forgot_password_rate_limiter,
        http_request,
        request.email,
        "forgot-password",
        FORGOT_PASSWORD_RATE_LIMIT_PER_EMAIL,
        FORGOT_PASSWORD_RATE_LIMIT_WINDOW,
        "Too many password reset requests",
    )
    if rate_limit_response is not None:
        return rate_limit_response

    user = userRepo.get_user_by_email(db=db, email=request.email)
    if user is None:
        return common_response(Ok(data={"message": "Please check your email"}))

    token = resetPasswordRepo.generate_token()
    expired_at = datetime.now().astimezone(timezone(TZ)) + timedelta(hours=12)
    existing_reset_password = resetPasswordRepo.get_reset_password_by_user(
        db=db, user=user
    )
    if existing_reset_password:
        resetPasswordRepo.update_reset_password(
            db=db,
            reset_password=existing_reset_password,
            user=user,
            token=token,
            expired_at=expired_at,
            is_commit=False,
        )
    else:
        existing_reset_password = resetPasswordRepo.create_reset_password(
            db=db,
            user=user,
            token=token,
            expired_at=expired_at,
            is_commit=False,
        )
    reset_link = f"{FRONTEND_BASE_URL}/reset-password/?token={token}"
    await send_reset_password_email(recipient=request.email, reset_link=reset_link)
    db.commit()
    return common_response(Ok(data={"message": "Please check your email"}))


@router.post(
    "/email/reset-password/",
    responses={
        "200": {"model": ResetPasswordSuccessResponse},
        "400": {"model": BadRequestResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def reset_password(
    request: ResetPasswordRequest, db: Session = Depends(get_db_sync)
):
    reset_password = resetPasswordRepo.get_reset_password_by_token(
        db=db, token=request.token
    )
    if not reset_password:
        return common_response(BadRequest(message="Invalid token"))

    if reset_password.expired_at < datetime.now().astimezone(timezone(TZ)):
        resetPasswordRepo.delete_reset_password(db=db, reset_password=reset_password)
        return common_response(BadRequest(message="Token expired"))

    user: User = reset_password.user
    if not user:
        return common_response(BadRequest(message="User not found"))

    user.password = generate_hash_password(request.new_password)
    user.updated_at = datetime.now().astimezone(timezone(TZ))
    db.add(user)

    resetPasswordRepo.delete_reset_password(
        db=db, reset_password=reset_password, is_commit=False
    )
    invalidate_user_tokens(db=db, user_id=user.id)
    return common_response(Ok(data={"message": "Password changed successfully"}))


@router.post(
    "/github/signin/",
    responses={
        "200": {"model": GithubSignInResponse},
        "307": {
            "description": "Redirect to oauth provider",
            "content": {"text/html": {"example": "Redirecting..."}},
        },
        "400": {"model": BadRequestResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def github_signin(http_request: Request, params: OauthSignInRequest = Depends()):
    try:
        authorization_url = await github_service.initiate_oauth(
            request=http_request,
            follow_redirect=params.follow_redirect,
        )

        if isinstance(authorization_url, RedirectResponse):
            return set_oauth_state_cookie(authorization_url, http_request)
        response = common_response(Ok(data={"redirect": authorization_url}))
        return set_oauth_state_cookie(response, http_request)
    except HTTPException as e:
        return handle_http_exception(e)
    except Exception as e:
        traceback.print_exc()
        return common_response(
            InternalServerError(error=f"Failed to initiate OAuth github: {str(e)}")
        )


@router.post(
    "/github/verified/",
    responses={
        "200": {"model": GithubVerifiedResponse},
        "400": {"model": BadRequestResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def github_verified(
    http_request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    db: Session = Depends(get_db_sync),
):
    try:
        if not code:
            return common_response(BadRequest(message="Code not found"))

        oauth_result = await github_service.handle_verified(request=http_request, db=db)

        user = oauth_result["user"]
        is_new_user = oauth_result["is_new_user"]
        provider_user_info = oauth_result["provider_user_info"]

        token, refresh_token = await generate_token_from_user(db=db, user=user)

        response = {
            "token": token,
            "refresh_token": refresh_token,
            "id": str(user.id),
            "username": user.username,
            "is_active": user.is_active,
            "is_new_user": is_new_user,
            "github_username": provider_user_info.get("username"),
            "token_exp": get_token_exp(token),
            "refresh_token_exp": get_token_exp(refresh_token),
        }

        return clear_oauth_state_cookie(common_response(Ok(data=response)))
    except HTTPException as e:
        return handle_http_exception(e)
    except Exception as e:
        traceback.print_exc()
        return common_response(
            InternalServerError(
                error=f"Failed to handle OAuth verified github: {str(e)}"
            )
        )


@router.post(
    "/google/signin/",
    responses={
        "200": {"model": GoogleSignInResponse},
        "307": {
            "description": "Redirect to oauth provider",
            "content": {"text/html": {"example": "Redirecting..."}},
        },
        "400": {"model": BadRequestResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def google_signin(http_request: Request, params: OauthSignInRequest = Depends()):
    try:
        authorization_url = await google_service.initiate_oauth(
            request=http_request,
            follow_redirect=params.follow_redirect,
        )

        if isinstance(authorization_url, RedirectResponse):
            return set_oauth_state_cookie(authorization_url, http_request)
        response = common_response(Ok(data={"redirect": authorization_url}))
        return set_oauth_state_cookie(response, http_request)
    except HTTPException as e:
        return handle_http_exception(e)
    except Exception as e:
        traceback.print_exc()
        return common_response(
            InternalServerError(error=f"Failed to initiate OAuth google: {str(e)}")
        )


@router.post(
    "/google/verified/",
    responses={
        "200": {"model": GoogleVerifiedResponse},
        "400": {"model": BadRequestResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def google_verified(
    http_request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    db: Session = Depends(get_db_sync),
):
    try:
        if not code:
            return common_response(BadRequest(message="Code not found"))

        oauth_result = await google_service.handle_verified(request=http_request, db=db)

        user = oauth_result["user"]
        is_new_user = oauth_result["is_new_user"]
        provider_user_info = oauth_result["provider_user_info"]

        token, refresh_token = await generate_token_from_user(db=db, user=user)

        response = {
            "token": token,
            "refresh_token": refresh_token,
            "id": str(user.id),
            "username": user.username,
            "is_active": user.is_active,
            "is_new_user": is_new_user,
            "google_email": provider_user_info.get("email"),
            "token_exp": get_token_exp(token),
            "refresh_token_exp": get_token_exp(refresh_token),
        }

        return clear_oauth_state_cookie(common_response(Ok(data=response)))
    except HTTPException as e:
        return handle_http_exception(e)
    except Exception as e:
        traceback.print_exc()
        return common_response(
            InternalServerError(
                error=f"Failed to handle OAuth verified google: {str(e)}"
            )
        )
