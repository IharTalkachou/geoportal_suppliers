import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache
from config.auth import log_action

def render_datasets_tab(session, user_role="user"):
    st.subheader("📚 Справочники данных")
    is_readonly = (user_role == "user")

    # 1. 📑 СЕРВЕРНАЯ НАВИГАЦИЯ
    choice = st.segmented_control(
        "Разделы справочника",
        options=["🗃️ Наборы данных", "📄 Виды сведений"],
        default="🗃️ Наборы данных",
        key="ds_sub_nav",
        label_visibility="collapsed"
    )
    st.markdown("---")

    # ==========================================
    # РАЗДЕЛ 1: НАБОРЫ ДАННЫХ
    # ==========================================
    if choice == "🗃️ Наборы данных":
        render_datasets_manager(session, is_readonly)

    # ==========================================
    # РАЗДЕЛ 2: ВИДЫ СВЕДЕНИЙ
    # ==========================================
    elif choice == "📄 Виды сведений":
        render_info_types_manager(session, is_readonly)

# ==========================================
# 🛠️ ПОД-ФУНКЦИИ (КОМПОНЕНТЫ)
# ==========================================

def render_datasets_manager(session, is_readonly):
    ds_df = query_db("SELECT dataset_id, dataset_name, is_mandatory, is_basic FROM datasets ORDER BY is_mandatory DESC, dataset_name")

    # Размещаем радио-кнопку. Она автоматически исключает выбор нескольких вариантов.
    filter_mode = st.radio(
        "🔍 Фильтр наборов по обязательности:",
        options=["Все", "Только обязательные", "Только необязательные"],
        horizontal=False, # Как ты и просил: один под другим
        key="ds_filter_radio"
    )
    
    # Логика фильтрации
    display_ds = ds_df.copy()
    if filter_mode == "Только обязательные":
        display_ds = display_ds[display_ds["is_mandatory"] == True]
    elif filter_mode == "Только необязательные":
        display_ds = display_ds[display_ds["is_mandatory"] == False]

    st.markdown(f"**Отображено записей:** {len(display_ds)}")

    st.dataframe(display_ds[["dataset_name", "is_mandatory", "is_basic"]], 
                 width="stretch", 
                 hide_index=True,
                 height=500,
                 column_config={
                     "dataset_name": "Название набора", 
                     "is_mandatory": "Обязательный", 
                     "is_basic": "Базовый"
                 })

    if not is_readonly:
        with st.expander("➕ Добавить / ✏️ Редактировать набор"):
            edit_options = ["(Создать новый)"] + ds_df["dataset_name"].tolist()
            sel_ds = st.selectbox("Выберите набор для редактирования:", edit_options, key="ds_edit_selector")
            is_editing = sel_ds != "(Создать новый)"

            if st.session_state.get("ds_prev_sel") != sel_ds:
                if is_editing:
                    curr = ds_df[ds_df["dataset_name"] == sel_ds].iloc[0]
                    st.session_state["ds_name_in"] = curr["dataset_name"]
                    st.session_state["ds_mand_in"] = bool(curr["is_mandatory"])
                    st.session_state["ds_basic_in"] = bool(curr["is_basic"])
                else:
                    st.session_state["ds_name_in"] = ""
                    st.session_state["ds_mand_in"] = False
                    st.session_state["ds_basic_in"] = False
                st.session_state["ds_prev_sel"] = sel_ds

            with st.form("ds_save_form"):
                st.text_input("Название набора *", key="ds_name_in")
                c1, c2 = st.columns(2)
                with c1: st.checkbox("Обязательный (is_mandatory)", key="ds_mand_in")
                with c2: st.checkbox("Базовый (is_basic)", key="ds_basic_in")
                
                if st.form_submit_button("💾 Сохранить набор", width="stretch"):
                    new_name = st.session_state["ds_name_in"].strip()
                    if not new_name:
                        st.error("❌ Название обязательно")
                    else:
                        try:
                            if is_editing:
                                target_id = int(ds_df[ds_df["dataset_name"] == sel_ds].iloc[0]["dataset_id"])
                                # 🔍 ЛОГИРОВАНИЕ
                                log_action(st.session_state["auth"]["user_id"], "UPDATE_DATASET", "datasets", target_id, new={"name": new_name})
                                session.execute(text("UPDATE datasets SET dataset_name=:n, is_mandatory=:m, is_basic=:b WHERE dataset_id=:id"),
                                                {"n": new_name, "m": st.session_state["ds_mand_in"], "b": st.session_state["ds_basic_in"], "id": target_id})
                            else:
                                # 🔍 ЛОГИРОВАНИЕ
                                log_action(st.session_state["auth"]["user_id"], "CREATE_DATASET", "datasets", None, new={"name": new_name})
                                session.execute(text("INSERT INTO datasets (dataset_name, is_mandatory, is_basic) VALUES (:n, :m, :b)"),
                                                {"n": new_name, "m": st.session_state["ds_mand_in"], "b": st.session_state["ds_basic_in"]})
                            session.commit(); clear_cache(); st.success("✅ Сохранено!"); st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}"); session.rollback()

            if is_editing:
                if st.button("🗑 Удалить набор", type="secondary", width="stretch", key="ds_del_btn"):
                    target_id = int(ds_df[ds_df["dataset_name"] == sel_ds].iloc[0]["dataset_id"])
                    has_info_types = session.execute(text("SELECT 1 FROM info_types WHERE dataset_id = :id LIMIT 1"), {"id": target_id}).scalar()
                    in_use = session.execute(text("SELECT 1 FROM project_items WHERE dataset_id = :id LIMIT 1"), {"id": target_id}).scalar()
                    
                    if has_info_types or in_use:
                        st.error("❌ Нельзя удалить набор: он используется или содержит виды сведений.")
                    else:
                        try:
                            log_action(st.session_state["auth"]["user_id"], "DELETE_DATASET", "datasets", target_id, old={"name": sel_ds})
                            session.execute(text("DELETE FROM datasets WHERE dataset_id = :id"), {"id": target_id})
                            session.commit(); clear_cache(); st.success("🗑 Удалён"); st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}"); session.rollback()

