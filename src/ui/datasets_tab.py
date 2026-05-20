import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache

def render_datasets_tab(session, user_role="user"):
    st.subheader("📚 Справочники: Наборы и Виды сведений")
    is_readonly = (user_role == "user")

    # ==========================================
    # ЧАСТЬ 1: НАБОРЫ ДАННЫХ (Datasets)
    # ==========================================
    st.markdown("### 📦 Наборы данных")
    ds_df = query_db("SELECT dataset_id, dataset_name, is_mandatory, is_basic FROM datasets ORDER BY is_mandatory DESC, dataset_name")

    # 🔍 1. Фильтрация по is_mandatory
    show_mandatory_only = st.checkbox("Показывать только обязательные наборы", key="ds_mandatory_filter")
    display_ds = ds_df[ds_df["is_mandatory"]] if show_mandatory_only else ds_df

    st.dataframe(display_ds[["dataset_name", "is_mandatory", "is_basic"]], use_container_width=True, hide_index=True,
                 column_config={"dataset_name": "Название", "is_mandatory": "Обязательный", "is_basic": "Базовый"})

    # 🔽 2. Форма создания/редактирования (скрыта для user)
    if not is_readonly:
        with st.expander("➕ Добавить / ✏️ Редактировать набор"):
            with st.form("ds_form"):
                edit_options = ["(Создать новый)"] + display_ds["dataset_name"].tolist()
                sel_ds = st.selectbox("Выберите набор для редактирования:", edit_options)

                is_editing = sel_ds != "(Создать новый)"
                current_row = display_ds[display_ds["dataset_name"] == sel_ds].iloc[0] if is_editing else None

                ds_name = st.text_input("Название набора *", value=sel_ds if is_editing else "")
                ds_mandatory = st.checkbox("Обязательный набор (is_mandatory)", value=bool(current_row["is_mandatory"]) if is_editing else False)
                ds_basic = st.checkbox("Базовый набор (is_basic)", value=bool(current_row["is_basic"]) if is_editing else False)

                col_btn, col_del = st.columns([3, 1])
                with col_btn:
                    submit = st.form_submit_button("💾 Сохранить", type="primary")
                with col_del:
                    delete_btn = st.form_submit_button("🗑 Удалить", type="secondary") if is_editing else None

                if submit:
                    if not ds_name.strip():
                        st.error("❌ Название обязательно")
                    else:
                        try:
                            if not is_editing and ds_name.strip() in list(ds_df["dataset_name"]):
                                st.error("❌ Такой набор уже существует")
                            else:
                                if is_editing:
                                    session.execute(text("""
                                        UPDATE datasets SET dataset_name=:n, is_mandatory=:m, is_basic=:b 
                                        WHERE dataset_id=:id
                                    """), {"n": ds_name.strip(), "m": ds_mandatory, "b": ds_basic, "id": int(current_row["dataset_id"])})
                                else:
                                    session.execute(text("""
                                        INSERT INTO datasets (dataset_name, is_mandatory, is_basic) 
                                        VALUES (:n, :m, :b)
                                    """), {"n": ds_name.strip(), "m": ds_mandatory, "b": ds_basic})
                                session.commit()
                                clear_cache()
                                st.success("✅ Набор сохранён!")
                                st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ошибка БД: {e}")
                            session.rollback()

                if delete_btn:
                    cnt = session.execute(text("SELECT COUNT(*) FROM project_items WHERE dataset_id = :id"), {"id": int(current_row["dataset_id"])}).scalar()
                    if cnt > 0:
                        st.warning("⚠️ Набор уже используется в проектах. Удаление невозможно.")
                    else:
                        try:
                            session.execute(text("DELETE FROM datasets WHERE dataset_id = :id"), {"id": int(current_row["dataset_id"])})
                            session.commit()
                            clear_cache()
                            st.success("🗑 Набор удалён!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ошибка БД: {e}")
                            session.rollback()

    st.divider()

    # ==========================================
    # ЧАСТЬ 2: ВИДЫ СВЕДЕНИЙ (Info Types)
    # ==========================================
    st.markdown("### 📄 Виды сведений")
    datasets_list = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
    if datasets_list.empty:
        st.info("📭 Сначала создайте хотя бы один набор данных.")
        return

    ds_map = dict(zip(datasets_list["dataset_name"], datasets_list["dataset_id"]))
    sel_ds_name = st.selectbox("📦 Набор данных для просмотра видов:", list(ds_map.keys()), key="info_ds_filter")
    sel_ds_id = ds_map[sel_ds_name]

    # Справочники
    formats = query_db("SELECT format_name FROM ref_file_formats ORDER BY format_name")["format_name"].tolist()
    periods = query_db("SELECT period_name FROM ref_update_periods ORDER BY period_name")["period_name"].tolist()

    # 🔽 3. Запрос с агрегацией поставщиков через STRING_AGG
    info_query = """
        SELECT it.info_id, it.info_name, it.type, it.format, it."update",
               COALESCE(STRING_AGG(DISTINCT s.supplier_name, ', ' ORDER BY s.supplier_name), '') AS suppliers
        FROM info_types it
        LEFT JOIN project_items pi ON it.info_id = pi.info_id
        LEFT JOIN projects p ON pi.project_id = p.project_id
        LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
        WHERE it.dataset_id = :did
        GROUP BY it.info_id, it.info_name, it.type, it.format, it."update"
        ORDER BY it.info_name
    """
    info_df = query_db(info_query, {"did": sel_ds_id})

    st.dataframe(info_df[["info_name", "type", "format", "update", "suppliers"]], use_container_width=True, hide_index=True,
                 column_config={"info_name": "Название", "type": "Тип", "format": "Формат", 
                                "update": "Срок обновления", "suppliers": "Поставщики"})

    # 🔽 Форма создания/редактирования видов (скрыта для user)
    if not is_readonly:
        with st.expander("➕ Добавить / ✏️ Редактировать вид сведений"):
            with st.form("info_form"):
                edit_options = ["(Создать новый)"] + info_df["info_name"].tolist()
                sel_info = st.selectbox("Выберите вид для редактирования:", edit_options)

                is_editing = sel_info != "(Создать новый)"
                current_info = info_df[info_df["info_name"] == sel_info].iloc[0] if is_editing else None

                info_name = st.text_input("Название вида *", value=sel_info if is_editing else "")
                info_type = st.selectbox("Тип", ["Данные", "Сервис"],
                                         index=(["Данные", "Сервис"].index(current_info["type"]) if current_info["type"] in ["Данные", "Сервис"] else 0) if is_editing else 0)
                info_format = st.selectbox("Формат", formats,
                                           index=(formats.index(current_info["format"]) if current_info["format"] in formats else 0) if is_editing else 0)
                info_update = st.selectbox("Срок обновления", periods,
                                           index=(periods.index(current_info["update"]) if current_info["update"] in periods else 0) if is_editing else 0)

                col_btn, col_del = st.columns([3, 1])
                with col_btn:
                    submit_info = st.form_submit_button("💾 Сохранить", type="primary")
                with col_del:
                    delete_info_btn = st.form_submit_button("🗑 Удалить", type="secondary") if is_editing else None

                if submit_info:
                    if not info_name.strip():
                        st.error("❌ Название обязательно")
                    else:
                        try:
                            if is_editing:
                                session.execute(text("""
                                    UPDATE info_types SET info_name=:n, type=:t, format=:f, "update"=:u 
                                    WHERE info_id=:id
                                """), {"n": info_name.strip(), "t": info_type, "f": info_format, "u": info_update, "id": int(current_info["info_id"])})
                            else:
                                session.execute(text("""
                                    INSERT INTO info_types (dataset_id, info_name, type, format, "update") 
                                    VALUES (:did, :n, :t, :f, :u)
                                """), {"did": sel_ds_id, "n": info_name.strip(), "t": info_type, "f": info_format, "u": info_update})
                            session.commit()
                            clear_cache()
                            st.success("✅ Вид сведений сохранён!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ошибка БД: {e}")
                            session.rollback()

                if delete_info_btn:
                    try:
                        session.execute(text("DELETE FROM info_types WHERE info_id = :id"), {"id": int(current_info["info_id"])})
                        session.commit()
                        clear_cache()
                        st.success("🗑 Вид сведений удалён!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Ошибка БД: {e}")
                        session.rollback()