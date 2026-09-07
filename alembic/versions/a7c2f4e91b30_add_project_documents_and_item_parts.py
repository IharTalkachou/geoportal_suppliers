"""add project_documents, project_item_parts and document coverage

Гибкое завершение бюрократического трека: соглашение и протоколы проекта
становятся отдельными документами, подписываемыми независимо друг от друга.
Дополнительно вводится редкий подуровень "часть вида сведений" для случаев,
когда один вид сведений передаётся несколькими протоколами.

Revision ID: a7c2f4e91b30
Revises: 636d01f3cff0
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c2f4e91b30'
down_revision: Union[str, Sequence[str], None] = '636d01f3cff0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'project_documents',
        sa.Column('doc_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('doc_kind', sa.Text(), nullable=False, comment='Вид документа: Соглашение или Протокол'),
        sa.Column('doc_number', sa.Text(), nullable=True, comment='Номер или наименование документа'),
        sa.Column('doc_url', sa.Text(), nullable=True, comment='Ссылка на скан подписанного документа'),
        sa.Column('signed_date', sa.Date(), nullable=True, comment='Дата подписания; NULL пока документ не подписан'),
        sa.Column('is_signed', sa.Boolean(), server_default=sa.text('false'), nullable=True, comment='Признак подписанного документа'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("doc_kind = ANY (ARRAY['Соглашение'::text, 'Протокол'::text])",
                           name='project_documents_kind_check'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.project_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('doc_id'),
        comment='Документы проекта: соглашение и протоколы, подписываемые независимо друг от друга',
    )
    op.create_index('idx_pdocs_project', 'project_documents', ['project_id'], unique=False)
    # В проекте допустимо не более одного соглашения; протоколов - сколько угодно
    op.create_index('idx_pdocs_one_agreement', 'project_documents', ['project_id'], unique=True,
                    postgresql_where=sa.text("doc_kind = 'Соглашение'"))

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

    op.create_table(
        'project_document_items',
        sa.Column('link_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('doc_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('part_id', sa.Integer(), nullable=True, comment='NULL - документ покрывает вид сведений целиком'),
        sa.ForeignKeyConstraint(['doc_id'], ['project_documents.doc_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['project_items.item_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['part_id'], ['project_item_parts.part_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('link_id'),
        sa.UniqueConstraint('doc_id', 'item_id', 'part_id', name='unique_document_item_part'),
        comment='Связь документа проекта с видами сведений (или их частями), которые он покрывает',
    )
    op.create_index('idx_pdoc_items_doc', 'project_document_items', ['doc_id'], unique=False)
    op.create_index('idx_pdoc_items_item', 'project_document_items', ['item_id'], unique=False)

    op.add_column('project_stages', sa.Column(
        'document_id', sa.Integer(), nullable=True,
        comment='Документ проекта (соглашение/протокол), к подписанию которого относится этап'))
    op.create_foreign_key('fk_project_stages_document', 'project_stages', 'project_documents',
                          ['document_id'], ['doc_id'], ondelete='SET NULL')
    op.create_index('idx_pstages_document', 'project_stages', ['document_id'], unique=False)

    # --- ПЕРЕНОС СУЩЕСТВУЮЩИХ ДАННЫХ ---
    # Для каждого проекта с выполненным этапом CONTRACT_SIGNED создаём один документ.
    # Вид определяется прежним флагом projects.is_agreement_project - той самой
    # логикой, которая до сих пор различала "Соглашение подписано" и "Протокол подписан".
    # Берём самый поздний выполненный этап на проект (DISTINCT ON), чтобы на проект
    # пришёлся ровно один документ и не нарушился частичный уникальный индекс.
    # Охват намеренно не заполняем: пустой охват = весь проект.
    op.execute("""
        INSERT INTO project_documents (project_id, doc_kind, signed_date, is_signed, sort_order)
        SELECT DISTINCT ON (ps.project_id)
               ps.project_id,
               CASE WHEN p.is_agreement_project THEN 'Соглашение' ELSE 'Протокол' END,
               ps.actual_end,
               true,
               1
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        WHERE stg.stage_code = 'CONTRACT_SIGNED'
          AND ps.micro_status = 4
        ORDER BY ps.project_id, ps.actual_end DESC NULLS LAST, ps.stage_progress_id DESC
    """)

    # Привязываем все этапы CONTRACT_SIGNED проекта к созданному документу
    op.execute("""
        UPDATE project_stages ps
        SET document_id = pd.doc_id
        FROM stages stg, project_documents pd
        WHERE ps.stage_id = stg.stage_id
          AND stg.stage_code = 'CONTRACT_SIGNED'
          AND pd.project_id = ps.project_id
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_pstages_document', table_name='project_stages')
    op.drop_constraint('fk_project_stages_document', 'project_stages', type_='foreignkey')
    op.drop_column('project_stages', 'document_id')

    op.drop_index('idx_pdoc_items_item', table_name='project_document_items')
    op.drop_index('idx_pdoc_items_doc', table_name='project_document_items')
    op.drop_table('project_document_items')

    op.drop_index('idx_item_parts_item', table_name='project_item_parts')
    op.drop_table('project_item_parts')

    op.drop_index('idx_pdocs_one_agreement', table_name='project_documents')
    op.drop_index('idx_pdocs_project', table_name='project_documents')
    op.drop_table('project_documents')
