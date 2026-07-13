from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, Numeric, ForeignKey, JSON, CheckConstraint, UniqueConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, ENUM
from sqlalchemy.orm import relationship
from config.database import Base

# ENUM-типы, уже существующие в БД (создаются вручную SQL, не Alembic'ом)
ApplicantCategory = ENUM('Физическое лицо', 'Юридическое лицо', name='applicant_category', create_type=False)
OrgTargetType = ENUM('Пользователь', 'Поставщик', name='org_target_type', create_type=False)
RequestStatus = ENUM('Новая', 'В обработке', 'Завершена', 'Отклонена', name='request_status', create_type=False)
DataProvisionType = ENUM(
    'Оператор и Поставщик', 'Только Поставщик', 'Не предоставляется',
    'Протокол не заключён', 'На безвозмездной основе', 'Только метаданные',
    name='data_provision_type', create_type=False
)
Restrictions = ENUM('Открытые данные', 'Для служебного использования', 'Коммерческая информация', 'Иное', name='restrictions', create_type=False)
Definitions = ENUM('Автоматический', 'Полуавтоматический', 'Ручной', 'Иное', name='definitions', create_type=False)

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
    show_in_staff = Column(Boolean, server_default=text("false"), comment='Признак отображения пользователя в списке для назначения ответственным по проектам')

    __table_args__ = (
        CheckConstraint("role::text = ANY (ARRAY['admin'::text, 'editor'::text, 'user'::text])", name='users_role_check'),
        Index('idx_users_username', 'username'),
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

    __table_args__ = (
        Index('idx_audit_log_action', 'action'),
        Index('idx_audit_log_user_time', 'user_id', text('created_at DESC')),
    )

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
    is_mandatory = Column(Boolean, server_default=text("false"), comment='Флаг поставщика обязательного набора пространственных данных')
    is_gov_agency = Column(Boolean, server_default=text("false"))

class Contact(Base):
    __tablename__ = 'contacts'

    contact_id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.supplier_id', ondelete='RESTRICT'))
    full_name = Column(String(255), nullable=False)
    position = Column('position', String(255))
    email = Column(String(255))
    phone = Column(String(50))
    notes = Column(Text)

    __table_args__ = (
        Index('idx_contacts_supplier', 'supplier_id'),
    )

class RefStatus(Base):
    __tablename__ = 'ref_statuses'

    status_id = Column(Integer, primary_key=True, autoincrement=True)
    status_code = Column(String(50))
    status_name = Column(Text, nullable=False)
    sort_order = Column(Integer)

class Project(Base):
    __tablename__ = 'projects'
    
    project_id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.supplier_id', ondelete='RESTRICT'), nullable=False)
    project_name = Column(Text, nullable=False)
    main_contact_id = Column(Integer, ForeignKey('contacts.contact_id', ondelete='SET NULL'))
    status = Column(Integer, ForeignKey('ref_statuses.status_id', ondelete='RESTRICT'))
    notes = Column(Text)
    is_agreement_project = Column(Boolean, server_default=text("false"), comment='Признак проекта, включающего заключение соглашения с поставщиком (первичное подключение)')

    __table_args__ = (
        Index('idx_projects_status', 'status'),
        Index('idx_projects_supplier', 'supplier_id'),
    )

class Stage(Base):
    __tablename__ = 'stages'

    stage_id = Column(Integer, primary_key=True, autoincrement=True)
    stage_name = Column(Text, nullable=False)
    stage_order = Column(Integer, nullable=False)
    duration_days = Column(Integer)
    track_category = Column(String(50), nullable=False)
    stage_type = Column(String(20), nullable=False)
    stage_color = Column(String(20))
    stage_code = Column(String(50))

    __table_args__ = (
        CheckConstraint("stage_type::text = ANY (ARRAY['Веха'::text, 'Задача'::text])", name='stages_stage_type_check'),
        Index('idx_stages_cat_type_order', 'track_category', 'stage_type', 'stage_order'),
        Index('idx_stages_unique_code', 'stage_code', unique=True, postgresql_where=text('stage_code IS NOT NULL')),
    )

class RefMicroStatus(Base):
    __tablename__ = 'ref_micro_statuses'

    micro_status_id = Column(Integer, primary_key=True, autoincrement=True)
    micro_status_code = Column(String(50))
    micro_status_name = Column(Text, nullable=False)
    sort_order = Column(Integer)

class Dataset(Base):
    __tablename__ = 'datasets'

    dataset_id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_name = Column(Text, nullable=False)
    is_mandatory = Column(Boolean, server_default=text("false"))
    is_basic = Column(Boolean, server_default=text("false"))
    dataset_icon = Column(Text)

class InfoType(Base):
    __tablename__ = 'info_types'

    info_id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(Integer, ForeignKey('datasets.dataset_id', ondelete='RESTRICT'))
    info_name = Column(Text, nullable=False)
    type = Column(String(100))
    format = Column(String(100))
    update = Column(String(100))
    update_period = Column(String(100))

    __table_args__ = (
        Index('idx_info_types_dataset', 'dataset_id'),
    )

class ProjectItem(Base):
    __tablename__ = 'project_items'

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.project_id', ondelete='CASCADE'), nullable=False)
    dataset_id = Column(Integer, ForeignKey('datasets.dataset_id', ondelete='RESTRICT'), nullable=False)
    info_id = Column(Integer, ForeignKey('info_types.info_id', ondelete='RESTRICT'), nullable=False)
    tech_contact_id = Column(Integer, ForeignKey('contacts.contact_id', ondelete='SET NULL'))
    provision_right = Column(DataProvisionType, server_default=text("'Не предоставляется'::data_provision_type"), comment='Право на предоставление в пользование')
    meta_days = Column(Integer, server_default=text("10"))
    data_days = Column(Integer, server_default=text("10"))
    meta_method = Column(Text, server_default=text("'Электронный кабинет'::text"))
    data_method = Column(Text, server_default=text("'Сервис (WMS/WFS)'::text"))

    __table_args__ = (
        Index('idx_items_dataset', 'dataset_id'),
        Index('idx_items_info', 'info_id'),
        Index('idx_items_project', 'project_id'),
    )

class ItemStageOld(Base):
    __tablename__ = 'item_stages_old'

    stage_progress_id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey('project_items.item_id', ondelete='CASCADE'), nullable=False)
    stage_id = Column(Integer, ForeignKey('stages.stage_id', ondelete='RESTRICT'), nullable=False)
    micro_status = Column(Integer, ForeignKey('ref_micro_statuses.micro_status_id', ondelete='RESTRICT'))
    iteration_count = Column(Integer, server_default=text("1"))
    planned_start = Column(Date)
    planned_end = Column(Date)
    actual_start = Column(Date)
    actual_end = Column(Date)
    comments = Column(Text)
    document_url = Column(Text)
    responsible_id = Column(Integer, ForeignKey('users.user_id'), comment='Ответственный сотрудник за техническую интеграцию конкретного вида сведений')

    __table_args__ = (
        Index('idx_istages_item', 'item_id'),
        Index('idx_istages_stage', 'stage_id'),
    )

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
    responsible_id = Column(Integer, ForeignKey('users.user_id'), comment='Ответственный сотрудник за конкретный документарный этап')
    affected_item_ids = Column(JSONB, server_default=text("'[]'::jsonb"))

    __table_args__ = (
        Index('idx_pstages_project', 'project_id'),
        Index('idx_pstages_stage', 'stage_id'),
    )

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
    fixed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index('idx_reports_month', 'report_month'),
    )

