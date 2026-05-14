-- 1. СПРАВОЧНИКИ
CREATE TABLE suppliers (
    supplier_id SERIAL PRIMARY KEY,
    supplier_name VARCHAR(255) NOT NULL
);

CREATE TABLE contacts (
    contact_id SERIAL PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL
);

CREATE TABLE ref_statuses (
    status_id SERIAL PRIMARY KEY,
    status_name VARCHAR(50) NOT NULL
);

CREATE TABLE ref_micro_statuses (
    micro_status_id SERIAL PRIMARY KEY,
    micro_status_name VARCHAR(50) NOT NULL
);

CREATE TABLE datasets (
    dataset_id SERIAL PRIMARY KEY,
    dataset_name VARCHAR(255) NOT NULL
);

CREATE TABLE info_types (
    info_id SERIAL PRIMARY KEY,
    info_name VARCHAR(255) NOT NULL
);

CREATE TABLE stages (
    stage_id SERIAL PRIMARY KEY,
    stage_name VARCHAR(255) NOT NULL,
    track_category VARCHAR(50) NOT NULL,
    stage_type VARCHAR(20) NOT NULL CHECK (stage_type IN ('Веха', 'Задача')),
    stage_order INTEGER NOT NULL,
    duration_days INTEGER
);
CREATE INDEX idx_stages_cat_type_order ON stages(track_category, stage_type, stage_order);

-- 2. ОПЕРАЦИОННЫЕ
CREATE TABLE projects (
    project_id SERIAL PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    project_name VARCHAR(255) NOT NULL,
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
    comments VARCHAR(500),
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
    comments VARCHAR(500),
    document_url TEXT
);
CREATE INDEX idx_istages_item ON item_stages(item_id);
CREATE INDEX idx_istages_stage ON item_stages(stage_id);