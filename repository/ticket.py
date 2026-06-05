from sqlalchemy import select
from sqlalchemy.orm import Session
from models.Ticket import Ticket


def get_active_tickets(db: Session):
    return db.query(Ticket).filter(Ticket.is_active).order_by(Ticket.order.asc()).all()


def get_active_ticket_by_id(db: Session, ticket_id: str):
    query = select(Ticket).where(Ticket.id == ticket_id, Ticket.is_active)
    return db.execute(query).scalars().first()