class RegistrationRequest(Base):
    __tablename__ = 'reg_requests'

    req_id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    processed_at = Column(DateTime(timezone=True))
    applicant_type = Column(ApplicantCategory, nullable=False)
    applicant_name = Column(Text, nullable=False)
    applicant_phone = Column(String(50))
    scan_url = Column(Text)
    org_type = Column(OrgTargetType)
    status = Column(RequestStatus, server_default=text("'Новая'::request_status"))
    result_supplier_id = Column(Integer, ForeignKey('suppliers.supplier_id', ondelete='SET NULL'))
    note = Column(Text)

class RequestUser(Base):
    __tablename__ = 'reg_request_users'

    user_row_id = Column(Integer, primary_key=True, autoincrement=True)
    req_id = Column(Integer, ForeignKey('reg_requests.req_id', ondelete='CASCADE'))
    full_name = Column(Text, nullable=False)
    email = Column(String(255))
    login = Column(Text, nullable=False)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, server_default=text("true"))
    last_activity_at = Column(DateTime(timezone=True))

class GkfType(Base):
    __tablename__ = 'ref_gkf_types'
    type_id = Column(Integer, primary_key=True, autoincrement=True)
    type_name = Column(Text, nullable=False)

class GkfMaterial(Base):
    __tablename__ = 'ref_gkf_materials'
    material_id = Column(Integer, primary_key=True, autoincrement=True)
    type_id = Column(Integer, ForeignKey('ref_gkf_types.type_id', ondelete='CASCADE'))
    material_name = Column(Text, nullable=False)