def render_info_types_manager(session, is_readonly):
    datasets_list = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
    if datasets_list.empty:
        st.info("Сначала создайте хотя бы один набор данных.")
        return

    ds_map = dict(zip(datasets_list["dataset_name"], datasets_list["dataset_id"]))
    sel_ds_name = st.selectbox("📦 Выберите набор данных:", list(ds_map.keys()), key="info_tab_ds_sel")
    sel_ds_id = ds_map[sel_ds_name]

    # Справочники из БД
    formats_list = query_db("SELECT format_name FROM ref_file_formats ORDER BY format_name")["format_name"].tolist()
    periods_list = query_db("SELECT period_name FROM ref_update_periods ORDER BY period_name")["period_name"].tolist()

    info_df = query_db("""
        SELECT it.info_id, it.info_name, it.type, it.format, it."update",
               COALESCE(STRING_AGG(DISTINCT s.supplier_name, ', ' ORDER BY s.supplier_name), '—') AS suppliers
        FROM info_types it
        LEFT JOIN project_items pi ON it.info_id = pi.info_id
        LEFT JOIN projects p ON pi.project_id = p.project_id
        LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
        WHERE it.dataset_id = :did
        GROUP BY it.info_id, it.info_name, it.type, it.format, it."update"
        ORDER BY it.info_name
    """, {"did": sel_ds_id})

    # 🔍 UI SIDE-QUEST: Быстрый поиск по видам
    search_q = st.text_input("🔍 Быстрый поиск по названию вида...", key="info_search_q").lower()
    display_info = info_df.copy()
    if search_q:
        display_info = display_info[display_info["info_name"].str.lower().str.contains(search_q)]

    st.dataframe(display_info[["info_name", "type", "format", "update", "suppliers"]], width="stretch", hide_index=True)

    if not is_readonly:
        with st.expander("➕ Добавить / ✏️ Редактировать вид"):
            edit_opts_i = ["(Создать новый)"] + info_df["info_name"].tolist()
            sel_i = st.selectbox("Выберите вид:", edit_opts_i, key="info_edit_selector")
            is_editing_i = sel_i != "(Создать новый)"

            # Логика инициализации полей
            if st.session_state.get("info_prev_sel") != sel_i:
                if is_editing_i:
                    curr = info_df[info_df["info_name"] == sel_i].iloc[0]
                    st.session_state["i_name_in"] = curr["info_name"]
                    st.session_state["i_type_in"] = curr["type"] if curr["type"] in ["Данные", "Сервис"] else "Данные"
                    
                    # 🛠️ ПРЕОБРАЗОВАНИЕ СТРОКИ ФОРМАТОВ В СПИСОК ДЛЯ MULTISELECT
                    db_formats = curr["format"] or ""
                    # Очищаем от пробелов и фильтруем только те, что есть в справочнике
                    st.session_state["i_format_in"] = [f.strip() for f in db_formats.split(",") if f.strip() in formats_list]
                    
                    st.session_state["i_upd_in"] = curr["update"] if curr["update"] in periods_list else (periods_list[0] if periods_list else "")
                else:
                    st.session_state["i_name_in"] = ""
                    st.session_state["i_type_in"] = "Данные"
                    st.session_state["i_format_in"] = []
                    st.session_state["i_upd_in"] = periods_list[0] if periods_list else ""
                st.session_state["info_prev_sel"] = sel_i

            with st.form("info_save_form"):
                st.text_input("Название вида *", key="i_name_in")
                c1, c2, c3 = st.columns(3)
                with c1: st.selectbox("Тип", ["Данные", "Сервис"], key="i_type_in")
                with c2: 
                    # 🛠️ ЗАМЕНА SELECTBOX НА MULTISELECT
                    st.multiselect("Допустимые форматы", options=formats_list, key="i_format_in")
                with c3: 
                    st.selectbox("Срок обновления", options=periods_list, key="i_upd_in")
                
                if st.form_submit_button("💾 Сохранить вид", width="stretch"):
                    name = st.session_state["i_name_in"].strip()
                    # 🛠️ СКЛЕЙКА СПИСКА В СТРОКУ ПЕРЕД СОХРАНЕНИЕМ
                    fmt_string = ", ".join(st.session_state["i_format_in"])
                    
                    if name:
                        try:
                            if is_editing_i:
                                t_id = int(info_df[info_df["info_name"] == sel_i].iloc[0]["info_id"])
                                # 🔍 ЛОГИРОВАНИЕ
                                log_action(st.session_state["auth"]["user_id"], "UPDATE_INFO_TYPE", "info_types", t_id, new={"name": name, "format": fmt_string})
                                session.execute(text("UPDATE info_types SET info_name=:n, type=:t, format=:f, \"update\"=:u WHERE info_id=:id"),
                                                {"n": name, "t": st.session_state["i_type_in"], "f": fmt_string, "u": st.session_state["i_upd_in"], "id": t_id})
                            else:
                                # 🔍 ЛОГИРОВАНИЕ
                                log_action(st.session_state["auth"]["user_id"], "CREATE_INFO_TYPE", "info_types", None, new={"name": name, "format": fmt_string})
                                session.execute(text("INSERT INTO info_types (dataset_id, info_name, type, format, \"update\") VALUES (:did, :n, :t, :f, :u)"),
                                                {"did": sel_ds_id, "n": name, "t": st.session_state["i_type_in"], "f": fmt_string, "u": st.session_state["i_upd_in"]})
                            session.commit(); clear_cache(); st.success("✅ Сохранено!"); st.rerun()
                        except Exception as e: 
                            st.error(f"Ошибка: {e}"); session.rollback()

            if is_editing_i:
                if st.button("🗑 Удалить вид сведений", type="secondary", width="stretch", key="info_del_btn"):
                    t_id = int(info_df[info_df["info_name"] == sel_i].iloc[0]["info_id"])
                    in_use = session.execute(text("SELECT 1 FROM project_items WHERE info_id = :id LIMIT 1"), {"id": t_id}).scalar()
                    if in_use: 
                        st.error("❌ Нельзя удалить: этот вид сведений уже добавлен в проекты!")
                    else:
                        try:
                            log_action(st.session_state["auth"]["user_id"], "DELETE_INFO_TYPE", "info_types", t_id, old={"name": sel_i})
                            session.execute(text("DELETE FROM info_types WHERE info_id = :id"), {"id": t_id})
                            session.commit(); clear_cache(); st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}"); session.rollback()