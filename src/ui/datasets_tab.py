import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache
from config.auth import log_action

def render_datasets_tab(session, user_role="user"):
    st.subheader("📚 Справочники данных")
    is_readonly = (user_role == "user")

    tab_ds, tab_info = st.tabs(["🗃️ Наборы данных", "📄 Виды сведений"])

    # ==========================================
    # ПОДВКЛАДКА 1: НАБОРЫ ДАННЫХ
    # ==========================================
    with tab_ds:
        ds_df = query_db("SELECT dataset_id, dataset_name, is_mandatory, is_basic FROM datasets ORDER BY is_mandatory DESC, dataset_name")

        # 1. Фильтры таблицы
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            show_mandatory = st.checkbox("Показывать только обязательные наборы", key="ds_filter_mand")
        with col_f2:
            show_optional = st.checkbox("Показывать только необязательные наборы", key="ds_filter_opt")
        
        # Применяем фильтрацию
        display_ds = ds_df.copy()
        if show_mandatory:
            display_ds = display_ds[display_ds["is_mandatory"] == True]
        if show_optional:
            display_ds = display_ds[display_ds["is_mandatory"] == False]

        # Отображение таблицы
        st.dataframe(display_ds[["dataset_name", "is_mandatory", "is_basic"]], 
                     width="stretch", hide_index=True,
                     column_config={
                         "dataset_name": "Название набора", 
                         "is_mandatory": "Обязательный", 
                         "is_basic": "Базовый"
                     })

        if not is_readonly:
            with st.expander("➕ Добавить / ✏️ Редактировать набор"):
                # 1. ВЫБОР (Вне формы для реактивности)
                edit_options = ["(Создать новый)"] + ds_df["dataset_name"].tolist()
                sel_ds = st.selectbox("Выберите набор для редактирования:", edit_options, key="ds_edit_selector")
                is_editing = sel_ds != "(Создать новый)"

                # Логика подтягивания данных в session_state
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

                # 2. ФОРМА СОХРАНЕНИЯ
                with st.form("ds_save_form"):
                    st.text_input("Название набора *", key="ds_name_in")
                    c1, c2 = st.columns(2)
                    with c1: st.checkbox("Обязательный (is_mandatory)", key="ds_mand_in")
                    with c2: st.checkbox("Базовый (is_basic)", key="ds_basic_in")
                    
                    if st.form_submit_button("💾 Сохранить изменения", width="stretch"):
                        new_name = st.session_state["ds_name_in"].strip()
                        if not new_name:
                            st.error("❌ Название обязательно")
                        else:
                            try:
                                if is_editing:
                                    target_id = int(ds_df[ds_df["dataset_name"] == sel_ds].iloc[0]["dataset_id"])
                                    session.execute(text("UPDATE datasets SET dataset_name=:n, is_mandatory=:m, is_basic=:b WHERE dataset_id=:id"),
                                                    {"n": new_name, "m": st.session_state["ds_mand_in"], "b": st.session_state["ds_basic_in"], "id": target_id})
                                else:
                                    session.execute(text("INSERT INTO datasets (dataset_name, is_mandatory, is_basic) VALUES (:n, :m, :b)"),
                                                    {"n": new_name, "m": st.session_state["ds_mand_in"], "b": st.session_state["ds_basic_in"]})
                                session.commit(); clear_cache(); st.success("✅ Сохранено!"); st.rerun()
                            except Exception as e:
                                st.error(f"Ошибка: {e}"); session.rollback()

                # 3. КНОПКА УДАЛЕНИЯ (Вне формы)
                if is_editing:
                    if st.button("🗑 Удалить набор", type="secondary", width="stretch", key="ds_del_btn"):
                        target_id = int(ds_df[ds_df["dataset_name"] == sel_ds].iloc[0]["dataset_id"])
                        
                        # 🛡️ ПРОВЕРКА 1: Есть ли в этом наборе виды сведений?
                        has_info_types = session.execute(text("SELECT 1 FROM info_types WHERE dataset_id = :id LIMIT 1"), {"id": target_id}).scalar()
                        
                        # 🛡️ ПРОВЕРКА 2: Используется ли набор в проектах?
                        in_use = session.execute(text("SELECT 1 FROM project_items WHERE dataset_id = :id LIMIT 1"), {"id": target_id}).scalar()
                        
                        if has_info_types:
                            st.error("❌ Нельзя удалить набор: в нем созданы виды сведений. Сначала удалите их на вкладке «Виды сведений».")
                        elif in_use:
                            st.error("❌ Нельзя удалить: набор используется в проектах!")
                        else:
                            try:
                                session.execute(text("DELETE FROM datasets WHERE dataset_id = :id"), {"id": target_id})
                                session.commit()
                                clear_cache()
                                st.success("🗑 Набор удалён")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Ошибка при удалении: {e}")
                                session.rollback()

    # ==========================================
    # ПОДВКЛАДКА 2: ВИДЫ СВЕДЕНИЙ
    # ==========================================
    with tab_info:
        datasets_list = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
        if not datasets_list.empty:
            ds_map = dict(zip(datasets_list["dataset_name"], datasets_list["dataset_id"]))
            sel_ds_name = st.selectbox("📦 Набор данных:", list(ds_map.keys()), key="info_tab_ds_sel")
            sel_ds_id = ds_map[sel_ds_name]

            formats = query_db("SELECT format_name FROM ref_file_formats ORDER BY format_name")["format_name"].tolist()
            periods = query_db("SELECT period_name FROM ref_update_periods ORDER BY period_name")["period_name"].tolist()

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

            st.dataframe(info_df[["info_name", "type", "format", "update", "suppliers"]], width="stretch", hide_index=True)

            if not is_readonly:
                with st.expander("➕ Добавить / ✏️ Редактировать вид"):
                    # 1. ВЫБОР (Вне формы)
                    edit_opts_i = ["(Создать новый)"] + info_df["info_name"].tolist()
                    sel_i = st.selectbox("Выберите вид:", edit_opts_i, key="info_edit_selector")
                    is_editing_i = sel_i != "(Создать новый)"

                    if st.session_state.get("info_prev_sel") != sel_i:
                        if is_editing_i:
                            curr = info_df[info_df["info_name"] == sel_i].iloc[0]
                            st.session_state["i_name_in"] = curr["info_name"]
                            st.session_state["i_type_in"] = curr["type"] if curr["type"] in ["Данные", "Сервис"] else "Данные"
                            st.session_state["i_format_in"] = curr["format"] if curr["format"] in formats else formats[0]
                            st.session_state["i_upd_in"] = curr["update"] if curr["update"] in periods else periods[0]
                        else:
                            st.session_state["i_name_in"] = ""
                            st.session_state["i_type_in"] = "Данные"
                        st.session_state["info_prev_sel"] = sel_i

                    # 2. ФОРМА
                    with st.form("info_save_form"):
                        st.text_input("Название вида *", key="i_name_in")
                        c1, c2, c3 = st.columns(3)
                        with c1: st.selectbox("Тип", ["Данные", "Сервис"], key="i_type_in")
                        with c2: st.selectbox("Формат", formats, key="i_format_in")
                        with c3: st.selectbox("Срок обновления", periods, key="i_upd_in")
                        
                        if st.form_submit_button("💾 Сохранить вид", width="stretch"):
                            name = st.session_state["i_name_in"].strip()
                            if name:
                                try:
                                    if is_editing_i:
                                        t_id = int(info_df[info_df["info_name"] == sel_i].iloc[0]["info_id"])
                                        session.execute(text("UPDATE info_types SET info_name=:n, type=:t, format=:f, \"update\"=:u WHERE info_id=:id"),
                                                        {"n": name, "t": st.session_state["i_type_in"], "f": st.session_state["i_format_in"], "u": st.session_state["i_upd_in"], "id": t_id})
                                    else:
                                        session.execute(text("INSERT INTO info_types (dataset_id, info_name, type, format, \"update\") VALUES (:did, :n, :t, :f, :u)"),
                                                        {"did": sel_ds_id, "n": name, "t": st.session_state["i_type_in"], "f": st.session_state["i_format_in"], "u": st.session_state["i_upd_in"]})
                                    session.commit(); clear_cache(); st.rerun()
                                except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

                    # 3. УДАЛЕНИЕ
                    if is_editing_i:
                        if st.button("🗑 Удалить вид сведений", type="secondary", width="stretch", key="info_del_btn"):
                            t_id = int(info_df[info_df["info_name"] == sel_i].iloc[0]["info_id"])
                            in_use = session.execute(text("SELECT 1 FROM project_items WHERE info_id = :id LIMIT 1"), {"id": t_id}).scalar()
                            if in_use: st.error("❌ Используется в проектах!")
                            else:
                                session.execute(text("DELETE FROM info_types WHERE info_id = :id"), {"id": t_id})
                                session.commit(); clear_cache(); st.rerun()