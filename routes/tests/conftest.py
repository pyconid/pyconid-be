import pytest
from sqlalchemy import event

from models.User import User
from routes.auth import (
    auth_rate_limiter,
    forgot_password_rate_limiter,
    signup_rate_limiter,
)


@pytest.fixture(autouse=True)
def activate_test_users():
    """Keep authentication fixtures active unless a test explicitly disables them."""

    def set_active(user, args, kwargs):
        if "is_active" not in kwargs:
            user.is_active = True

    event.listen(User, "init", set_active)
    for limiter in (
        auth_rate_limiter,
        forgot_password_rate_limiter,
        signup_rate_limiter,
    ):
        limiter._requests.clear()
    yield
    event.remove(User, "init", set_active)
