"""seed subscription tiers

Revision ID: 3d6b838a3069
Revises: 6ba569cfa653
Create Date: 2026-09-13 19:02:15.398561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d6b838a3069'
down_revision: Union[str, Sequence[str], None] = '6ba569cfa653'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("INSERT INTO subscription_tiers(name,rank) VALUES ('Premium',30),('Pro',20),('Basic',10)")  


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM subscription_tiers WHERE name IN ('Premium','Basic','Pro')")
