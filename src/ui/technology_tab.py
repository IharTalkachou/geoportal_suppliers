import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache
from config.auth import log_action

def render_technology_tab(session, project_id, user_role="user"):
    st.subheader("⚙️ Технология (Этапы по наборам)")
    st.caption("⚙️ Итерация и плановые даты считаются автоматически. Факт. начало закрывает предыдущий этап.")
    
    is_readonly = (user_role == "user")

    # 🔍 1. Загружаем ТОЛЬКО состав текущего проекта для фильтров
    project_items = query_db("""
        SELECT pi.item_id, d.dataset_name, i.info_name
        FROM project_items pi
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        WHERE pi.project_id = :pid
        ORDER BY d.dataset_name, i.info_name
    """, {"pid": project_id})

    if project_items.empty:
        st.info("📭 В составе этого проекта пока нет наборов данных. Добавьте их в блоке «Состав проекта» выше.")
        return

    available_datasets = sorted(project_items["dataset_name"].dropna().unique().tolist())
    selected_ds = st.selectbox("🔍 Набор данных", [""] + available_datasets, key="tech_ds_sel")

    available_infos = []
    if selected_ds:
        available_infos = sorted(
            project_items[project_items["dataset_name"] == selected_ds]["info_name"].dropna().unique().tolist()
        )
    selected_info = st.selectbox("🔍 Вид сведений", [""] + available_infos, key="tech_info_sel")

    if selected_ds and selected_info:
        item_record = project_items[(project_items["dataset_name"] == selected_ds) & (project_items["info_name"] == selected_info)]
        if not item_record.empty:
            selected_item_id = int(item_record.iloc[0]["item_id"])
        else:
            st.warning("⚠️ Связка не найдена."); return
    else:
        st.info("👆 Выберите Набор и Вид сведений из состава проекта."); return

    # 📖 Справочник этапов (только технологический трек)
    stages = query_db("""
        SELECT stage_id, stage_name, stage_type, duration_days, stage_order
        FROM stages WHERE track_category = '2. Технологический' ORDER BY stage_order
    """)
    micro_statuses = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses ORDER BY micro_status_id")

    stage_map = {
        row["stage_name"]: {
            "id": row["stage_id"], "type": row["stage_type"],
            "duration": int(row["duration_days"] or 0), "order": row["stage_order"]
        } for _, row in stages.iterrows()
    }
    micro_map = dict(zip(micro_statuses["micro_status_name"], micro_statuses["micro_status_id"]))
    completed_status_id = micro_map.get("Выполнено")

    # 🛡 ЗАЩИТА: Если справочники пусты, блокируем отрисовку вкладки
    if not stage_map or not micro_map:
        st.warning("⚠️ Справочники этапов или микростатусов не заполнены. Добавьте их в админ-панели.")
        return

    # 📊 Текущие этапы для выбранного набора
    stages_df = query_db("""
        SELECT ist.stage_progress_id, s.stage_name, ms.micro_status_name,
               ist.iteration_count, ist.planned_start, ist.planned_end,
               ist.actual_start, ist.actual_end, ist.comments,
               u.display_name as responsible_name,
               ist.responsible_id          
        FROM item_stages ist
        JOIN stages s ON ist.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id
        LEFT JOIN users u ON ist.responsible_id = u.user_id
        WHERE ist.item_id = :iid
        ORDER BY s.stage_order, ist.iteration_count
    """, {"iid": selected_item_id})

    # 👥 Загружаем список сотрудников для выбора
    staff_df = query_db("SELECT user_id, display_name FROM users WHERE show_in_staff = TRUE AND is_active = TRUE ORDER BY display_name")
    staff_map = dict(zip(staff_df["display_name"], staff_df["user_id"]))
    staff_options = ["Не назначен"] + list(staff_map.keys())

    cols_to_show = [
        "stage_name", "micro_status_name", "responsible_name", 
        "iteration_count", "planned_start", "planned_end", 
        "actual_start", "actual_end", "comments"
    ]

    # 🔐 Таблица ВСЕГДА в режиме просмотра
    st.dataframe(stages_df[cols_to_show], 
                 width='stretch', hide_index=True,
                 column_config={
                     "stage_name": "Этап", 
                     "micro_status_name": "Микростатус",
                     "responsible_name": "Ответственный", # ⬅️ Красивый заголовок
                     "iteration_count": st.column_config.NumberColumn("Ит.", format="%d"),
                     "planned_start": "План. начало", 
                     "planned_end": "План. конец",
                     "actual_start": "Факт. начало", 
                     "actual_end": "Факт. окончание", 
                     "comments": "Комментарий"
                 })
    
    if is_readonly:
        return

    # 🛠 Вспомогательная функция для безопасного извлечения дат (защита от Pandas NaT)
    def get_safe_date(val):
        if pd.isna(val) or val is None:
            return None
        if hasattr(val, 'date'):
            return val.date()
        return val

    # 🔽 Реактивный CRUD
    with st.expander("➕ Добавить / ✏️ Редактировать этап"):
        item_options = ["(Добавить новый)"]
        item_ids_map = {}
        for _, row in stages_df.iterrows():
            label = f"{row['stage_name']} (Ит. {int(row['iteration_count'])})"
            item_options.append(label)
            item_ids_map[label] = row["stage_progress_id"]

        sel_item = st.selectbox("Выберите этап:", item_options, key="tech_sel")
        is_editing = sel_item != "(Добавить новый)"

        # 🔍 РЕАКТИВНОЕ ОБНОВЛЕНИЕ: Перезаписываем ключи самих виджетов при смене выбора
        if st.session_state.get("tech_sel_prev") != sel_item:
            if is_editing:
                curr = stages_df[stages_df["stage_progress_id"] == item_ids_map[sel_item]].iloc[0]
                
                st.session_state["tech_stage_in"] = curr["stage_name"]
                st.session_state["tech_status_in"] = curr["micro_status_name"]
                st.session_state["tech_iter_in"] = int(curr["iteration_count"]) if pd.notna(curr["iteration_count"]) else 1
                st.session_state["tech_p_start_in"] = get_safe_date(curr["planned_start"])
                st.session_state["tech_a_start_in"] = get_safe_date(curr["actual_start"])
                st.session_state["tech_a_end_in"] = get_safe_date(curr["actual_end"])
                st.session_state["tech_comments_in"] = curr["comments"] if pd.notna(curr["comments"]) else ""
                
                # 👤 Логика ответственного
                resp_id = curr.get("responsible_id")
                resp_name = "Не назначен"
                if pd.notna(resp_id):
                    matching_staff = staff_df[staff_df["user_id"] == int(resp_id)]
                    if not matching_staff.empty:
                        resp_name = matching_staff.iloc[0]["display_name"]
                
                st.session_state["tech_resp_in"] = resp_name
            else:
                # Сброс для нового этапа
                st.session_state["tech_stage_in"] = list(stage_map.keys())[0] if stage_map else None
                st.session_state["tech_status_in"] = list(micro_map.keys())[0] if micro_map else None
                st.session_state["tech_iter_in"] = 1
                st.session_state["tech_p_start_in"] = None
                st.session_state["tech_a_start_in"] = None
                st.session_state["tech_a_end_in"] = None
                st.session_state["tech_comments_in"] = ""
                st.session_state["tech_resp_in"] = "Не назначен"

            st.session_state["tech_sel_prev"] = sel_item

        col1, col2 = st.columns(2)
        with col1:
            stage_name = st.selectbox("Этап", list(stage_map.keys()), key="tech_stage_in")
            micro_status = st.selectbox("Микростатус", list(micro_map.keys()), key="tech_status_in")
            #st.number_input("🔒 Итерация", disabled=True, key="tech_iter_in")
            sel_resp = st.selectbox("👤 Ответственный за этап", staff_options, key="tech_resp_in")

        with col2:
            p_start = st.date_input("План. начало", value=None, key="tech_p_start_in")
            a_start = st.date_input("Факт. начало", value=None, key="tech_a_start_in")
            stage_type = stage_map[stage_name]["type"]
            a_end = st.date_input("Факт. окончание", value=None, disabled=(stage_type == "Веха"), key="tech_a_end_in")

        comments = st.text_area("Комментарий", key="tech_comments_in")

        # Чекбокс авто-закрытия (показываем только при добавлении нового этапа)
        auto_close_prev = False
        if not is_editing:
            auto_close_prev = st.checkbox("☑️ Автоматически закрыть предыдущий открытый этап текущей датой", 
                                          value=True,
                                          key='tech_auto_close')

        col_btn, col_del = st.columns([3, 1])
        with col_btn:
            if st.button("💾 Сохранить", type="primary", key="tech_save"):
                stage_info = stage_map[stage_name]
                micro_id = micro_map[micro_status]
                r_id = staff_map.get(sel_resp) if sel_resp != "Не назначен" else None

                # 🛡 ЗАЩИТА ЛОГИКИ ВЕХ И ДАТ
                if stage_info["type"] == "Веха":
                    p_end = p_start
                    a_end = a_start
                else:
                    p_end = p_start + timedelta(days=stage_info["duration"]) if p_start else None

                iter_val = int(st.session_state["tech_iter_in"]) if is_editing else (
                    session.execute(text("SELECT COALESCE(MAX(iteration_count), 0) FROM item_stages WHERE item_id = :iid AND stage_id = :sid"), 
                                    {"iid": selected_item_id, "sid": stage_info["id"]}).scalar() + 1
                )

                # 🎯 Авто-закрытие предыдущего этапа (с учетом чекбокса)
                if not is_editing and auto_close_prev and a_start is not None and completed_status_id is not None:
                    session.execute(text("""
                        UPDATE item_stages SET actual_end = :close_date, micro_status = :completed_id
                        WHERE stage_progress_id = (
                            SELECT ist.stage_progress_id FROM item_stages ist
                            WHERE ist.item_id = :iid AND ist.actual_end IS NULL
                            ORDER BY (SELECT s.stage_order FROM stages s WHERE s.stage_id = ist.stage_id) DESC, ist.iteration_count DESC
                            LIMIT 1
                        )
                    """), {"close_date": a_start, "completed_id": completed_status_id, "iid": selected_item_id})

                try:
                    if is_editing:
                        # ДОСТАЕМ ТЕКУЩИЕ ДАННЫЕ ДЛЯ ЛОГА
                        curr = stages_df[stages_df["stage_progress_id"] == item_ids_map[sel_item]].iloc[0]
                        
                        session.execute(text("""
                            UPDATE item_stages SET stage_id=:sid, micro_status=:mst, iteration_count=:iter,
                                planned_start=:ps, planned_end=:pe, actual_start=:as, actual_end=:ae, comments=:comm, responsible_id=:rid
                            WHERE stage_progress_id=:id
                        """), {"sid": stage_info["id"], "mst": micro_id, "iter": iter_val,
                               "ps": p_start, "pe": p_end, "as": a_start, "ae": a_end, "comm": comments,
                               "id": int(item_ids_map[sel_item]), "rid": r_id})
                        
                        # 🚨 ИСПРАВЛЕНА ТАБЛИЦА: item_stages вместо project_stages
                        log_action(st.session_state["auth"]["user_id"], "UPDATE_STAGE", "item_stages", int(item_ids_map[sel_item]),
                            old={"status": curr["micro_status_name"], "a_start": curr["actual_start"]},
                            new={"status": micro_status, "a_start": a_start})
                    else:
                        session.execute(text("""
                            INSERT INTO item_stages (item_id, stage_id, micro_status, iteration_count,
                                planned_start, planned_end, actual_start, actual_end, comments, responsible_id)
                            VALUES (:iid, :sid, :mst, :iter, :ps, :pe, :as, :ae, :comm, :rid)
                        """), {"iid": selected_item_id, "sid": stage_info["id"], "mst": micro_id, "iter": iter_val,
                               "ps": p_start, "pe": p_end, "as": a_start, "ae": a_end, "comm": comments, "rid": r_id})
                        
                        # 🚨 ИСПРАВЛЕНА ТАБЛИЦА: item_stages
                        log_action(st.session_state["auth"]["user_id"], "CREATE_STAGE", "item_stages",
                            new={"stage": stage_name, "status": micro_status, "iteration": iter_val})
                    
                    session.commit(); clear_cache()
                    st.success("✅ Этап набора сохранён!"); st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка БД: {e}"); session.rollback()

        with col_del:
            if is_editing and st.button("🗑 Удалить", type="secondary", key="tech_del"):
                try:
                    # ДОСТАЕМ ТЕКУЩИЕ ДАННЫЕ ДЛЯ ЛОГА
                    curr = stages_df[stages_df["stage_progress_id"] == item_ids_map[sel_item]].iloc[0]
                    
                    # 🚨 ИСПРАВЛЕНА ТАБЛИЦА: item_stages
                    log_action(st.session_state["auth"]["user_id"], "DELETE_STAGE", "item_stages", int(item_ids_map[sel_item]),
                        old={"stage": curr["stage_name"], "status": curr["micro_status_name"]})
                    
                    session.execute(text("DELETE FROM item_stages WHERE stage_progress_id = :id"), {"id": int(item_ids_map[sel_item])})
                    session.commit(); clear_cache()
                    st.success("🗑 Этап удалён!"); st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка БД: {e}"); session.rollback()