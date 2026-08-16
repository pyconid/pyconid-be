from typing import Optional
from fastapi import Query
from pydantic import BaseModel, Field
from enum import Enum


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginEmailRequest(BaseModel):
    email: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenPairResponse(BaseModel):
    token: str
    refresh_token: str
    token_exp: int
    refresh_token_exp: int


class LoginSuccessResponse(TokenPairResponse):
    id: str
    username: str
    is_active: bool


class SwaggerTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    token_exp: int
    refresh_token_exp: int


class MeResponse(BaseModel):
    id: str
    username: str
    participant_type: Optional[str] = None


class LogoutSuccessResponse(BaseModel):
    message: str


class SignUpRequest(BaseModel):
    email: str
    username: str
    password: str


class EmailVerifiedSuccessResponse(BaseModel):
    message: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ForgotPasswordSuccessResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ResetPasswordSuccessResponse(BaseModel):
    message: str


class OauthSignInRequest(BaseModel):
    follow_redirect: Optional[bool] = Field(Query(False, description="Follow redirect"))


class GithubSignInResponse(BaseModel):
    redirect: str


class GithubVerifiedResponse(TokenPairResponse):
    id: str
    username: str
    is_active: bool
    is_new_user: bool
    github_username: str


class GoogleSignInResponse(BaseModel):
    redirect: str


class GoogleVerifiedResponse(TokenPairResponse):
    id: str
    username: str
    is_active: bool
    is_new_user: bool
    google_email: str


class AuthorizationStatusEnum(str, Enum):
    FORBIDDEN = "forbidden"
    UNAUTHORIZED = "unauthorized"
    PASSED = "passed"
