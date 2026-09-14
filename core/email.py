from fastapi_mail import ConnectionConfig, FastMail, MessageSchema
from settings import (
    MAIL_USERNAME,
    MAIL_PASSWORD,
    MAIL_FROM,
    MAIL_PORT,
    MAIL_SERVER,
    MAIL_FROM_NAME,
    MAIL_TLS,
    MAIL_SSL,
    USE_CREDENTIALS,
)


conf_static = ConnectionConfig(
    MAIL_USERNAME=MAIL_USERNAME,
    MAIL_PASSWORD=MAIL_PASSWORD,
    MAIL_FROM=MAIL_FROM,
    MAIL_PORT=MAIL_PORT,
    MAIL_SERVER=MAIL_SERVER,
    MAIL_FROM_NAME=MAIL_FROM_NAME,
    MAIL_STARTTLS=MAIL_TLS,
    MAIL_SSL_TLS=MAIL_SSL,
    USE_CREDENTIALS=USE_CREDENTIALS,
    TEMPLATE_FOLDER="./core/mail_templates/",
)


async def try_send_email(recipient: str, name: str = "User"):
    """
    Function for sending email\n
    """
    fm = FastMail(conf_static)
    await fm.send_message(
        message=MessageSchema(
            subject="Test email",
            recipients=[recipient],
            template_body={"name": name},
            subtype="html",
        ),
        template_name="test_email.html",
    )


async def send_email_verfication(recipient: str, activation_link: str):
    fm = FastMail(conf_static)
    await fm.send_message(
        message=MessageSchema(
            subject="Activate your account",
            recipients=[recipient],
            template_body={"activation_link": activation_link},
            subtype="html",
        ),
        template_name="email_verification.html",
    )


async def send_reset_password_email(recipient: str, reset_link: str):
    fm = FastMail(conf_static)
    await fm.send_message(
        message=MessageSchema(
            subject="Reset your password",
            recipients=[recipient],
            template_body={"reset_link": reset_link},
            subtype="html",
        ),
        template_name="reset_password.html",
    )