class ProvisionRequest(Base):
    __tablename__ = 'provision_requests'
    req_id = Column(Integer, primary_key=True, autoincrement=True)
    reg_number = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    applicant_category = Column(Text, nullable=False)
    applicant_name = Column(Text, nullable=False)
    contact_person = Column(Text)
    phone = Column(String(50))
    email = Column(String(255))
    channel = Column(Text)
    preferred_contact_method = Column(Text)
    request_type = Column(Text, nullable=False)
    scan_url = Column(Text)
    nipd_info_id = Column(Integer, ForeignKey('info_types.info_id'))
    gkf_material_ids = Column(ARRAY(Integer))
    status_id = Column(Integer, ForeignKey('stages.stage_id'), server_default=text("1"))
    note = Column(Text)
    area_coords_raw = Column(Text)
    provision_term = Column(Text)

class ProvisionHistory(Base):
    __tablename__ = 'provision_request_history'
    history_id = Column(Integer, primary_key=True, autoincrement=True)
    req_id = Column(Integer, ForeignKey('provision_requests.req_id', ondelete='CASCADE'))
    stage_id = Column(Integer, ForeignKey('stages.stage_id'))
    planned_start = Column(Date)
    planned_end = Column(Date)
    actual_start = Column(DateTime(timezone=True))
    actual_end = Column(DateTime(timezone=True))
    responsible_id = Column(Integer, ForeignKey('users.user_id'))
    comments = Column(Text)

class CalendarException(Base):
    __tablename__ = 'ref_calendar_exceptions'
    exception_date = Column(Date, primary_key=True)
    is_workday = Column(Boolean, default=False)
    description = Column(Text)

class RefFileFormat(Base):
    __tablename__ = 'ref_file_formats'

    format_id = Column(Integer, primary_key=True, autoincrement=True)
    format_name = Column(String(50), unique=True)

class RefUpdatePeriod(Base):
    __tablename__ = 'ref_update_periods'

    period_id = Column(Integer, primary_key=True, autoincrement=True)
    period_name = Column(String(50), unique=True)

class RefInteraction(Base):
    __tablename__ = 'ref_interactions'

    interaction_id = Column(Integer, primary_key=True, autoincrement=True)
    interaction_option_id = Column(Integer, nullable=False)
    interaction_text = Column(Text, nullable=False)

class ReportMetric(Base):
    __tablename__ = 'report_metrics'

    metric_id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey('reports_monthly.report_id', ondelete='CASCADE'))
    metric_key = Column(Text, nullable=False)
    metric_value = Column(Numeric)
    metric_text = Column(Text)

    __table_args__ = (
        UniqueConstraint('report_id', 'metric_key', name='unique_report_metric'),
    )

class StageDocument(Base):
    __tablename__ = 'stage_documents'

    doc_id = Column(Integer, primary_key=True, autoincrement=True)
    project_stage_id = Column(Integer, ForeignKey('project_stages.stage_progress_id', ondelete='CASCADE'))
    item_stage_id = Column(Integer, ForeignKey('item_stages_old.stage_progress_id', ondelete='CASCADE'))
    doc_name = Column(Text, nullable=False)
    doc_url = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=text("now()"))
    provision_history_id = Column(Integer, ForeignKey('provision_request_history.history_id', ondelete='CASCADE'))

