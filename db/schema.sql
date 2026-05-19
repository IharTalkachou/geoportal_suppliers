-- 1. СПРАВОЧНИКИ
CREATE TABLE suppliers (
    supplier_id SERIAL PRIMARY KEY,
    supplier_name VARCHAR(255) NOT NULL,
    supplier_address TEXT,
    supplier_email VARCHAR(255),
    supplier_phone VARCHAR(50),
    supplier_website VARCHAR(255),
    supplier_manager VARCHAR(255),
    supplier_notes TEXT,
    supplier_logo TEXT
);

CREATE TABLE contacts (
    contact_id SERIAL PRIMARY KEY,
    supplier_id INTEGER REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    full_name VARCHAR(255) NOT NULL,
    position VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    notes TEXT
);
CREATE INDEX idx_contacts_supplier ON contacts(supplier_id);

CREATE TABLE ref_statuses (
    status_id SERIAL PRIMARY KEY,
    status_code VARCHAR(50),
    status_name TEXT NOT NULL,
    sort_order INTEGER
);

CREATE TABLE ref_micro_statuses (
    micro_status_id SERIAL PRIMARY KEY,
    micro_status_code VARCHAR(50),
    micro_status_name TEXT NOT NULL,
    sort_order INTEGER
);

CREATE TABLE datasets (
    dataset_id SERIAL PRIMARY KEY,
    dataset_name TEXT NOT NULL,
    is_mandatory BOOLEAN DEFAULT FALSE,
    is_basic BOOLEAN DEFAULT FALSE,
    dataset_icon TEXT
);

CREATE TABLE info_types (
    info_id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(dataset_id) ON DELETE RESTRICT,
    info_name TEXT NOT NULL,
    type VARCHAR(100),
    format VARCHAR(100),
    update VARCHAR(100),
    update_period VARCHAR(100)
);
CREATE INDEX idx_info_types_dataset ON info_types(dataset_id);

CREATE TABLE stages (
    stage_id SERIAL PRIMARY KEY,
    stage_name TEXT NOT NULL,
    stage_order INTEGER NOT NULL,
    duration_days INTEGER,
    track_category VARCHAR(50) NOT NULL,
    stage_type VARCHAR(20) NOT NULL CHECK (stage_type IN ('Веха', 'Задача')),
    stage_color VARCHAR(20)
);
CREATE INDEX idx_stages_cat_type_order ON stages(track_category, stage_type, stage_order);

-- 2. ОПЕРАЦИОННЫЕ ТАБЛИЦЫ
CREATE TABLE projects (
    project_id SERIAL PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    project_name TEXT NOT NULL,
    main_contact_id INTEGER REFERENCES contacts(contact_id) ON DELETE SET NULL,
    status INTEGER REFERENCES ref_statuses(status_id) ON DELETE RESTRICT,
    notes TEXT
);
CREATE INDEX idx_projects_supplier ON projects(supplier_id);
CREATE INDEX idx_projects_status ON projects(status);

CREATE TABLE project_items (
    item_id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    dataset_id INTEGER NOT NULL REFERENCES datasets(dataset_id) ON DELETE RESTRICT,
    info_id INTEGER NOT NULL REFERENCES info_types(info_id) ON DELETE RESTRICT,
    tech_contact_id INTEGER REFERENCES contacts(contact_id) ON DELETE SET NULL
);
CREATE INDEX idx_items_project ON project_items(project_id);
CREATE INDEX idx_items_dataset ON project_items(dataset_id);
CREATE INDEX idx_items_info ON project_items(info_id);

-- 3. ТРЕКИНГ
CREATE TABLE project_stages (
    stage_progress_id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    stage_id INTEGER NOT NULL REFERENCES stages(stage_id) ON DELETE RESTRICT,
    micro_status INTEGER REFERENCES ref_micro_statuses(micro_status_id) ON DELETE RESTRICT,
    iteration_count INTEGER DEFAULT 1,
    planned_start DATE,
    planned_end DATE,
    actual_start DATE,
    actual_end DATE,
    comments TEXT,
    document_url TEXT
);
CREATE INDEX idx_pstages_project ON project_stages(project_id);
CREATE INDEX idx_pstages_stage ON project_stages(stage_id);

CREATE TABLE item_stages (
    stage_progress_id SERIAL PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES project_items(item_id) ON DELETE CASCADE,
    stage_id INTEGER NOT NULL REFERENCES stages(stage_id) ON DELETE RESTRICT,
    micro_status INTEGER REFERENCES ref_micro_statuses(micro_status_id) ON DELETE RESTRICT,
    iteration_count INTEGER DEFAULT 1,
    planned_start DATE,
    planned_end DATE,
    actual_start DATE,
    actual_end DATE,
    comments TEXT,
    document_url TEXT
);
CREATE INDEX idx_istages_item ON item_stages(item_id);
CREATE INDEX idx_istages_stage ON item_stages(stage_id);