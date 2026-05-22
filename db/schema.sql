-- ==========================================
-- SCHEMA: public (PostgreSQL 18)
-- ==========================================

-- 1. Справочники статусов
CREATE TABLE ref_statuses (
    status_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status_name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE ref_micro_statuses (
    micro_status_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    micro_status_name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE ref_file_formats (
    format_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    format_name VARCHAR(50) UNIQUE NOT NULL
);

CREATE TABLE ref_update_periods (
    period_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_name VARCHAR(50) UNIQUE NOT NULL
);

-- 2. Поставщики и Контакты
CREATE TABLE suppliers (
    supplier_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_name VARCHAR(255) NOT NULL,
    supplier_address TEXT,
    supplier_email VARCHAR(255),
    supplier_phone VARCHAR(50),
    supplier_website VARCHAR(255),
    supplier_manager VARCHAR(255),
    supplier_notes TEXT
);

CREATE TABLE contacts (
    contact_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_id INT NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    full_name VARCHAR(255) NOT NULL,
    position VARCHAR(150),
    email VARCHAR(255),
    phone VARCHAR(50),
    notes TEXT
);

-- 3. Справочники данных
CREATE TABLE datasets (
    dataset_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_name VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE info_types (
    info_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_id INT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    info_name VARCHAR(255) NOT NULL,
    type VARCHAR(50),
    format VARCHAR(50) REFERENCES ref_file_formats(format_name),
    "update" VARCHAR(50) REFERENCES ref_update_periods(period_name)
);

-- 4. Проекты
CREATE TABLE projects (
    project_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_name VARCHAR(255) NOT NULL,
    supplier_id INT NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    main_contact_id INT REFERENCES contacts(contact_id) ON DELETE SET NULL,
    status INT REFERENCES ref_statuses(status_id),
    notes TEXT
);

-- 5. Состав проекта
CREATE TABLE project_items (
    item_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id INT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    dataset_id INT NOT NULL REFERENCES datasets(dataset_id) ON DELETE RESTRICT,
    info_id INT NOT NULL REFERENCES info_types(info_id) ON DELETE RESTRICT,
    tech_contact_id INT REFERENCES contacts(contact_id) ON DELETE SET NULL
);

-- 6. Справочник этапов
CREATE TABLE stages (
    stage_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stage_name VARCHAR(255) NOT NULL,
    stage_order INT NOT NULL,
    duration_days INT DEFAULT 0,
    track_category VARCHAR(50) NOT NULL,
    stage_type VARCHAR(50) NOT NULL,
    stage_color VARCHAR(20)
);

-- 7. Этапы проектов (Бюрократия)
CREATE TABLE project_stages (
    stage_progress_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id INT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    stage_id INT NOT NULL REFERENCES stages(stage_id) ON DELETE RESTRICT,
    micro_status INT NOT NULL REFERENCES ref_micro_statuses(micro_status_id),
    iteration_count INT DEFAULT 1,
    planned_start DATE,
    planned_end DATE,
    actual_start DATE,
    actual_end DATE,
    comments TEXT
);

-- 8. Этапы по наборам (Технология)
CREATE TABLE item_stages (
    stage_progress_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id INT NOT NULL REFERENCES project_items(item_id) ON DELETE CASCADE,
    stage_id INT NOT NULL REFERENCES stages(stage_id) ON DELETE RESTRICT,
    micro_status INT NOT NULL REFERENCES ref_micro_statuses(micro_status_id),
    iteration_count INT DEFAULT 1,
    planned_start DATE,
    planned_end DATE,
    actual_start DATE,
    actual_end DATE,
    comments TEXT
);

-- 9. АДМИНКА: Пользователи
CREATE TABLE users (
    user_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'editor', 'user')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);

-- 10. АДМИНКА: Журнал действий (Audit Log)
CREATE TABLE audit_log (
    log_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id INT REFERENCES users(user_id) ON DELETE SET NULL,
    action VARCHAR(50) NOT NULL, -- LOGIN, LOGOUT, INSERT, UPDATE, DELETE, TAB_SWITCH, EXPORT
    target_table VARCHAR(100),
    target_id INT,
    old_value JSONB,
    new_value JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 11. ПРЕДСТАВЛЕНИЕ для аналитики
CREATE OR REPLACE VIEW v_bi_flat_export AS
SELECT 
    s.supplier_name,
    p.project_name,
    rs.status_name AS project_status,
    d.dataset_name,
    i.info_name,
    st.stage_name,
    rms.micro_status_name AS stage_micro_status,
    ps.planned_start,
    ps.planned_end,
    ps.actual_start,
    ps.actual_end,
    ps.comments AS stage_comments,
    NULL::TEXT AS document_url, -- Заглушка под будущие ссылки
    ps.stage_progress_id
FROM project_stages ps
JOIN projects p ON ps.project_id = p.project_id
JOIN suppliers s ON p.supplier_id = s.supplier_id
LEFT JOIN ref_statuses rs ON p.status = rs.status_id
JOIN stages st ON ps.stage_id = st.stage_id
JOIN ref_micro_statuses rms ON ps.micro_status = rms.micro_status_id
LEFT JOIN project_items pi ON ps.project_id = pi.project_id -- Упрощённая связь для плоского вида
LEFT JOIN datasets d ON pi.dataset_id = d.dataset_id
LEFT JOIN info_types i ON pi.info_id = i.info_id
UNION ALL
SELECT 
    s.supplier_name, p.project_name, rs.status_name, d.dataset_name, i.info_name,
    st.stage_name, rms.micro_status_name,
    ist.planned_start, ist.planned_end, ist.actual_start, ist.actual_end,
    ist.comments, NULL, ist.stage_progress_id
FROM item_stages ist
JOIN project_items pi ON ist.item_id = pi.item_id
JOIN projects p ON pi.project_id = p.project_id
JOIN suppliers s ON p.supplier_id = s.supplier_id
LEFT JOIN ref_statuses rs ON p.status = rs.status_id
JOIN stages st ON ist.stage_id = st.stage_id
JOIN ref_micro_statuses rms ON ist.micro_status = rms.micro_status_id
JOIN datasets d ON pi.dataset_id = d.dataset_id
JOIN info_types i ON pi.info_id = i.info_id;

-- Индексы для производительности
CREATE INDEX idx_projects_supplier ON projects(supplier_id);
CREATE INDEX idx_project_items_project ON project_items(project_id);
CREATE INDEX idx_project_stages_project ON project_stages(project_id);
CREATE INDEX idx_item_stages_item ON item_stages(item_id);
CREATE INDEX idx_audit_log_user_time ON audit_log(user_id, created_at DESC);
CREATE INDEX idx_users_username ON users(username);