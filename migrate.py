import os
import pandas as pd
from sqlalchemy import create_engine
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# 🔧 КОНФИГУРАЦИЯ
DB_USER = "app_user_dev"
DB_PASS = "app_user_pass"  # <--- ВСТАВЬТЕ ПАРОЛЬ
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "geodata_suppliers_dev"
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Порядок загрузки (строго по зависимостям FK)
TABLE_ORDER = [
    "suppliers", "contacts", "ref_statuses", "ref_micro_statuses",
    "datasets", "info_types", "stages",
    "projects", "project_items",
    "project_stages", "item_stages"
]

# 🔑 ЯВНЫЙ МАППИНГ КОЛОНОК: {имя_в_csv} : {имя_в_бд}
# Если колонка есть в БД, но нет в этом словаре - она будет пропущена.
# Если колонка есть в CSV, но нет в этом словаре - она будет пропущена.
# Это гарантирует, что мы вставляем только то, что контролируем.
COLUMN_MAP = {
    "suppliers": {
        "SupplierID": "supplier_id",      # PK, будет проигнорирован при вставке (SERIAL)
        "SupplierName": "supplier_name",
        "SupplierAddress": "supplier_address",
        "SupplierEmail": "supplier_email",
        "SupplierPhone": "supplier_phone",
        "SupplierWebsite": "supplier_website",
        "SupplierManager": "supplier_manager",
        "SupplierNotes": "supplier_notes",
        "SupplierLogo": "supplier_logo"
    },
    "contacts": {
        "ContactID": "contact_id",        # PK, игнорируется
        "SupplierID": "supplier_id",      # FK
        "FullName": "full_name",
        "Position": "position",
        "Email": "email",
        "Phone": "phone",
        "Notes": "notes"
    },
    "ref_statuses": {
        "StatusID": "status_id",          # PK
        "StatusCode": "status_code",
        "StatusName": "status_name",
        "SortOrder": "sort_order"
    },
    "ref_micro_statuses": {
        "MicroStatusID": "micro_status_id",
        "MicroStatusCode": "micro_status_code",
        "MicroStatusName": "micro_status_name",
        "SortOrder": "sort_order"
    },
    "datasets": {
        "DatasetID": "dataset_id",
        "DatasetName": "dataset_name",
        "IsMandatory": "is_mandatory",
        "IsBasic": "is_basic",
        "DatasetIcon": "dataset_icon"
    },
    "info_types": {
        "InfoID": "info_id",
        "DatasetID": "dataset_id",        # FK
        "InfoName": "info_name",
        "Type": "type",
        "Format": "format",
        "Update": "update",
        "UpdatePeriod": "update_period"
    },
    "stages": {
        "StageID": "stage_id",
        "StageName": "stage_name",
        "StageOrder": "stage_order",
        "DurationDays": "duration_days",
        "TrackCategory": "track_category",
        "StageType": "stage_type",
        "StageColor": "stage_color"
    },
    "projects": {
        "ProjectID": "project_id",
        "SupplierID": "supplier_id",
        "ProjectName": "project_name",
        "MainContactID": "main_contact_id",
        "Status": "status",
        "Notes": "notes"
    },
    "project_items": {
        "ItemID": "item_id",
        "ProjectID": "project_id",
        "DatasetID": "dataset_id",
        "InfoID": "info_id",
        "TechContactID": "tech_contact_id"
    },
    "project_stages": {
        "StageProgressID": "stage_progress_id",
        "ProjectID": "project_id",
        "StageID": "stage_id",
        "MicroStatus": "micro_status",
        "IterationCount": "iteration_count",
        "PlannedStart": "planned_start",
        "PlannedEnd": "planned_end",
        "ActualStart": "actual_start",
        "ActualEnd": "actual_end",
        "Comments": "comments",
        "DocumentURL": "document_url"
    },
    "item_stages": {
        "StageProgressID": "stage_progress_id",
        "ItemID": "item_id",
        "StageID": "stage_id",
        "MicroStatus": "micro_status",
        "IterationCount": "iteration_count",
        "PlannedStart": "planned_start",
        "PlannedEnd": "planned_end",
        "ActualStart": "actual_start",
        "ActualEnd": "actual_end",
        "Comments": "comments",
        "DocumentURL": "document_url"
    }
}

