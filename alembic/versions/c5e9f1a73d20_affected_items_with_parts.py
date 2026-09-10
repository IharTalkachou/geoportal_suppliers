"""store affected items as {item_id, part_id} pairs

Технологический этап должен уметь нацеливаться на часть вида сведений: часть
равна протоколу, у неё свои сроки размещения, и опубликована она может быть
отдельно от остальных частей того же вида.

Формат project_stages.affected_item_ids меняется с массива чисел
    [18, 105]
на массив объектов
    [{"item_id": 18, "part_id": null}, {"item_id": 105, "part_id": 7}]

part_id = NULL означает "вид сведений целиком" (все его части) - именно так
трактуются все существующие записи после конвертации, поэтому смысл
исторических данных не меняется и проценты готовности не падают.

Revision ID: c5e9f1a73d20
Revises: b8d3e05a1c47
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e9f1a73d20'
down_revision: Union[str, Sequence[str], None] = 'b8d3e05a1c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Пустые массивы и NULL оставляем как есть; числовые элементы заворачиваем
    # в объекты с part_id = null. jsonb_typeof отсекает уже сконвертированные
    # строки, чтобы миграция была идемпотентной при повторном прогоне.
    op.execute("""
        UPDATE project_stages ps
        SET affected_item_ids = (
            SELECT COALESCE(jsonb_agg(jsonb_build_object('item_id', elem::int, 'part_id', NULL)), '[]'::jsonb)
            FROM jsonb_array_elements_text(ps.affected_item_ids) AS elem
        )
        WHERE ps.affected_item_ids IS NOT NULL
          AND jsonb_typeof(ps.affected_item_ids) = 'array'
          AND jsonb_array_length(ps.affected_item_ids) > 0
          AND jsonb_typeof(ps.affected_item_ids -> 0) = 'number'
    """)


def downgrade() -> None:
    """Downgrade schema.

    Обратная свёртка теряет привязку к частям: этап, нацеленный на конкретную
    часть, становится этапом на весь вид сведений. Дубли по item_id снимаются.
    """
    op.execute("""
        UPDATE project_stages ps
        SET affected_item_ids = (
            SELECT COALESCE(jsonb_agg(DISTINCT (elem ->> 'item_id')::int), '[]'::jsonb)
            FROM jsonb_array_elements(ps.affected_item_ids) AS elem
        )
        WHERE ps.affected_item_ids IS NOT NULL
          AND jsonb_typeof(ps.affected_item_ids) = 'array'
          AND jsonb_array_length(ps.affected_item_ids) > 0
          AND jsonb_typeof(ps.affected_item_ids -> 0) = 'object'
    """)
