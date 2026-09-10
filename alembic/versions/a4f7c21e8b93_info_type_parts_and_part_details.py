"""move item parts to the global reference and add per-project part details

Часть вида сведений = единица, которой соответствует один протокол. Раньше части
жили на уровне состава проекта (project_item_parts), из-за чего один и тот же
разбитый вид сведений приходилось заводить заново у каждого поставщика.

Теперь состав частей - свойство справочника (info_type_parts): вид сведений задан
регламентом, значит и его дробление одинаково для всех. А то, КАК конкретный
поставщик передаёт конкретную часть (право, формат, срок обновления, способ и срок
размещения), уходит в project_item_part_details - там значения различаются от
протокола к протоколу.

Дополнительно project_items получает format/update_period: раньше они были только
глобальными в info_types и не могли отличаться у разных поставщиков.

Старая таблица project_item_parts НЕ удаляется этой миграцией - см. следующую
ревизию. Разделение даёт точку остановки: обе таблицы сосуществуют, данные можно
сверить, и только потом удалять. После DROP восстановить принадлежность части
к item_id уже невозможно.

Revision ID: a4f7c21e8b93
Revises: f1a6c58d3b74
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a4f7c21e8b93'
down_revision: Union[str, Sequence[str], None] = 'f1a6c58d3b74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'info_type_parts',
        sa.Column('part_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('info_id', sa.Integer(), nullable=False),
        sa.Column('part_name', sa.Text(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['info_id'], ['info_types.info_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('part_id'),
        sa.UniqueConstraint('info_id', 'part_name', name='unique_info_part_name'),
        comment='Части вида сведений: единица, передаваемая отдельным протоколом. Общая для всех поставщиков',
    )
    op.create_index('idx_info_parts_info', 'info_type_parts', ['info_id'], unique=False)

    op.create_table(
        'project_item_part_details',
        sa.Column('detail_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('part_id', sa.Integer(), nullable=False),
        sa.Column('provision_right',
                  postgresql.ENUM('Оператор и Поставщик', 'Только Поставщик', 'Не предоставляется',
                                  'Протокол не заключён', 'На безвозмездной основе', 'Только метаданные',
                                  name='data_provision_type', create_type=False),
                  nullable=True, comment='Право на предоставление в пользование для этой части'),
        sa.Column('format', sa.String(length=100), nullable=True,
                  comment='Формат предоставления; по умолчанию копируется из info_types.format'),
        sa.Column('update_period', sa.String(length=100), nullable=True,
                  comment='Срок обновления; по умолчанию копируется из info_types."update"'),
        sa.Column('meta_days', sa.Integer(), nullable=True),
        sa.Column('meta_method', sa.Text(), nullable=True),
        sa.Column('data_days', sa.Integer(), nullable=True),
        sa.Column('data_method', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['project_items.item_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['part_id'], ['info_type_parts.part_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('detail_id'),
        sa.UniqueConstraint('item_id', 'part_id', name='unique_item_part_detail'),
        comment='Как ЭТОТ поставщик передаёт ЭТУ часть вида сведений в рамках проекта',
    )
    op.create_index('idx_part_details_item', 'project_item_part_details', ['item_id'], unique=False)
    op.create_index('idx_part_details_part', 'project_item_part_details', ['part_id'], unique=False)

    op.add_column('project_items', sa.Column(
        'format', sa.String(length=100), nullable=True,
        comment='Переопределение info_types.format для этого поставщика; NULL - берётся из справочника'))
    op.add_column('project_items', sa.Column(
        'update_period', sa.String(length=100), nullable=True,
        comment='Переопределение info_types."update" для этого поставщика; NULL - берётся из справочника'))

    # --- ПЕРЕНОС СУЩЕСТВУЮЩИХ ДАННЫХ ---

    # 1. Части поднимаются с item_id на info_id. Одноимённые части одного вида
    # сведений из разных проектов схлопываются в одну глобальную (это и есть смысл
    # переноса). sort_order пересчитывается через row_number: у разных проектов
    # нумерация своя и при слиянии конфликтует (напр. вид 72 - части заведены
    # на item_id 68 и 144, обе с sort_order = 1).
    op.execute("""
        INSERT INTO info_type_parts (info_id, part_name, sort_order)
        SELECT info_id, part_name,
               row_number() OVER (PARTITION BY info_id ORDER BY min_order, min_part_id)
        FROM (
            SELECT pi.info_id,
                   pip.part_name,
                   MIN(COALESCE(pip.sort_order, 2147483647)) AS min_order,
                   MIN(pip.part_id) AS min_part_id
            FROM project_item_parts pip
            JOIN project_items pi ON pip.item_id = pi.item_id
            GROUP BY pi.info_id, pip.part_name
        ) grouped
    """)

    # 2. Детали передачи: значения project_items копируются в каждую часть.
    # С этого момента у разбитого вида сведений данные живут на частях
    # (решение "есть части - данные только на них"), а строки project_items
    # остаются как источник значений по умолчанию для новых частей.
    op.execute("""
        INSERT INTO project_item_part_details
            (item_id, part_id, provision_right, format, update_period,
             meta_days, meta_method, data_days, data_method)
        SELECT pip.item_id, itp.part_id, pi.provision_right,
               it.format, it."update",
               pi.meta_days, pi.meta_method, pi.data_days, pi.data_method
        FROM project_item_parts pip
        JOIN project_items pi ON pip.item_id = pi.item_id
        JOIN info_types it ON pi.info_id = it.info_id
        JOIN info_type_parts itp ON itp.info_id = pi.info_id AND itp.part_name = pip.part_name
        ON CONFLICT (item_id, part_id) DO NOTHING
    """)

    # 3. Перевешивание охвата документов на новые part_id.
    # Идентификаторы меняются, поэтому мало сменить FK - нужно перенумеровать
    # значения. Сопоставление идёт по (info_id, part_name) через старую таблицу.
    op.drop_constraint('project_document_items_part_id_fkey', 'project_document_items', type_='foreignkey')

    op.execute("""
        UPDATE project_document_items pdi
        SET part_id = m.new_part_id
        FROM (
            SELECT pip.part_id AS old_part_id, itp.part_id AS new_part_id
            FROM project_item_parts pip
            JOIN project_items pi ON pip.item_id = pi.item_id
            JOIN info_type_parts itp ON itp.info_id = pi.info_id AND itp.part_name = pip.part_name
        ) m
        WHERE pdi.part_id = m.old_part_id
    """)

    # Страховка: если что-то не сопоставилось, охват сбрасывается на "вид сведений
    # целиком" - это осмысленное состояние, в отличие от битой ссылки.
    op.execute("""
        UPDATE project_document_items pdi
        SET part_id = NULL
        WHERE pdi.part_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM info_type_parts itp WHERE itp.part_id = pdi.part_id)
    """)

    # Схлопывание частей могло породить дубли по (doc_id, item_id, part_id) -
    # снять их до восстановления уникального ограничения.
    op.execute("""
        DELETE FROM project_document_items a
        USING project_document_items b
        WHERE a.link_id > b.link_id
          AND a.doc_id = b.doc_id
          AND a.item_id = b.item_id
          AND a.part_id IS NOT DISTINCT FROM b.part_id
    """)

    op.create_foreign_key('project_document_items_part_id_fkey', 'project_document_items',
                          'info_type_parts', ['part_id'], ['part_id'], ondelete='CASCADE')


def downgrade() -> None:
    """Downgrade schema.

    ВНИМАНИЕ: обратный маппинг project_document_items.part_id восстановить нельзя.
    При переносе вперёд одноимённые части разных проектов схлопываются в одну
    глобальную, и информация о том, какому item_id принадлежала исходная часть,
    теряется. Здесь охват по частям сбрасывается в NULL ("вид сведений целиком"),
    что сохраняет ссылочную целостность, но не исходные данные.
    Перед downgrade на реальных данных - восстанавливаться из дампа.
    """
    op.drop_constraint('project_document_items_part_id_fkey', 'project_document_items', type_='foreignkey')
    op.execute("UPDATE project_document_items SET part_id = NULL WHERE part_id IS NOT NULL")
    op.create_foreign_key('project_document_items_part_id_fkey', 'project_document_items',
                          'project_item_parts', ['part_id'], ['part_id'], ondelete='CASCADE')

    op.drop_column('project_items', 'update_period')
    op.drop_column('project_items', 'format')

    op.drop_index('idx_part_details_part', table_name='project_item_part_details')
    op.drop_index('idx_part_details_item', table_name='project_item_part_details')
    op.drop_table('project_item_part_details')

    op.drop_index('idx_info_parts_info', table_name='info_type_parts')
    op.drop_table('info_type_parts')