class OverdueLog(Base):
    __tablename__ = 'overdue_log'

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    source_table = Column(String(50), nullable=False)
    stage_progress_id = Column(Integer, nullable=False)
    supplier_name = Column(Text)
    project_name = Column(Text)
    info_name = Column(Text)
    stage_name = Column(Text)
    responsible_name = Column(Text)
    planned_start = Column(Date)
    planned_end = Column(Date)
    actual_start = Column(Date)
    comments = Column(Text)
    detected_at = Column(DateTime, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint('source_table', 'stage_progress_id', name='unique_overdue_entry'),
        {'comment': 'История зафиксированных просрочек по всем этапам'},
    )

class Survey(Base):
    __tablename__ = 'surveys'
    __table_args__ = {'comment': 'Результаты первичной технической проработки поставщиков ОНПД'}

    survey_id = Column(Integer, primary_key=True, autoincrement=True, comment='Идентификатор опросника')
    received_date = Column(Date, nullable=False, comment='Дата получения заполненного опросника')
    supplier_id = Column(Integer, ForeignKey('suppliers.supplier_id', ondelete='CASCADE'), nullable=False, comment='Идентификатор поставщика')
    it_description = Column(Text, nullable=False, comment='Описание набора ПД')
    it_purpose = Column(Text, nullable=False, comment='Назначение набора ПД (предполагаемая целевая аудитория при размещении на НГ)')
    it_legal_status = Column(Text, nullable=False, comment='Правовой статус набора ПД (основание для формирования и ведения набора ПД)')
    it_statute = Column(Text, nullable=False, comment='Нормативные правовые акты и технические нормативные правовые акты, регламентирующие формирование и обновление набора ПД (при их наличии)')
    it_regulations = Column(ARRAY(Restrictions), nullable=False, comment='Ограничительный гриф набора ПД (при его наличии)')
    it_other_regulations = Column(Text, nullable=False, comment='Наличие иных ограничений, препятствующих предоставлению в пользование и использование набора ПД')
    it_format = Column(Text, nullable=False, comment='Форма ведения (хранения) набора ПД (цифровая, иная)')
    it_type = Column(Text, nullable=False, comment='Вид цифрового набора ПД (растровые данные, векторные данные, табличные данные, текст и т.д.)')
    it_digital_format = Column(Text, nullable=False, comment='Формат хранения цифрового набора ПД. Справочно: в векторном представлении - shp, dwg и другие; в растровой форме - tiff, jpeg, png и другие; в текстовой форме - docs, txt, xls и другие; база данных - mdb и другие')
    it_digital_transform = Column(Boolean, server_default=text("false"), comment='Потребность перевода набора ПД в цифровую форму, текстовых или табличных данных в базу данных')
    it_metadata_base = Column(Text, nullable=False, comment='Наличие и виды информационных каталогов, баз данных, журналов учёта из которых возможно формировать метаданные')
    it_coordinate_system = Column(Text, nullable=False, comment='Системы отсчёта координат и высот набора ПД. Справочно: система отсчёта координат 1995 года; система отсчёта координат 1942 года, World Geodetic System (WGS-84); местные системы отсчёта координат; Балтийская система высот 1977 года; другие системы отсчёта')
    it_spatial_extent = Column(Text, nullable=False, comment='Территория, в отношении которой создан набор ПД (административно-территориальная единица; территориальная единица)')
    it_actual_date = Column(Text, nullable=False, comment='Год состояния местности (актуальность) набора ПД')
    it_update = Column(Text, nullable=False, comment='Периодичность (частота) обновления набора ПД, регламентирующие документы')
    it_spatial_scale = Column(Text, nullable=False, comment='Пространственное разрешение или масштаб данных. Справочно: для данных дистанционного зондирования Земли указывается пространственное разрешение; для картографических материалов - масштаб')
    it_classification = Column(Text, nullable=False, comment='Наличие специализированного классификатора объектов набора ПД (утвержденного в Республике Беларусь или международного классификатора)')
    it_conventional_signs = Column(Text, nullable=False, comment='Наличие каталога специальных графических отображений объектов набора ПД (специальные условные знаки)')
    it_coordinate_determining = Column(ARRAY(Definitions), nullable=False, comment='Точность и способ определения координат объектов набора ПД. Справочно: способы определения координат - автоматический, полуавтоматический, ручной')
    it_coordinate_determining_text = Column(Text, comment='Точность и способ определения координат объектов набора ПД. Описать методику получения координат, в том числе с указанием источника данных и инструмента (при наличии)')
    it_use = Column(Text, nullable=False, comment='Вариант использования набора ПД у поставщика (в виде настольных карт и схем, настольных ГИС (указать каких), WEB-сервисов (указать каких))')
    it_distribution_format = Column(Text, nullable=False, comment='Возможные формы и форматы предоставления набора ПД (в цифровом или ином виде). Справочно: для иных материалов - на бумаге, на пластике, на пленке и другие; для цифровых материалов в соответствии с п. 12 настоящего опросного листа')
    it_distribution_method = Column(Text, nullable=False, comment='Способы предоставления и протоколы обмена набора ПД в цифровой форме. Справочно: способы предоставления - на магнитном носителе, по электронной почте, в виде сервиса и другие')
    it_distribution_protocol = Column(Text, comment='Способы предоставления и протоколы обмена набора ПД в цифровой форме. Справочно: протоколы обмена - HTTPS, WMS, WMTS, REST API и другие')
    it_base_services = Column(Text, nullable=False, comment='Предполагаемые базовые сервисы на основе набора ПД для Национального геопортала. Справочно: визуализация, поиск, фильтрация, загрузка и другие')
    it_cis_publication = Column(Boolean, nullable=False, comment='Допускается размещение и публикация открытых наборов ПД на Геопортале инфраструктуры пространственных данных государств-участников СНГ')

