import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache
from config.auth import log_action

def render_bureaucracy_tab(session, project_id, user_role="user"):
    st.subheader("📜 Бюрократия (Документарные этапы)")
    st.caption("⚙️ Итерация и плановые даты считаются автоматически. Факт. начало закрывает предыдущий этап.")
    
    is_readonly = (user_role == "user")

    # 📖 Справочник этапов
    stages = query_db("""
        SELECT stage_id, stage_name, stage_type, duration_days, stage_order
        FROM stages WHERE track_category = '1. Документарный' ORDER BY stage_order
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
    
    # 📊 Текущие этапы проекта
    ps_df = query_db("""
        SELECT ps.stage_progress_id, s.stage_name, ms.micro_status_name,
               ps.iteration_count, ps.planned_start, ps.planned_end,
               ps.actual_start, ps.actual_end, ps.comments
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE ps.project_id = :pid
        ORDER BY s.stage_order, ps.iteration_count
    """, {"pid": project_id})

    # 🔐 Таблица ВСЕГДА в режиме просмотра
    st.dataframe(ps_df[["stage_name", "micro_status_name", "iteration_count", "planned_start", "planned_end", "actual_start", "actual_end", "comments"]], 
                 width="stretch", hide_index=True,
                 column_config={
                     "stage_name": "Этап", "micro_status_name": "Микростатус",
                     "iteration_count": st.column_config.NumberColumn("Итерация", format="%d"),
                     "planned_start": "План. начало", "planned_end": "План. конец",
                     "actual_start": "Факт. начало", "actual_end": "Факт. окончание", "comments": "Комментарий"
                 })
    
    if is_readonly:
        return

    # 🔽 Реактивный CRUD (без st.form)
    with st.expander("➕ Добавить / ✏️ Редактировать этап"):
        # 1. Выбор существующего или нового
        item_options = ["(Добавить новый)"]
        item_ids_map = {}
        for _, row in ps_df.iterrows():
            label = f"{row['stage_name']} (Ит. {int(row['iteration_count'])})"
            item_options.append(label)
            item_ids_map[label] = row["stage_progress_id"]

        sel_item = st.selectbox("Выберите этап:", item_options, key="buro_sel")
        is_editing = sel_item != "(Добавить новый)"

        # 🛠 Вспомогательная функция для безопасного извлечения дат (защита от Pandas NaT)
        def get_safe_date(val):
            if pd.isna(val) or val is None:
                return None
            if hasattr(val, 'date'):
                return val.date()
            return val

        # 🔍 РЕАКТИВНОЕ ОБНОВЛЕНИЕ: Перезаписываем ключи самих виджетов при смене выбора
        if st.session_state.get("buro_sel_prev") != sel_item:
            if is_editing:
                curr = ps_df[ps_df["stage_progress_id"] == item_ids_map[sel_item]].iloc[0]
                # Пишем напрямую в ключи с суффиксом _in (как у самих виджетов)
                st.session_state["buro_stage_in"] = curr["stage_name"]
                st.session_state["buro_status_in"] = curr["micro_status_name"]
                st.session_state["buro_iter_in"] = int(curr["iteration_count"]) if pd.notna(curr["iteration_count"]) else 1
                st.session_state["buro_p_start_in"] = get_safe_date(curr["planned_start"])
                st.session_state["buro_a_start_in"] = get_safe_date(curr["actual_start"])
                st.session_state["buro_a_end_in"] = get_safe_date(curr["actual_end"])
                st.session_state["buro_comments_in"] = curr["comments"] if pd.notna(curr["comments"]) else ""
            else:
                # Безопасный дефолт, если выбираем "(Добавить новый)"
                default_stage = list(stage_map.keys())[0] if stage_map else None
                default_status = list(micro_map.keys())[0] if micro_map else None
                
                st.session_state["buro_stage_in"] = default_stage
                st.session_state["buro_status_in"] = default_status
                st.session_state["buro_iter_in"] = 1
                st.session_state["buro_p_start_in"] = None
                st.session_state["buro_a_start_in"] = None
                st.session_state["buro_a_end_in"] = None
                st.session_state["buro_comments_in"] = ""
                
            st.session_state["buro_sel_prev"] = sel_item

        # 2. Поля ввода
        col1, col2 = st.columns(2)
        with col1:
            # Убраны index=..., так как Streamlit сам возьмет нужные значения из ключей (key)
            stage_name = st.selectbox("Этап", list(stage_map.keys()), key="buro_stage_in")
            micro_status = st.selectbox("Микростатус", list(micro_map.keys()), key="buro_status_in")
            st.number_input("🔒 Итерация", disabled=True, key="buro_iter_in")

        with col2:
            # Оставлен value=None как "запасной парашют", чтобы по умолчанию не ставилась "сегодняшняя" дата
            p_start = st.date_input("План. начало", value=None, key="buro_p_start_in")
            a_start = st.date_input("Факт. начало", value=None, key="buro_a_start_in")
            
            stage_type = stage_map.get(stage_name, {}).get("type", "")
            a_end = st.date_input("Факт. окончание", value=None, disabled=(stage_type == "Веха"), key="buro_a_end_in")

        comments = st.text_area("Комментарий", key="buro_comments_in")

        # Чекбокс авто-закрытия (показываем только при добавлении нового этапа)
        auto_close_prev = False
        if not is_editing:
            auto_close_prev = st.checkbox("☑️ Автоматически закрыть предыдущий открытый этап текущей датой", 
                                          value=True,
                                          key="buro_auto_close")
            
        # 3. Кнопки действий
        col_btn, col_del = st.columns([3, 1])
        with col_btn:
            if st.button("💾 Сохранить", type="primary", key="buro_save"):
                stage_info = stage_map[stage_name]
                micro_id = micro_map[micro_status]

                # 1. Расчёт итерации
                if is_editing:
                    # Если редактируем, берем значение из заблокированного поля ввода
                    iter_val = int(st.session_state["buro_iter_in"])
                else:
                    # Если новый, считаем MAX + 1 из базы
                    iter_val = session.execute(text("""
                        SELECT COALESCE(MAX(iteration_count), 0) + 1 
                        FROM project_stages 
                        WHERE project_id = :pid AND stage_id = :sid
                    """), {"pid": project_id, "sid": stage_info["id"]}).scalar()

                # 2. Логика дат (как мы правили ранее)
                if stage_info["type"] == "Веха":
                    p_end = p_start
                    a_end = a_start
                else:
                    p_end = p_start + timedelta(days=stage_info["duration"]) if p_start else None

                # 3. Сама вставка/обновление
                try:
                    if is_editing:
                        # Достаем curr для лога
                        curr = ps_df[ps_df["stage_progress_id"] == item_ids_map[sel_item]].iloc[0]
                        
                        session.execute(text("""
                            UPDATE project_stages SET stage_id=:sid, micro_status=:mst, iteration_count=:iter,
                                planned_start=:ps, planned_end=:pe, actual_start=:as, actual_end=:ae, comments=:comm
                            WHERE stage_progress_id=:id
                        """), {"sid": stage_info["id"], "mst": micro_id, "iter": iter_val,
                            "ps": p_start, "pe": p_end, "as": a_start, "ae": a_end, "comm": comments,
                            "id": int(item_ids_map[sel_item])})
                    else:
                        session.execute(text("""
                            INSERT INTO project_stages (project_id, stage_id, micro_status, iteration_count,
                                planned_start, planned_end, actual_start, actual_end, comments)
                            VALUES (:pid, :sid, :mst, :iter, :ps, :pe, :as, :ae, :comm)
                        """), {"pid": project_id, "sid": stage_info["id"], "mst": micro_id, "iter": iter_val,
                               "ps": p_start, "pe": p_end, "as": a_start, "ae": a_end, "comm": comments})
                        log_action(st.session_state["auth"]["user_id"], "CREATE_STAGE", "project_stages",
                            new={"stage": stage_name, "status": micro_status, "iteration": iter_val})
                    
                    session.commit(); clear_cache()
                    st.success("✅ Этап сохранён!"); st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка БД: {e}"); session.rollback()

        with col_del:
            if is_editing and st.button("🗑 Удалить", type="secondary", key="buro_del"):
                try:
                    # 👈 ДОБАВЛЯЕМ ЭТУ СТРОКУ (Достаем текущие значения для лога)
                    curr = ps_df[ps_df["stage_progress_id"] == item_ids_map[sel_item]].iloc[0]

                    log_action(st.session_state["auth"]["user_id"], "DELETE_STAGE", "project_stages", int(item_ids_map[sel_item]),
                        old={"stage": curr["stage_name"], "status": curr["micro_status_name"]})
                    
                    session.execute(text("DELETE FROM project_stages WHERE stage_progress_id = :id"), {"id": int(item_ids_map[sel_item])})
                    session.commit(); clear_cache()
                    st.success("🗑 Этап удалён!"); st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка БД: {e}"); session.rollback()