"""add column order on ticket

Revision ID: 620f0b3ec868
Revises: 10419d21e3d0
Create Date: 2026-06-05 21:56:37.519244

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "620f0b3ec868"
down_revision: Union[str, None] = "10419d21e3d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("ticket", sa.Column("order", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("ticket", "order")
