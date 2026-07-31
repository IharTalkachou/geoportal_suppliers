"""set security_invoker on v_bi_flat_export view

Revision ID: 3dfa3c81c583
Revises: 4c9745be22b9
Create Date: 2026-07-15 09:35:25.219001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3dfa3c81c583'
down_revision: Union[str, Sequence[str], None] = '4c9745be22b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # View по умолчанию выполняется как SECURITY DEFINER (правами владельца-создателя),
    # что обходит RLS-политики для любой запрашивающей роли. security_invoker=true
    # переключает её на выполнение с правами вызывающей роли (Postgres 15+).
    op.execute("ALTER VIEW public.v_bi_flat_export SET (security_invoker = true)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER VIEW public.v_bi_flat_export RESET (security_invoker)")
