"""use protocol-specific stages in non-agreement projects

Документарный трек различает два типа проектов: проект-соглашение (первичное
подключение поставщика) и проект-протокол (передача конкретных видов сведений).
Этапы у них разные по смыслу, хотя раньше использовались общие:

    DOCUMENT_APPROVAL ("Согласование документов") -> PROTOCOL_NEGOTIATIONS ("Согласование протокола")
    CONTRACT_SIGNED   ("Документ подписан")       -> PROTOCOL_SIGNED       ("Протокол подписан")

Здесь уже заведённые этапы проектов без соглашения переводятся на протокольные
коды, чтобы данные стали однородными: после этого расчёт прогресса опирается на
один набор кодов для каждого типа проекта, а не на оба сразу.

Проекты-соглашения не затрагиваются - у них DOCUMENT_APPROVAL и CONTRACT_SIGNED
остаются рабочими этапами.

Revision ID: d7b4e28c9f15
Revises: c5e9f1a73d20
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7b4e28c9f15'
down_revision: Union[str, Sequence[str], None] = 'c5e9f1a73d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Согласование документов -> Согласование протокола
    op.execute("""
        UPDATE project_stages ps
        SET stage_id = (SELECT stage_id FROM stages WHERE stage_code = 'PROTOCOL_NEGOTIATIONS')
        FROM projects p, stages src
        WHERE ps.project_id = p.project_id
          AND ps.stage_id = src.stage_id
          AND src.stage_code = 'DOCUMENT_APPROVAL'
          AND NOT p.is_agreement_project
    """)

    # Документ подписан -> Протокол подписан
    op.execute("""
        UPDATE project_stages ps
        SET stage_id = (SELECT stage_id FROM stages WHERE stage_code = 'PROTOCOL_SIGNED')
        FROM projects p, stages src
        WHERE ps.project_id = p.project_id
          AND ps.stage_id = src.stage_id
          AND src.stage_code = 'CONTRACT_SIGNED'
          AND NOT p.is_agreement_project
    """)


def downgrade() -> None:
    """Downgrade schema.

    Возврат к общим кодам возможен только для проектов без соглашения - именно
    они и переводились. Протокольные этапы проектов-соглашений (если такие
    появятся позже) не трогаются, иначе откат исказил бы их смысл.
    """
    op.execute("""
        UPDATE project_stages ps
        SET stage_id = (SELECT stage_id FROM stages WHERE stage_code = 'DOCUMENT_APPROVAL')
        FROM projects p, stages src
        WHERE ps.project_id = p.project_id
          AND ps.stage_id = src.stage_id
          AND src.stage_code = 'PROTOCOL_NEGOTIATIONS'
          AND NOT p.is_agreement_project
    """)
    op.execute("""
        UPDATE project_stages ps
        SET stage_id = (SELECT stage_id FROM stages WHERE stage_code = 'CONTRACT_SIGNED')
        FROM projects p, stages src
        WHERE ps.project_id = p.project_id
          AND ps.stage_id = src.stage_id
          AND src.stage_code = 'PROTOCOL_SIGNED'
          AND NOT p.is_agreement_project
    """)
