"""enable row level security on all public tables

Revision ID: 4c9745be22b9
Revises: e1abcafd5901
Create Date: 2026-07-14 14:13:45.238637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c9745be22b9'
down_revision: Union[str, Sequence[str], None] = 'e1abcafd5901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = [
    "alembic_version", "app_settings", "audit_log", "contacts", "datasets",
    "info_types", "item_stages_old", "overdue_log", "project_items", "project_stages",
    "projects", "provision_request_history", "provision_requests", "ref_calendar_exceptions",
    "ref_file_formats", "ref_gkf_materials", "ref_gkf_types", "ref_interactions",
    "ref_micro_statuses", "ref_statuses", "ref_update_periods", "reg_request_users",
    "reg_requests", "report_metrics", "reports_monthly", "stage_documents", "stages",
    "suppliers", "survey_contacts", "survey_info_types", "survey_interactions",
    "survey_links", "surveys", "users",
]


def upgrade() -> None:
    """Upgrade schema."""
    # Включаем RLS без политик: закрывает доступ через Supabase PostgREST
    # (роли anon/authenticated), не затрагивает доступ через владельца таблиц
    # (роль postgres из DATABASE_URL имеет BYPASSRLS — проверено вручную перед миграцией).
    for t in TABLES:
        op.execute(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    """Downgrade schema."""
    for t in TABLES:
        op.execute(f'ALTER TABLE public."{t}" DISABLE ROW LEVEL SECURITY')
