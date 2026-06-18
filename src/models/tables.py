from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey, JSON, CheckConstraint, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from config.database import Base

class User(Base):
    __tablename__ = 'users'
    
    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)
    is_active = Column(Boolean, server_default=text("true"))
    created_at = Column(DateTime, server_default=text("now()"))
    last_login = Column(DateTime)
    display_name = Column(String(100))
    show_in_staff = Column(Boolean, server_default=text("false"))

    __table_args__ = (
        CheckConstraint("role::text = ANY (ARRAY['admin'::text, 'editor'::text, 'user'::text])", name='users_role_check'),
    )

class AuditLog(Base):
    __tablename__ = 'audit_log'
    
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id', ondelete='SET NULL'))
    action = Column(String(50), nullable=False)
    target_table = Column(String(100))
    target_id = Column(Integer)
    old_value = Column(JSONB)
    new_value = Column(JSONB)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime, server_default=text("now()"))

class Supplier(Base):
    __tablename__ = 'suppliers'
    
    supplier_id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_name = Column(String(255), nullable=False)
    supplier_address = Column(Text)
    supplier_email = Column(String(255))
    supplier_phone = Column(String(50))
    supplier_website = Column(String(255))
    supplier_manager = Column(String(255))
    supplier_notes = Column(Text)
    supplier_logo = Column(Text)
    is_mandatory = Column(Boolean, server_default=text("false"))

# Заглушки для связанных таблиц (чтобы код работал)
class Contact(Base):
    __tablename__ = 'contacts'
    contact_id = Column(Integer, primary_key=True)

class RefStatus(Base):
    __tablename__ = 'ref_statuses'
    status_id = Column(Integer, primary_key=True)

class Project(Base):
    __tablename__ = 'projects'
    
    project_id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.supplier_id', ondelete='RESTRICT'), nullable=False)
    project_name = Column(Text, nullable=False)
    main_contact_id = Column(Integer, ForeignKey('contacts.contact_id', ondelete='SET NULL'))
    status = Column(Integer, ForeignKey('ref_statuses.status_id', ondelete='RESTRICT'))
    notes = Column(Text)
    is_agreement_project = Column(Boolean, server_default=text("false"))

class Stage(Base):
    __tablename__ = 'stages'
    
    stage_id = Column(Integer, primary_key=True, autoincrement=True)
    stage_name = Column(Text, nullable=False)
    stage_order = Column(Integer, nullable=False)
    duration_days = Column(Integer)
    track_category = Column(String(50), nullable=False)
    stage_type = Column(String(20), nullable=False)
    stage_color = Column(String(20))

    __table_args__ = (
        CheckConstraint("stage_type::text = ANY (ARRAY['Веха'::text, 'Задача'::text])", name='stages_stage_type_check'),
    )

class RefMicroStatus(Base):
    __tablename__ = 'ref_micro_statuses'
    micro_status_id = Column(Integer, primary_key=True)

class ProjectStage(Base):
    __tablename__ = 'project_stages'
    
    stage_progress_id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.project_id', ondelete='CASCADE'), nullable=False)
    stage_id = Column(Integer, ForeignKey('stages.stage_id', ondelete='RESTRICT'), nullable=False)
    micro_status = Column(Integer, ForeignKey('ref_micro_statuses.micro_status_id', ondelete='RESTRICT'))
    iteration_count = Column(Integer, server_default=text("1"))
    planned_start = Column(Date)
    planned_end = Column(Date)
    actual_start = Column(Date)
    actual_end = Column(Date)
    comments = Column(Text)
    document_url = Column(Text)
    responsible_id = Column(Integer, ForeignKey('users.user_id'))

class AppSetting(Base):
    __tablename__ = 'app_settings'

    setting_key = Column(String(50), primary_key=True)
    setting_value = Column(JSONB, nullable=False)
    description = Column(Text)

class MonthlyReport(Base):
    __tablename__ = 'reports_monthly'
    
    report_id = Column(Integer, primary_key=True, autoincrement=True)
    report_month = Column(Date, nullable=False, unique=True)
    sections_data = Column(JSONB, nullable=False)
    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"), onupdate=text("now()"))
    created_by = Column(Integer, ForeignKey('users.user_id', ondelete='SET NULL'))

class RegistrationRequest(Base):
    __tablename__ = 'reg_requests'
    
    req_id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, server_default=text("now()"))
    processed_at = Column(DateTime)
    applicant_type = Column(String) 
    applicant_name = Column(Text, nullable=False)
    applicant_phone = Column(String(50)) # 👈 Новое поле
    scan_url = Column(Text)              # 👈 Новое поле
    org_type = Column(String)
    status = Column(String, server_default=text("'Новая'"))
    result_supplier_id = Column(Integer, ForeignKey('suppliers.supplier_id'))
    note = Column(Text)

class RequestUser(Base):
    __tablename__ = 'reg_request_users'
    
    user_row_id = Column(Integer, primary_key=True, autoincrement=True)
    req_id = Column(Integer, ForeignKey('reg_requests.req_id', ondelete='CASCADE'))
    full_name = Column(Text, nullable=False)
    email = Column(String(255)) # 👈 Новое поле
    login = Column(Text, nullable=False)
    is_admin = Column(Boolean, default=False)

