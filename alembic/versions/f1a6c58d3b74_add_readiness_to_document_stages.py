"""add is_ready and new_url to project_document_stages

Этап "Внесение изменений в протокол" получает per-документную готовность:
на одном этапе может быть несколько изменяемых протоколов, и каждый готовится
независимо. Пока протокол не готов - карточка показывает текст "изменяется"
без ссылки. Как только отмечена готовность и указана новая ссылка на скан,
она сразу переносится в project_documents.doc_url (документ считается
перезаключённым в новой редакции), а дата подписания обновляется.

Revision ID: f1a6c58d3b74
Revises: e7b2d40a91c3
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a6c58d3b74'
down_revision: Union[str, Sequence[str], None] = 'e7b2d40a91c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('project_document_stages', sa.Column(
        'is_ready', sa.Boolean(), server_default=sa.text('false'), nullable=True,
        comment='Готовность документа на этапе "Внесение изменений в протокол" - протокол перезаключён в новой редакции'))
    op.add_column('project_document_stages', sa.Column(
        'new_url', sa.Text(), nullable=True,
        comment='Ссылка на новую редакцию протокола (заполняется вместе с is_ready)'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('project_document_stages', 'new_url')
    op.drop_column('project_document_stages', 'is_ready')
