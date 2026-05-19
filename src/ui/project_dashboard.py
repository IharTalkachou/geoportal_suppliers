import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache
from ui.bureaucracy_tab import render_bureaucracy_tab
from ui.technology_tab import render_technology_tab


def render_project_dashboard(session):
    st.subheader("📂 Управление проектами")

    if "dash_edit_mode" not in st.session_state:
        st.session_state.dash_edit_mode = False
    if "selected_project_id" not in st.session_state:
        st.session_state.selected_project_id = None

    # 🔍 1. Зависимые фильтры
    suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    sup_map = dict(zip(suppliers["supplier_name"], suppliers["supplier_id"]))
    selected_sup = st.selectbox("🔍 Поставщик", ["Все"] + list(sup_map.keys()), key="dash_sup_filter")

    if selected_sup == "Все":
        projects = query_db("SELECT project_id, project_name FROM projects ORDER BY project_name")
    else:
        projects = query_db("SELECT project_id, project_name FROM projects WHERE supplier_id = :sid ORDER BY project_name", {"sid": sup_map[selected_sup]})

    proj_map = dict(zip(projects["project_id"], projects["project_name"]))
    selected_proj_id = st.selectbox(
        "🔍 Проект", 
        [None] + list(proj_map.keys()), 
        format_func=lambda x: proj_map.get(x, "Выберите проект..."), 
        key="dash_proj_filter"
    )

    st.session_state.selected_project_id = selected_proj_id

    if not selected_proj_id:
        st.info("👆 Выберите поставщика и проект для начала работы.")
        return

    # 📋 2. Карточка проекта (вертикальная сетка)
    proj_data = query_db("""
        SELECT p.project_id, p.project_name, s.supplier_name, c.full_name, rs.status_name, p.notes
        FROM projects p
        LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
        LEFT JOIN contacts c ON p.main_contact_id = c.contact_id
        LEFT JOIN ref_statuses rs ON p.status = rs.status_id
        WHERE p.project_id = :pid
    """, {"pid": selected_proj_id}).iloc[0]

    st.markdown("### 📋 Детали проекта")
    
    # Вертикальные метрики
    st.metric("📂 Проект", proj_data['project_name'])
    st.metric("🏢 Поставщик", proj_data['supplier_name'])
    st.metric("📊 Статус", proj_data['status_name'])
    st.metric("👤 Контакт", proj_data['full_name'] or "Не указан")

    # Примечание и кнопка редактирования
    col_note, col_btn = st.columns([3, 1])
    with col_note:
        st.markdown(f"**📝 Примечание:** {proj_data['notes'] or '-'}")
    with col_btn:
        if st.button("✏️ Изменить реквизиты", type="secondary", use_container_width=True):
            st.session_state.dash_edit_mode = not st.session_state.dash_edit_mode

    st.markdown("---")

    # 📝 3. Форма редактирования реквизитов проекта
    if st.session_state.dash_edit_mode:
        with st.form("edit_proj_form"):
            st.markdown("#### 📝 Редактирование реквизитов")
            
            sup_list = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
            cont_list = query_db("SELECT contact_id, full_name FROM contacts ORDER BY full_name")
            stat_list = query_db("SELECT status_id, status_name FROM ref_statuses ORDER BY status_name")

            sup_idx = list(sup_list["supplier_name"]).index(proj_data['supplier_name']) if proj_data['supplier_name'] in list(sup_list["supplier_name"]) else 0
            stat_idx = list(stat_list["status_name"]).index(proj_data['status_name']) if proj_data['status_name'] in list(stat_list["status_name"]) else 0
            cont_idx = 0
            if proj_data['full_name'] and proj_data['full_name'] in list(cont_list["full_name"]):
                cont_idx = list(cont_list["full_name"]).index(proj_data['full_name']) + 1

            col1, col2 = st.columns(2)
            with col1:
                p_name = st.text_input("Название проекта", value=proj_data['project_name'])
                p_sup = st.selectbox("Поставщик", sup_list["supplier_name"].tolist(), index=sup_idx)
                p_stat = st.selectbox("Статус", stat_list["status_name"].tolist(), index=stat_idx)
            with col2:
                p_contact = st.selectbox("Основной контакт", ["Не указан"] + cont_list["full_name"].tolist(), index=cont_idx)
                p_notes = st.text_area("Примечание", value=proj_data['notes'] or "")

            if st.form_submit_button("💾 Сохранить изменения проекта", type="primary"):
                try:
                    session.execute(text("""
                        UPDATE projects SET project_name=:name, supplier_id=:sup, main_contact_id=:cont,
                                            status=:stat, notes=:notes WHERE project_id=:id
                    """), {
                        "name": p_name,
                        "sup": sup_list[sup_list["supplier_name"]==p_sup]["supplier_id"].iloc[0],
                        "cont": None if p_contact == "Не указан" else cont_list[cont_list["full_name"]==p_contact]["contact_id"].iloc[0],
                        "stat": stat_list[stat_list["status_name"]==p_stat]["status_id"].iloc[0],
                        "notes": p_notes,
                        "id": selected_proj_id
                    })
                    session.commit()
                    clear_cache()
                    st.session_state.dash_edit_mode = False
                    st.success("✅ Реквизиты проекта обновлены!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка БД: {e}")
                    session.rollback()
        st.divider()

    # ==========================================
    # БЛОК: СОСТАВ ПРОЕКТА (project_items) - ID скрыт
    # ==========================================
    st.markdown("### 📦 Состав проекта (Наборы → Виды)")

    datasets = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
    info_types = query_db("SELECT info_id, info_name, dataset_id FROM info_types ORDER BY info_name")
    contacts = query_db("SELECT contact_id, full_name FROM contacts ORDER BY full_name")

    ds_map = dict(zip(datasets["dataset_name"], datasets["dataset_id"]))
    info_map = {
        row["info_name"]: {"id": row["info_id"], "ds_id": row["dataset_id"]}
        for _, row in info_types.iterrows()
    }
    cont_map = dict(zip(contacts["full_name"], contacts["contact_id"]))

    items_df = query_db("""
        SELECT pi.item_id, d.dataset_name, i.info_name, c.full_name as tech_contact
        FROM project_items pi
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        LEFT JOIN contacts c ON pi.tech_contact_id = c.contact_id
        WHERE pi.project_id = :pid
        ORDER BY d.dataset_name, i.info_name
    """, {"pid": selected_proj_id})

    item_col_config = {
        "dataset_name": st.column_config.SelectboxColumn("Набор данных", options=list(ds_map.keys()), required=True),
        "info_name": st.column_config.SelectboxColumn("Вид сведений", options=list(info_map.keys()), required=True),
        "tech_contact": st.column_config.SelectboxColumn("Тех. контакт", options=["Не выбран"] + list(cont_map.keys())),
        "item_id": st.column_config.NumberColumn("ID", disabled=True)
    }

    with st.form("items_editor_form"):
        edited_items = st.data_editor(
            items_df, key="dashboard_items_editor", hide_index=True, use_container_width=True,
            num_rows="dynamic", column_config=item_col_config, disabled=["item_id"],
            column_order=["dataset_name", "info_name", "tech_contact"]  # 🔹 ID скрыт из UI
        )

        orig_items = set(items_df["item_id"].dropna().astype(int))
        curr_items = set(edited_items["item_id"].dropna().astype(int))
        deleted_items = list(orig_items - curr_items)

        if st.form_submit_button("💾 Сохранить состав проекта", type="primary"):
            try:
                if deleted_items:
                    session.execute(
                        text("DELETE FROM project_items WHERE item_id IN :ids"),
                        {"ids": tuple(deleted_items)}
                    )

                for _, row in edited_items.iterrows():
                    pid = row.get("item_id")
                    is_new = pd.isna(pid)
                    ds_id = ds_map.get(row.get("dataset_name"))
                    info_data = info_map.get(row.get("info_name"))
                    info_id = info_data["id"] if info_data else None
                    contact_name = row.get("tech_contact")
                    cont_id = cont_map.get(contact_name) if contact_name != "Не выбран" else None

                    if is_new and ds_id and info_id:
                        session.execute(text("""
                            INSERT INTO project_items (project_id, dataset_id, info_id, tech_contact_id)
                            VALUES (:pid, :ds, :info, :cont)
                        """), {"pid": selected_proj_id, "ds": ds_id, "info": info_id, "cont": cont_id})
                    elif not is_new and ds_id and info_id:
                        session.execute(text("""
                            UPDATE project_items SET dataset_id=:ds, info_id=:info, tech_contact_id=:cont
                            WHERE item_id=:id
                        """), {"ds": ds_id, "info": info_id, "cont": cont_id, "id": int(pid)})

                session.commit()
                clear_cache()
                st.success("✅ Состав проекта обновлён!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка БД: {e}")
                session.rollback()

    st.divider()
    st.markdown("---")
    
    # ==========================================
    # ТАБЫ: БЮРОКРАТИЯ И ТЕХНОЛОГИЯ
    # ==========================================
    tab_buro, tab_tech = st.tabs(["📜 Бюрократия (ProjectStages)", "⚙️ Технология (ProjectItems)"])
    
    with tab_buro:
        render_bureaucracy_tab(session, selected_proj_id)
        
    with tab_tech:
        render_technology_tab(session, selected_proj_id)