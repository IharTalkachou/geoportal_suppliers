"""backfill DATA_TRANSFER stage from completed DATA_WAIT

Этап "Передача данных Оператору" (DATA_TRANSFER) - входной этап работы с данными,
предшествует "Размещению наборов" (DATA_WAIT). Он заведён позже, чем накопились
данные, поэтому у уже выполненных проектов его нет, и признак "Данные переданы"
в паспорте проекта (считается ПО ОХВАТУ, см. render_passport_subtab) у них не
загорелся бы, хотя данные фактически переданы - иначе размещение не состоялось бы.

Здесь для каждой выполненной итерации DATA_WAIT создаётся парная выполненная
итерация DATA_TRANSFER:

    planned_start = planned_end = actual_start = actual_end источника
    (по договорённости: плановые даты = фактической дате начала/выполнения DATA_WAIT)

    affected_item_ids копируется как есть - без него этап не попадёт в проверку
    охвата, ради которой всё и делается.

    iteration_count, responsible_id, comments переносятся из источника.

Идемпотентность: вставка пропускает проекты, где DATA_TRANSFER уже есть, поэтому
повторный прогон ничего не задваивает. Для строгости совпадение ищется по паре
(project_id, iteration_count) - если в проекте несколько итераций размещения,
каждой достанется своя передача.

Revision ID: f4c7a91e26b8
Revises: d7b4e28c9f15
Create Date: 2026-09-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4c7a91e26b8'
down_revision: Union[str, Sequence[str], None] = 'd7b4e28c9f15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Страховка: без этапа в справочнике вставлять нечего. Падаем явным сообщением,
    # а не тихо пропускаем - иначе миграция "прошла", а данных нет.
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT 1 FROM stages WHERE stage_code = 'DATA_TRANSFER'"
    )).scalar()
    if not exists:
        raise RuntimeError(
            "В справочнике stages нет этапа с stage_code = 'DATA_TRANSFER'. "
            "Заведите его (track_category = '2. Технологический', stage_order "
            "перед 'Размещение наборов') и повторите миграцию."
        )

    op.execute("""
        INSERT INTO project_stages (
            project_id, stage_id, micro_status, iteration_count,
            planned_start, planned_end, actual_start, actual_end,
            comments, responsible_id, affected_item_ids
        )
        SELECT
            src.project_id,
            (SELECT stage_id FROM stages WHERE stage_code = 'DATA_TRANSFER'),
            4,                                  -- Выполнено
            src.iteration_count,
            src.actual_start,                   -- плановое начало = фактическое начало
            src.actual_end,                     -- плановое завершение = фактическое
            src.actual_start,
            src.actual_end,
            src.comments,
            src.responsible_id,
            src.affected_item_ids               -- охват обязателен для признака "Данные переданы"
        FROM project_stages src
        JOIN stages s ON src.stage_id = s.stage_id
        WHERE s.stage_code = 'DATA_WAIT'
          AND src.micro_status = 4
          AND NOT EXISTS (
              SELECT 1
              FROM project_stages dup
              JOIN stages ds ON dup.stage_id = ds.stage_id
              WHERE ds.stage_code = 'DATA_TRANSFER'
                AND dup.project_id = src.project_id
                AND dup.iteration_count = src.iteration_count
          )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Удаляются только строки, неотличимые от созданных здесь: выполненный
    # DATA_TRANSFER, у которого даты совпадают с выполненным DATA_WAIT того же
    # проекта и той же итерации. Этап, заведённый вручную после миграции, обычно
    # имеет другие даты и переживёт откат - осознанный компромисс: потерять
    # реальные данные хуже, чем оставить лишнюю строку.
    op.execute("""
        DELETE FROM project_stages tgt
        USING stages ts
        WHERE tgt.stage_id = ts.stage_id
          AND ts.stage_code = 'DATA_TRANSFER'
          AND tgt.micro_status = 4
          AND EXISTS (
              SELECT 1
              FROM project_stages src
              JOIN stages s ON src.stage_id = s.stage_id
              WHERE s.stage_code = 'DATA_WAIT'
                AND src.micro_status = 4
                AND src.project_id = tgt.project_id
                AND src.iteration_count = tgt.iteration_count
                AND src.actual_start IS NOT DISTINCT FROM tgt.actual_start
                AND src.actual_end IS NOT DISTINCT FROM tgt.actual_end
          )
    """)
