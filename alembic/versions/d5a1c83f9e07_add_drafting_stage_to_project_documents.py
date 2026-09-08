"""add drafting_stage_id to project_documents

Этап "Согласование протокола" (PROTOCOL_NEGOTIATIONS) отражает работу над
документом ДО его подписания: соглашение может быть подписано, пока протоколы
ещё согласовываются. Документ ссылается на такой этап отдельной колонкой -
signed_stage_id означает "подписан на этом этапе" и для незакрытой работы
не подходит.

Revision ID: d5a1c83f9e07
Revises: c9f4a2071e58
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5a1c83f9e07'
down_revision: Union[str, Sequence[str], None] = 'c9f4a2071e58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('project_documents', sa.Column(
        'drafting_stage_id', sa.Integer(), nullable=True,
        comment='Этап "Согласование протокола", в рамках которого ведётся работа над этим документом до его подписания'))
    op.create_foreign_key('fk_project_documents_drafting_stage', 'project_documents', 'project_stages',
                          ['drafting_stage_id'], ['stage_progress_id'], ondelete='SET NULL')
    op.create_index('idx_pdocs_drafting_stage', 'project_documents', ['drafting_stage_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_pdocs_drafting_stage', table_name='project_documents')
    op.drop_constraint('fk_project_documents_drafting_stage', 'project_documents', type_='foreignkey')
    op.drop_column('project_documents', 'drafting_stage_id')
