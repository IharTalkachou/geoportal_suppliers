import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache  # 🔑 Импорт кэширования

def render_projects_tab(session):
    st.subheader("📂 Проекты")
    
    # Загрузка через кэш
    df = query_db("SELECT project_id, supplier_id, project_name, main_contact_id, status, notes FROM projects ORDER BY project_id DESC")
    
    # Гарантируем nullable-целые для FK
    for col in ["supplier_id", "main_contact_id", "status"]:
        if col in df.columns:
            df[col] = df[col].astype("Int64")

    # Справочники тоже кэшируем
    suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    contacts = query_db("SELECT contact_id, full_name FROM contacts ORDER BY full_name")
    statuses = query_db("SELECT status_id, status_name FROM ref_statuses ORDER BY status_name")

    lookups = {
        "suppliers": dict(zip(suppliers["supplier_id"], suppliers["supplier_name"])),
        "contacts": {None: "Не выбран", **dict(zip(contacts["contact_id"], contacts["full_name"]))},
        "ref_statuses": dict(zip(statuses["status_id"], statuses["status_name"]))
    }

    col_config = {
        "project_name": st.column_config.TextColumn("Название проекта", required=True),
        "supplier_id": st.column_config.SelectboxColumn("Поставщик", options=lookups["suppliers"], required=True),
        "main_contact_id": st.column_config.SelectboxColumn("Основной контакт", options=lookups["contacts"], required=False),
        "status": st.column_config.SelectboxColumn("Статус", options=lookups["ref_statuses"], required=True),
        "notes": st.column_config.TextColumn("Примечания"),
        "project_id": st.column_config.NumberColumn("ID", disabled=True, width="small")
    }

    with st.form("projects_form", clear_on_submit=False):
        edited_df = st.data_editor(df, key="projects_editor", hide_index=True, use_container_width=True, num_rows="dynamic", column_config=col_config, disabled=["project_id"])
        
        orig_ids = set(df["project_id"].dropna().astype(int))
        curr_ids = set(edited_df["project_id"].dropna().astype(int))
        deleted_ids = orig_ids - curr_ids
        if deleted_ids:
            st.warning(f"⚠️ Вы удалили {len(deleted_ids)} проект(ов). Связанные данные будут удалены (CASCADE).")

        col1, col2 = st.columns([1, 4])
        if col1.form_submit_button("💾 Сохранить проекты", type="primary"):
            try:
                sync_projects_to_db(session, df, edited_df)
                st.success("✅ Изменения сохранены!")
                clear_cache()  # 🔑 Сбрасываем кэш после успешной записи
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка БД: {e}")
                session.rollback()

def sync_projects_to_db(session, original_df, edited_df):
    # 1. Удаления
    orig_ids = set(original_df["project_id"].dropna().astype(int))
    curr_ids = set(edited_df["project_id"].dropna().astype(int))
    deleted = list(orig_ids - curr_ids)
    if deleted:
        session.execute(text("DELETE FROM projects WHERE project_id IN :ids"), {"ids": tuple(deleted)})

    # 2. Вставка и Обновление
    for _, row in edited_df.iterrows():
        pid = row.get("project_id")
        is_new = pd.isna(pid)
        
        # Преобразование значений из Selectbox в SQL-формат
        sup_id = int(row["supplier_id"]) if pd.notna(row["supplier_id"]) else None
        cont_id = int(row["main_contact_id"]) if pd.notna(row["main_contact_id"]) else None
        stat_id = int(row["status"]) if pd.notna(row["status"]) else None

        if is_new:
            session.execute(text("""
                INSERT INTO projects (supplier_id, project_name, main_contact_id, status, notes)
                VALUES (:sup, :name, :cont, :stat, :notes)
            """), {"sup": sup_id, "name": row["project_name"], "cont": cont_id, "stat": stat_id, "notes": row.get("notes")})
        else:
            session.execute(text("""
                UPDATE projects SET supplier_id=:sup, project_name=:name, main_contact_id=:cont,
                                    status=:stat, notes=:notes
                WHERE project_id=:id
            """), {"sup": sup_id, "name": row["project_name"], "cont": cont_id, "stat": stat_id, "notes": row.get("notes"), "id": int(pid)})
            
    session.commit()
    clear_cache()