def migrate():
    engine = create_engine(DATABASE_URL)
    csv_dir = "csv_export"

    with engine.begin() as conn:
        for table in TABLE_ORDER:
            file_path = os.path.join(csv_dir, f"{table}.csv")
            if not os.path.exists(file_path):
                # Пробуем найти файл с заглавной буквы, если не нашли (на случай, если не переименовали)
                file_path_cap = os.path.join(csv_dir, f"{table.capitalize()}.csv")
                if os.path.exists(file_path_cap):
                    file_path = file_path_cap
                else:
                    logging.warning(f"📂 Файл для {table} не найден. Пропуск.")
                    continue

            logging.info(f"⏳ Загрузка таблицы: {table}")
            
            # Читаем CSV с вашей кодировкой и разделителем
            df = pd.read_csv(file_path, sep=';', encoding='cp1251', keep_default_na=True)
            
            # 🔧 1. Переименование колонок по словарю
            if table in COLUMN_MAP:
                # Инвертируем словарь для удобного поиска: {имя_в_бд: имя_в_csv}
                reverse_map = {v: k for k, v in COLUMN_MAP[table].items()}
                # Оставляем в df только те колонки, которые есть в словаре, и переименовываем их
                cols_to_keep = [k for k in COLUMN_MAP[table].keys() if k in df.columns]
                df = df[cols_to_keep].rename(columns=COLUMN_MAP[table])
                
                # 🔧 2. Исключаем первичные ключи (SERIAL), чтобы PG сам их сгенерировал
                pk_col = f"{table}_id"
                if pk_col in df.columns:
                    df = df.drop(columns=[pk_col])
                    logging.debug(f"   ↪ Исключён автоинкремент {pk_col}")

            # 🔧 3. Очистка данных: пустые строки -> NULL
            df = df.replace(["", "NULL", "  "], None)

            # 🔧 4. Обработка дат
            date_cols = [c for c in df.columns if 'date' in c.lower() or c.lower().endswith('start') or c.lower().endswith('end')]
            for col in date_cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')

            # 🔧 5. Преобразование булевых значений (Access Yes/No → PostgreSQL BOOLEAN)
            # Access хранит: -1 = True, 0 = False. Иногда 1 = True.
            # Явно указываем колонки-флаги для каждой таблицы
            bool_columns = {
                "datasets": ["is_mandatory", "is_basic"],
                # При необходимости добавьте другие таблицы и колонки:
                # "projects": ["is_active"],
            }
            
            if table in bool_columns:
                for col in bool_columns[table]:
                    if col in df.columns and df[col].dtype in ['int64', 'int32', 'object']:
                        # Маппинг значений: -1/1/'1'/'-1' → True, 0/'0' → False
                        df[col] = df[col].map(
                            lambda x: True if x in [1, -1, '1', '-1', True] 
                            else (False if x in [0, '0', False] else None),
                            na_action='ignore'
                        )

            if df.empty:
                logging.warning(f"⚠️ Таблица {table} пуста после обработки. Пропуск.")
                continue
                
            try:
                # method='multi' ускоряет вставку
                df.to_sql(table, conn, if_exists='append', index=False, method='multi')
                logging.info(f"✅ {table}: загружено {len(df)} строк.")
            except Exception as e:
                logging.error(f"❌ Ошибка в {table}: {e}")
                # Выводим первые строки данных для отладки, если ошибка
                logging.error(f"   Данные: {df.head(1).to_dict()}")
                raise 

    logging.info("🎉 Миграция успешно завершена!")

if __name__ == "__main__":
    migrate()