"""add ref_data_methods

Справочник способов передачи данных ("Способ (данные)" в составе проекта и
в параметрах передачи по частям). Раньше список был зашит в код в двух местах
project_dashboard.py; теперь правится в Админ-панели -> Справочники.

Значения в project_items.data_method / project_item_part_details.data_method
остаются текстом (без FK): так они хранились и раньше, а переименование в
админ-панели само переписывает их в обеих таблицах.

Начальное наполнение - прежний список из кода, в том же порядке.

Revision ID: b2d6e83f4a17
Revises: a9e3c47b1d52
Create Date: 2026-10-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d6e83f4a17'
down_revision: Union[str, Sequence[str], None] = 'a9e3c47b1d52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INITIAL_METHODS = ["Сервис (WMS/WFS)", "Ссылка на облако", "Прямая загрузка", "Носитель", "Не передаются"]


def upgrade() -> None:
    """Upgrade schema."""
    table = op.create_table(
        'ref_data_methods',
        sa.Column('method_id', sa.Integer(), autoincrement=True, nullable=False,
                  comment='Идентификатор способа'),
        sa.Column('method_name', sa.String(length=50), nullable=False,
                  comment='Способ передачи данных, например «Сервис (WMS/WFS)»'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0',
                  comment='Порядок в выпадающем списке'),
        sa.PrimaryKeyConstraint('method_id'),
        sa.UniqueConstraint('method_name', name='unique_data_method_name'),
        comment='Справочник способов передачи данных (Способ (данные) в составе проекта)',
    )
    op.bulk_insert(table, [{'method_name': m, 'sort_order': n}
                           for n, m in enumerate(INITIAL_METHODS, 1)])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('ref_data_methods')
