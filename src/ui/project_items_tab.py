import streamlit as st
import pandas as pd
from sqlalchemy import text

def render_project_items_tab(session):
    st.subheader("📦 Состав проектов (Наборы данных → Виды сведений)")
    
    # 1. Загрузка справочников для UI
    projects = pd.read_sql(text("SELECT project_id, project_name FROM projects ORDER BY project_name"), session.bind)
    datasets = pd.read_sql(text("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name"), session.bind)
    info_types = pd.read_sql(text("SELECT info_id, info_name, dataset_id FROM info_types ORDER BY info_name"), session.bind)
    contacts = pd.read_sql(text("SELECT contact_id, full_name FROM contacts ORDER BY full_name"), session.bind)
    
    # Словари для отображения
    proj_map = dict(zip(projects["project_id"], projects["project_name"]))
    ds_map = dict(zip(datasets["dataset_id"], datasets["dataset_name"]))
    info_map = dict(zip(info_types["info_id"], info_types["info_name"]))
    cont_map = {None: "Не выбран"}
    cont_map.update(dict(zip(contacts["contact_id"], contacts["full_name"])))

    # 2. Отображение текущих элементов
    df = pd.read_sql(text("""
        SELECT pi.item_id, 
               p.project_name, 
               d.dataset_name, 
               i.info_name, 
               c.full_name as tech_contact_name
        FROM project_items pi
        JOIN projects p ON pi.project_id = p.project_id
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        LEFT JOIN contacts c ON pi.tech_contact_id = c.contact_id
        ORDER BY p.project_name, d.dataset_name
    """), session.bind)
    
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"Всего элементов: {len(df)}")

    # 3. Форма добавления с зависимым фильтром
    st.markdown("---")
    st.subheader("➕ Добавить новый элемент")
    
    with st.form("add_item_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            selected_proj = st.selectbox("Проект", options=proj_map.keys(), format_func=lambda x: proj_map[x])
            selected_ds = st.selectbox("Набор данных", options=ds_map.keys(), format_func=lambda x: ds_map[x])
        with col2:
            # Динамическая фильтрация: показываем только InfoTypes, привязанные к выбранному Dataset
            valid_infos = info_types[info_types["dataset_id"] == selected_ds]
            selected_info = st.selectbox(
                "Вид сведений", 
                options=valid_infos["info_id"], 
                format_func=lambda x: info_map.get(x, "Не выбрано")
            )
        with col3:
            selected_contact = st.selectbox("Тех. контакт", options=cont_map.keys(), format_func=lambda x: cont_map[x])
            
        add_btn = st.form_submit_button("Добавить связку", type="primary", use_container_width=True)
        
        if add_btn:
            # Валидация уникальности связки (Проект + Набор + Вид сведений)
            check_q = text("""
                SELECT 1 FROM project_items 
                WHERE project_id = :pid AND dataset_id = :did AND info_id = :iid
            """)
            exists = session.execute(check_q, {"pid": selected_proj, "did": selected_ds, "iid": selected_info}).scalar()
            
            if exists:
                st.error("⚠️ Такая связка уже существует в этом проекте.")
            else:
                session.execute(text("""
                    INSERT INTO project_items (project_id, dataset_id, info_id, tech_contact_id)
                    VALUES (:pid, :did, :iid, :cid)
                """), {"pid": selected_proj, "did": selected_ds, "iid": selected_info, "cid": selected_contact})
                session.commit()
                st.success("✅ Элемент успешно добавлен.")
                st.rerun()

    # 4. Удаление выбранных элементов
    st.markdown("---")
    with st.expander("🗑️ Удаление элементов"):
        ids_to_delete = st.multiselect(
            "Выберите элементы для удаления:",
            options=list(zip(df["item_id"], df["project_name"], df["dataset_name"])),
            format_func=lambda x: f"ID:{x[0]} | {x[1]} → {x[2]}"
        )
        if ids_to_delete:
            st.warning(f"Будет удалено {len(ids_to_delete)} элементов. Связанные этапы (`ItemStages`) также удалятся (CASCADE).")
            if st.button("Подтвердить удаление", type="secondary"):
                ids = [item[0] for item in ids_to_delete]
                session.execute(text("DELETE FROM project_items WHERE item_id IN :ids"), {"ids": tuple(ids)})
                session.commit()
                st.success("✅ Удалено.")
                st.rerun()