class SurveyContact(Base):
    __tablename__ = 'survey_contacts'
    __table_args__ = (
        UniqueConstraint('survey_id', 'contact_id', name='unique_survey_contact'),
        {'comment': 'Таблица-связка между опросниками и контактами поставщиков'},
    )

    survey_contacts_id = Column(Integer, primary_key=True, autoincrement=True, comment='Идентификатор связи опросник-контакт')
    survey_id = Column(Integer, ForeignKey('surveys.survey_id', ondelete='CASCADE'), nullable=False, comment='Идентификатор опросника')
    contact_id = Column(Integer, ForeignKey('contacts.contact_id', ondelete='CASCADE'), nullable=False, comment='Идентификатор контактного лица')

class SurveyInfoType(Base):
    __tablename__ = 'survey_info_types'
    __table_args__ = (
        UniqueConstraint('survey_id', 'info_id', name='unique_survey_info'),
        {'comment': 'Связь опросников с несколькими видами сведений'},
    )

    link_id = Column(Integer, primary_key=True, autoincrement=True, comment='Идентификатор связи "опросник - вид сведений"')
    survey_id = Column(Integer, ForeignKey('surveys.survey_id', ondelete='CASCADE'), nullable=False, comment='Идентификатор опросника')
    info_id = Column(Integer, ForeignKey('info_types.info_id', ondelete='CASCADE'), nullable=False, comment='Идентификатор вида сведений')

class SurveyInteraction(Base):
    __tablename__ = 'survey_interactions'
    __table_args__ = (
        UniqueConstraint('survey_id', 'interaction_id', name='unique_survey_interaction_link'),
        {'comment': 'Связь опросников с несколькими вариантами взаимодействия'},
    )

    link_id = Column(Integer, primary_key=True, autoincrement=True)
    survey_id = Column(Integer, ForeignKey('surveys.survey_id', ondelete='CASCADE'), nullable=False)
    interaction_id = Column(Integer, ForeignKey('ref_interactions.interaction_id', ondelete='CASCADE'), nullable=False)

class SurveyLink(Base):
    __tablename__ = 'survey_links'
    __table_args__ = (
        UniqueConstraint('survey_id', 'survey_link', name='unique_survey_link'),
        {'comment': 'Таблица-связка между опросниками и ссылками поставщиков на НПД, сервисы, варианты доступа'},
    )

    survey_link_id = Column(Integer, primary_key=True, autoincrement=True, comment='Идентификатор связи опросник-ссылка')
    survey_id = Column(Integer, ForeignKey('surveys.survey_id', ondelete='CASCADE'), nullable=False, comment='Идентификатор опросника')
    survey_link = Column(Text, nullable=False, comment='Ссылка поставщика на НПД, сервис или вариант доступа')

