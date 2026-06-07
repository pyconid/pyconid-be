from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import (
    sessionmaker,
    DeclarativeBase,
    scoped_session,
    Session as SqlalchemySession,
)


from settings import (
    POSTGRES_DATABASE,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)


engine = create_engine(
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DATABASE}",
    pool_size=20,
    max_overflow=0,
    pool_timeout=300,
)
db = sessionmaker(engine, future=True)
factory_session = scoped_session(db)


def get_db_sync():
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_sync_for_test(db: SqlalchemySession):
    def inner():
        yield db

    return inner


"""SQLAlchemy doesn't default to any schema, and PostgreSQL expects it.
    This ensures all models are created in the `public` schema.
"""


class Base(DeclarativeBase):
    metadata = MetaData(schema="public")


# define all model for alembic migration
from models.Country import Country  # NOQA
from models.State import State  # NOQA
from models.City import City  # NOQA
from models.User import User  # NOQA
from models.Token import Token  # NOQA
from models.RefreshToken import RefreshToken  # NOQA
from models.Ticket import Ticket  # NOQA
from models.EmailVerification import EmailVerification  # NOQA
from models.ResetPassword import ResetPassword  # NOQA
from models.Payment import Payment  # NOQA
from models.Room import Room  # NOQA
from models.ScheduleType import ScheduleType  # NOQA
from models.Schedule import Schedule  # NOQA
from models.Speaker import Speaker  # NOQA
from models.Voucher import Voucher  # NOQA
from models.Stream import Stream  # NOQA
from models.StreamWatchSession import StreamWatchSession  # NOQA
from models.SpeakerType import SpeakerType  # NOQA
from models.Volunteer import Volunteer  # NOQA
