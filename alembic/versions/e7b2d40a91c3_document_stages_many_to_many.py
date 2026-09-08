"""replace project_documents.drafting_stage_id with project_document_stages

Работа над документом (согласование протокола, внесение изменений) итеративна:
у этапа несколько итераций, каждая - отдельная строка project_stages. Колонка
drafting_stage_id допускала только одну связь, поэтому указание документа в
новой итерации стирало его из предыдущих. Заменяем связью многие-ко-многим.

Revision ID: e7b2d40a91c3
Revises: d5a1c83f9e07
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b2d40a91c3'
down_revision: Union[str, Sequence[str], None] = 'd5a1c83f9e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'project_document_stages',
        sa.Column('link_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('doc_id', sa.Integer(), nullable=False),
        sa.Column('stage_progress_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['doc_id'], ['project_documents.doc_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['stage_progress_id'], ['project_stages.stage_progress_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('link_id'),
        sa.UniqueConstraint('doc_id', 'stage_progress_id', name='unique_document_stage'),
        comment='Этапы работы над документом проекта (согласование, внесение изменений)',
    )
    op.create_index('idx_pdoc_stages_doc', 'project_document_stages', ['doc_id'], unique=False)
    op.create_index('idx_pdoc_stages_stage', 'project_document_stages', ['stage_progress_id'], unique=False)

    # Переносим уже проставленные связи, чтобы введённые данные не потерялись
    op.execute("""
        INSERT INTO project_document_stages (doc_id, stage_progress_id)
        SELECT doc_id, drafting_stage_id
        FROM project_documents
        WHERE drafting_stage_id IS NOT NULL
        ON CONFLICT (doc_id, stage_progress_id) DO NOTHING
    """)

    op.drop_index('idx_pdocs_drafting_stage', table_name='project_documents')
    op.drop_constraint('fk_project_documents_drafting_stage', 'project_documents', type_='foreignkey')
    op.drop_column('project_documents', 'drafting_stage_id')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('project_documents', sa.Column(
        'drafting_stage_id', sa.Integer(), nullable=True,
        comment='Этап "Согласование протокола", в рамках которого ведётся работа над этим документом до его подписания'))
    op.create_foreign_key('fk_project_documents_drafting_stage', 'project_documents', 'project_stages',
                          ['drafting_stage_id'], ['stage_progress_id'], ondelete='SET NULL')
    op.create_index('idx_pdocs_drafting_stage', 'project_documents', ['drafting_stage_id'], unique=False)

    # Обратно помещается только ОДНА связь на документ - многие-ко-многим
    # в один-к-одному без потерь не сворачивается
    op.execute("""
        UPDATE project_documents pd
        SET drafting_stage_id = sub.stage_progress_id
        FROM (
            SELECT DISTINCT ON (doc_id) doc_id, stage_progress_id
            FROM project_document_stages
            ORDER BY doc_id, stage_progress_id DESC
        ) sub
        WHERE sub.doc_id = pd.doc_id
    """)

    op.drop_index('idx_pdoc_stages_stage', table_name='project_document_stages')
    op.drop_index('idx_pdoc_stages_doc', table_name='project_document_stages')
    op.drop_table('project_document_stages')
