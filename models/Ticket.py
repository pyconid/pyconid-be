import uuid
from sqlalchemy import UUID, String, Integer, Boolean
from sqlalchemy.orm import mapped_column, Mapped
from models import Base


class Ticket(Base):
    __tablename__ = "ticket"

    id: Mapped[str] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column("name", String, nullable=False)
    price: Mapped[int] = mapped_column("price", Integer, nullable=False)
    user_participant_type: Mapped[str] = mapped_column(
        "user_participant_type", String, nullable=False
    )
    is_sold_out: Mapped[bool] = mapped_column("is_sold_out", Boolean, default=False)
    is_active: Mapped[bool] = mapped_column("is_active", Boolean, default=True)
    description: Mapped[str] = mapped_column("description", String, nullable=True)
    order: Mapped[int] = mapped_column("order", Integer, nullable=True)
