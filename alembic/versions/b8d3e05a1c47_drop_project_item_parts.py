"""drop the obsolete project_item_parts table

Части вида сведений переехали в справочник (info_type_parts, ревизия a4f7c21e8b93),
а условия их передачи конкретным поставщиком - в project_item_part_details.
Данные перенесены там же, охват документов перевешен на новые part_id.

Эта ревизия отделена от переноса намеренно: между ними обе таблицы сосуществуют,
данные можно сверить, и только потом удалять. К моменту применения ни один запрос
в src/ не читает project_item_parts - последним был отчёт №9.

Revision ID: b8d3e05a1c47
Revises: a4f7c21e8b93
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d3e05a1c47'
down_revision: Union[str, Sequence[str], None] = 'a4f7c21e8b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index('idx_item_parts_item', table_name='project_item_parts')
    op.drop_table('project_item_parts')


def downgrade() -> None:
    """Downgrade schema.

    Таблица воссоздаётся пустой: содержимое не восстанавливается. Части живут
    в info_type_parts, и обратное сопоставление части конкретному item_id
    потеряно ещё при переносе (a4f7c21e8b93). Для отката с данными -
    восстанавливаться из дампа.
    """
    op.create_table(
        'project_item_parts',
        sa.Column('part_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('part_name', sa.Text(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['project_items.item_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('part_id'),
        sa.UniqueConstraint('item_id', 'part_name', name='unique_item_part_name'),
        comment='Части вида сведений в составе проекта, передаваемые отдельными протоколами',
    )
    op.create_index('idx_item_parts_item', 'project_item_parts', ['item_id'], unique=False)
