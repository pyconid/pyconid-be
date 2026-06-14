import datetime
import uuid
from models import Base
from sqlalchemy import UUID, DateTime, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship


class Organizer(Base):
    __tablename__ = "organizer"

    id: Mapped[str] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(
        "user_id", ForeignKey("user.id"), nullable=False
    )
    organizer_type_id: Mapped[str] = mapped_column(
        "organizer_type_id", ForeignKey("organizer_type.id"), nullable=True
    )
    created_at = mapped_column(
        "created_at",
        DateTime(timezone=True),
        default=datetime.datetime.now(datetime.timezone.utc),
    )
    updated_at = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        default=datetime.datetime.now(datetime.timezone.utc),
    )
    deleted_at = mapped_column("deleted_at", DateTime(timezone=True), nullable=True)
    # Relationships
    user = relationship("User", back_populates="organizer")
    organizer_type = relationship("OrganizerType", backref="organizer_organizer_type")
