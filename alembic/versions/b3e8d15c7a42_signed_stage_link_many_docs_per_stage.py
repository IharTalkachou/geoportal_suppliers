"""move signing link from project_stages.document_id to project_documents.signed_stage_id

На одном этапе "Документ подписан" может быть подписано сразу несколько документов
(соглашение + протокол, либо несколько протоколов), поэтому связь один-к-одному
(project_stages.document_id) заменяется на один-ко-многим: каждый документ ссылается
на этап, которым он был подписан.

Revision ID: b3e8d15c7a42
Revises: a7c2f4e91b30
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e8d15c7a42'
down_revision: Union[str, Sequence[str], None] = 'a7c2f4e91b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('project_documents', sa.Column(
        'signed_stage_id', sa.Integer(), nullable=True,
        comment='Этап "Документ подписан", на котором подписан этот документ; на одном этапе их может быть несколько'))
    op.create_foreign_key('fk_project_documents_signed_stage', 'project_documents', 'project_stages',
                          ['signed_stage_id'], ['stage_progress_id'], ondelete='SET NULL')
    op.create_index('idx_pdocs_signed_stage', 'project_documents', ['signed_stage_id'], unique=False)

    # Переносим существующие связи в обратном направлении
    op.execute("""
        UPDATE project_documents pd
        SET signed_stage_id = ps.stage_progress_id
        FROM project_stages ps
        WHERE ps.document_id = pd.doc_id
    """)

    op.drop_index('idx_pstages_document', table_name='project_stages')
    op.drop_constraint('fk_project_stages_document', 'project_stages', type_='foreignkey')
    op.drop_column('project_stages', 'document_id')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('project_stages', sa.Column(
        'document_id', sa.Integer(), nullable=True,
        comment='Документ проекта (соглашение/протокол), к подписанию которого относится этап'))
    op.create_foreign_key('fk_project_stages_document', 'project_stages', 'project_documents',
                          ['document_id'], ['doc_id'], ondelete='SET NULL')
    op.create_index('idx_pstages_document', 'project_stages', ['document_id'], unique=False)

    # Обратный перенос: на этап попадёт только ОДИН документ (произвольный из набора) -
    # связь один-ко-многим в один-к-одному без потерь не сворачивается.
    op.execute("""
        UPDATE project_stages ps
        SET document_id = sub.doc_id
        FROM (
            SELECT DISTINCT ON (signed_stage_id) signed_stage_id, doc_id
            FROM project_documents
            WHERE signed_stage_id IS NOT NULL
            ORDER BY signed_stage_id, doc_id
        ) sub
        WHERE sub.signed_stage_id = ps.stage_progress_id
    """)

    op.drop_index('idx_pdocs_signed_stage', table_name='project_documents')
    op.drop_constraint('fk_project_documents_signed_stage', 'project_documents', type_='foreignkey')
    op.drop_column('project_documents', 'signed_stage_id')
