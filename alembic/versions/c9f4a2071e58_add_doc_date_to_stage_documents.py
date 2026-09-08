"""add doc_date to stage_documents and make doc_url nullable

Протокол переговоров прикрепляется к этапу "Переговоры" как документ этапа
(stage_documents), а не как документ проекта (project_documents): это другая
сущность - он не покрывает виды сведений и не участвует в расчёте прогресса.
Для него нужна дата документа; ссылку на скан допускается заполнить позже.

Revision ID: c9f4a2071e58
Revises: b3e8d15c7a42
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9f4a2071e58'
down_revision: Union[str, Sequence[str], None] = 'b3e8d15c7a42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('stage_documents', sa.Column(
        'doc_date', sa.Date(), nullable=True,
        comment='Дата документа - напр. дата протокола переговоров, приложенного к этапу'))
    op.add_column('stage_documents', sa.Column(
        'is_nego_protocol', sa.Boolean(), server_default=sa.text('false'), nullable=True,
        comment='Признак протокола переговоров (веха этапа "Переговоры"), а не обычного вложения'))
    # Документ можно завести до появления скана
    op.alter_column('stage_documents', 'doc_url', existing_type=sa.Text(), nullable=True)

    # --- ПЕРЕНОС ЭТАПОВ "Протокол переговоров" (PROTOCOL_NEGOTIATIONS) ---
    # Этап дублировал сущность: он фиксировал веху-протокол переговоров, что теперь
    # делается признаком у этапа "Переговоры". Существующие записи не удаляем вслепую -
    # переносим их вместе со сканами в этап NEGOTIATIONS того же проекта.

    # 1. Сканы, висящие на этапах PROTOCOL_NEGOTIATIONS, помечаем протоколами
    #    переговоров и проставляем дату из самого этапа
    op.execute("""
        UPDATE stage_documents sd
        SET is_nego_protocol = TRUE,
            doc_date = COALESCE(sd.doc_date, ps.actual_end, ps.actual_start, ps.planned_start)
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        WHERE sd.project_stage_id = ps.stage_progress_id
          AND s.stage_code = 'PROTOCOL_NEGOTIATIONS'
    """)

    # 2. Переносим их на этап "Переговоры" того же проекта (последняя итерация).
    #    Если NEGOTIATIONS в проекте нет, документ остаётся на своём этапе -
    #    данные не теряются, запись PROTOCOL_NEGOTIATIONS тоже сохраняется (см. п.3).
    op.execute("""
        UPDATE stage_documents sd
        SET project_stage_id = tgt.stage_progress_id
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        JOIN LATERAL (
            SELECT ps2.stage_progress_id
            FROM project_stages ps2
            JOIN stages s2 ON ps2.stage_id = s2.stage_id
            WHERE ps2.project_id = ps.project_id AND s2.stage_code = 'NEGOTIATIONS'
            ORDER BY ps2.iteration_count DESC, ps2.stage_progress_id DESC
            LIMIT 1
        ) tgt ON TRUE
        WHERE sd.project_stage_id = ps.stage_progress_id
          AND s.stage_code = 'PROTOCOL_NEGOTIATIONS'
    """)

    # 3. Удаляем только те записи этапа, с которых всё унесено (не осталось вложений).
    #    Этапы, чьи сканы перенести было некуда, остаются - разбираются вручную.
    op.execute("""
        DELETE FROM project_stages ps
        USING stages s
        WHERE ps.stage_id = s.stage_id
          AND s.stage_code = 'PROTOCOL_NEGOTIATIONS'
          AND NOT EXISTS (SELECT 1 FROM stage_documents sd
                           WHERE sd.project_stage_id = ps.stage_progress_id)
    """)

    # 4. Сам этап в справочнике переименовываем: он больше не про протокол
    #    переговоров, а про согласование протокола передачи данных
    op.execute("""
        UPDATE stages
        SET stage_name = 'Согласование протокола'
        WHERE stage_code = 'PROTOCOL_NEGOTIATIONS'
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        UPDATE stages
        SET stage_name = 'Протокол переговоров'
        WHERE stage_code = 'PROTOCOL_NEGOTIATIONS'
    """)
    # Перенос документов и удалённые записи этапов обратно не восстанавливаются
    op.drop_column('stage_documents', 'is_nego_protocol')
    # Вернуть NOT NULL можно только если пустых ссылок не осталось
    op.execute("UPDATE stage_documents SET doc_url = '' WHERE doc_url IS NULL")
    op.alter_column('stage_documents', 'doc_url', existing_type=sa.Text(), nullable=False)
    op.drop_column('stage_documents', 'doc_date')
