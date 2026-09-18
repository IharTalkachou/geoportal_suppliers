"""add report_supplier_selections

Именованные выборки поставщиков для фильтра отчётов: набор из двух десятков
банков не приходится выбирать заново при каждом построении отчёта.

Выборка - вспомогательная сущность: в самих отчётах она не отображается и
не идентифицируется, только подставляет список поставщиков в фильтр. Состав
хранится массивом supplier_id в JSONB, а не таблицей-связкой: выборка всегда
читается и переписывается целиком, join-ов и выборочных запросов по её
элементам нет. Обратная сторона - FK на suppliers тут не действует, поэтому
удалённый поставщик останется "висеть" идентификатором; UI отбрасывает
идентификаторы, которых нет в текущем списке.

Выборки общие для всех пользователей (решение зафиксировано при постановке
задачи): собранный однажды список доступен всей команде. created_by хранится
для справки, на доступ не влияет.

Revision ID: a9e3c47b1d52
Revises: f4c7a91e26b8
Create Date: 2026-09-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a9e3c47b1d52'
down_revision: Union[str, Sequence[str], None] = 'f4c7a91e26b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'report_supplier_selections',
        sa.Column('selection_id', sa.Integer(), autoincrement=True, nullable=False,
                  comment='Идентификатор выборки'),
        sa.Column('selection_name', sa.Text(), nullable=False,
                  comment='Название выборки, например «Банки»'),
        sa.Column('supplier_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb"),
                  comment='Массив supplier_id, входящих в выборку'),
        sa.Column('created_by', sa.Integer(), nullable=True,
                  comment='Автор выборки; выборка общая, автор нужен только для справки'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=True, comment='Дата создания выборки'),
        sa.ForeignKeyConstraint(['created_by'], ['users.user_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('selection_id'),
        sa.UniqueConstraint('selection_name', name='unique_report_selection_name'),
        comment='Именованные выборки поставщиков для фильтров отчётов (общие для всех пользователей)',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('report_supplier_selections')
