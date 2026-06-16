import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache
from config.auth import log_action

def render_technology_tab(session, project_id, user_role="user"):
    st.subheader("⚙️ Технология (Этапы по наборам)")
    is_readonly = (user_role == "user")

    # 1. ЗАГРУЗКА СОСТАВА ПРОЕКТА ДЛЯ ФИЛЬТРОВ
    project_items = query_db("""
        SELECT pi.item_id, d.dataset_name, i.info_name
        FROM project_items pi
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        WHERE pi.project_id = :pid
        ORDER BY d.dataset_name, i.info_name
    """, {"pid": project_id})

    if project_items.empty:
        st.info("📭 В составе проекта нет наборов данных. Добавьте их в «Составе проекта».")
        return

    # Селекторы набора и вида
    available_datasets = sorted(project_items["dataset_name"].dropna().unique().tolist())
    selected_ds = st.selectbox("🔍 Набор данных", [""] + available_datasets, key="tech_ds_sel")

    available_infos = []
    if selected_ds:
        available_infos = sorted(
            project_items[project_items["dataset_name"] == selected_ds]["info_name"].dropna().unique().tolist()
        )
    selected_info = st.selectbox("🔍 Вид сведений", [""] + available_infos, key="tech_info_sel")

    if not (selected_ds and selected_info):
        st.info("👆 Выберите Набор и Вид сведений для управления этапами.")
        return

    # Получаем ID связи
    item_record = project_items[(project_items["dataset_name"] == selected_ds) & (project_items["info_name"] == selected_info)]
    selected_item_id = int(item_record.iloc[0]["item_id"])

    # 2. ЗАГРУЗКА СПРАВОЧНИКОВ
    stages = query_db("""
        SELECT stage_id, stage_name, stage_type, duration_days, stage_order
        FROM stages WHERE track_category = '2. Технологический' ORDER BY stage_order
    """)
    micro_statuses = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses ORDER BY micro_status_id")

    stage_map = {
        row["stage_name"]: {
            "id": int(row["stage_id"]), "type": row["stage_type"],
            "duration": int(row["duration_days"] or 0), "order": row["stage_order"]
        } for _, row in stages.iterrows()
    }
    micro_map = {name: int(mid) for name, mid in zip(micro_statuses["micro_status_name"], micro_statuses["micro_status_id"])}

    if not stage_map or not micro_map:
        st.warning("⚠️ Справочники пусты.")
        return

    # 3. ЗАГРУЗКА ДАННЫХ (Умная сортировка)
    stages_df = query_db("""
        SELECT ist.stage_progress_id, s.stage_name, ms.micro_status_name,
               ist.iteration_count, ist.planned_start, ist.planned_end,
               ist.actual_start, ist.actual_end, ist.comments,
               u.display_name as responsible_name, ist.responsible_id          
        FROM item_stages ist
        JOIN stages s ON ist.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id
        LEFT JOIN users u ON ist.responsible_id = u.user_id
        WHERE ist.item_id = :iid
        ORDER BY COALESCE(ist.actual_start, ist.planned_start) ASC, s.stage_order ASC
    """, {"iid": selected_item_id})

    # Таблица просмотра
    st.dataframe(
        stages_df[["stage_name", "micro_status_name", "responsible_name", "iteration_count", "planned_start", "planned_end", "actual_start", "actual_end", "comments"]], 
        width='stretch', hide_index=True,
        column_config={
            "stage_name": "Этап", "micro_status_name": "Статус",
            "iteration_count": st.column_config.NumberColumn("Ит.", format="%d"),
            "planned_start": st.column_config.DateColumn("План. начало", format="DD.MM.YYYY"),
            "planned_end": st.column_config.DateColumn("Дедлайн", format="DD.MM.YYYY"),
            "actual_start": st.column_config.DateColumn("Факт. начало", format="DD.MM.YYYY"),
            "actual_end": st.column_config.DateColumn("Факт. конец", format="DD.MM.YYYY")
        }
    )
    
    if is_readonly: return

    # ==========================================
    # Вспомогательные функции расчёта
    # ==========================================
    def calculate_norm_end(s_name, start_date):
        if not s_name or not start_date: return None
        duration = stage_map.get(s_name, {}).get("duration", 0)
        return start_date + timedelta(days=duration)

    def sync_planned_end():
        if st.session_state.get("tech_manual_date"): return
        base_date = st.session_state.get("tech_a_start_in") or st.session_state.get("tech_p_start_in")
        st.session_state["tech_p_end_in"] = calculate_norm_end(st.session_state.get("tech_stage_in"), base_date)

    def on_toggle_manual():
        if not st.session_state.get("tech_manual_date"): sync_planned_end()

    # ==========================================
    # SMART CRUD
    # ==========================================
    with st.expander("➕ Добавить / ✏️ Редактировать этап", expanded=stages_df.empty):
        item_options = ["(Добавить новый)"]
        item_ids_map = {f"{r['stage_name']} (Ит. {int(r['iteration_count'])})": int(r["stage_progress_id"]) for _, r in stages_df.iterrows()}
        item_options += list(item_ids_map.keys())

        sel_item = st.selectbox("Выберите этап:", item_options, key="tech_sel")
        is_editing = sel_item != "(Добавить новый)"

        # РЕАКТИВНАЯ ЗАГРУЗКА
        if st.session_state.get("tech_sel_prev") != sel_item:
            if is_editing:
                curr = stages_df[stages_df["stage_progress_id"] == item_ids_map[sel_item]].iloc[0]
                st.session_state["tech_stage_in"] = curr["stage_name"]
                st.session_state["tech_status_in"] = curr["micro_status_name"]
                st.session_state["tech_p_start_in"] = curr["planned_start"]
                st.session_state["tech_p_end_in"] = curr["planned_end"]
                st.session_state["tech_a_start_in"] = curr["actual_start"]
                st.session_state["tech_a_end_in"] = curr["actual_end"]
                st.session_state["tech_comments_in"] = curr["comments"] or ""
                st.session_state["tech_iter_in"] = int(curr["iteration_count"])
                
                # Логика определения ручного ввода
                base = curr["actual_start"] or curr["planned_start"]
                norm_date = calculate_norm_end(curr["stage_name"], base)
                st.session_state["tech_manual_date"] = (curr["planned_end"] != norm_date)
                
                resp_id = curr.get("responsible_id")
                if pd.notna(resp_id):
                    r_name = query_db("SELECT display_name FROM users WHERE user_id=:u", {"u": int(resp_id)}).iloc[0]["display_name"]
                    st.session_state["tech_resp_in"] = r_name
                else: st.session_state["tech_resp_in"] = "Не назначен"
            else:
                st.session_state["tech_stage_in"] = list(stage_map.keys())[0]
                st.session_state["tech_status_in"] = "Планируется"
                st.session_state["tech_p_start_in"] = date.today()
                st.session_state["tech_p_end_in"] = calculate_norm_end(st.session_state["tech_stage_in"], date.today())
                st.session_state["tech_a_start_in"], st.session_state["tech_a_end_in"] = None, None
                st.session_state["tech_comments_in"], st.session_state["tech_resp_in"] = "", "Не назначен"
                st.session_state["tech_manual_date"] = False
            
            st.session_state["tech_sel_prev"] = sel_item

        # ИНТЕРФЕЙС
        col1, col2 = st.columns(2)
        with col1:
            st.selectbox("Этап *", list(stage_map.keys()), key="tech_stage_in", on_change=sync_planned_end)
            st.selectbox("Микростатус", list(micro_map.keys()), key="tech_status_in")
            staff = ["Не назначен"] + sorted(query_db("SELECT display_name FROM users WHERE show_in_staff=True AND is_active=True")["display_name"].tolist())
            st.selectbox("👤 Ответственный", staff, key="tech_resp_in")

        with col2:
            st.date_input("🗓️ Плановое начало", key="tech_p_start_in", on_change=sync_planned_end)
            c_date, c_lock = st.columns([0.7, 0.3])
            with c_lock:
                st.write("<br>", unsafe_allow_html=True)
                st.toggle("✏️ Вручную", key="tech_manual_date", on_change=on_toggle_manual)
            with c_date:
                st.date_input("🎯 План. завершение (Дедлайн)", key="tech_p_end_in", disabled=not st.session_state.tech_manual_date)
            
            st.divider()
            st.date_input("🚀 Фактическое начало", key="tech_a_start_in", value=None, on_change=sync_planned_end)
            st.date_input("🏁 Фактическое окончание", key="tech_a_end_in", value=None)

        st.text_area("Комментарий", key="tech_comments_in")
        if not is_editing:
            st.checkbox("☑️ Закрыть предыдущий этап этого набора", value=True, key="tech_auto_close")
            # ЧЕКБОКС ДЛЯ МАССОВОГО КОПИРОВАНИЯ
            st.checkbox("🚀 Дублировать этот этап для всех наборов проекта, которые еще в работе", 
                        value=False, key="tech_bulk_copy", 
                        help="Этап будет создан для всех видов сведений проекта, где еще не выполнен этап 'Публикация набора'")
        # --- КНОПКИ ДЕЙСТВИЙ ---
        cb1, cb2 = st.columns([3, 1])

        with cb1:
            if st.button("💾 Сохранить изменения", type="primary", use_container_width=True, key="tech_save_final_btn"):
                try:
                    s_id = stage_map[st.session_state.tech_stage_in]["id"]
                    r_id = None
                    if st.session_state.tech_resp_in != "Не назначен":
                        r_res = query_db("SELECT user_id FROM users WHERE display_name=:n", {"n": st.session_state.tech_resp_in})
                        if not r_res.empty: r_id = int(r_res.iloc[0]["user_id"])

                    # Список ID для вставки (по умолчанию только текущий)
                    items_to_process = [selected_item_id]

                    # ЛОГИКА МАССОВОГО КОПИРОВАНИЯ (только для новых записей)
                    if not is_editing and st.session_state.get("tech_bulk_copy"):
                        # 1. Находим ID этапа публикации
                        pub_stage_res = query_db("SELECT stage_id FROM stages WHERE stage_name = 'Публикация набора' LIMIT 1")
                        pub_stage_id = int(pub_stage_res.iloc[0]['stage_id']) if not pub_stage_res.empty else None
                        
                        # 2. Находим все item_id проекта, кроме текущего
                        all_project_items = project_items[project_items['item_id'] != selected_item_id]['item_id'].tolist()
                        
                        for other_id in all_project_items:
                            # 3. Проверяем, не завершена ли публикация по этому набору
                            is_finished = False
                            if pub_stage_id:
                                check_pub = session.execute(text("""
                                    SELECT 1 FROM item_stages 
                                    WHERE item_id = :iid AND stage_id = :sid 
                                    AND micro_status = (SELECT micro_status_id FROM ref_micro_statuses WHERE micro_status_name = 'Выполнено')
                                """), {"iid": int(other_id), "sid": pub_stage_id}).scalar()
                                if check_pub: is_finished = True
                            
                            if not is_finished:
                                items_to_process.append(int(other_id))

                    # ВЫПОЛНЯЕМ СОХРАНЕНИЕ ДЛЯ ВСЕХ ВЫБРАННЫХ ITEM_ID
                    for target_iid in items_to_process:
                        # Авто-закрытие для каждого набора отдельно
                        if not is_editing and st.session_state.tech_auto_close:
                            session.execute(text("UPDATE item_stages SET actual_end=:n, micro_status=:ms WHERE item_id=:i AND actual_end IS NULL"),
                                            {"n": date.today(), "ms": micro_map["Выполнено"], "i": target_iid})

                        # Расчет итерации для каждого набора индивидуально
                        it_val = st.session_state.tech_iter_in if is_editing else \
                                 session.execute(text("SELECT COALESCE(MAX(iteration_count), 0) + 1 FROM item_stages WHERE item_id=:i AND stage_id=:s"),
                                                 {"i": target_iid, "s": s_id}).scalar()

                        params = {
                            "iid": target_iid, "sid": s_id, "mst": int(micro_map[st.session_state.tech_status_in]),
                            "iter": int(it_val), "ps": st.session_state.tech_p_start_in, "pe": st.session_state.tech_p_end_in,
                            "as": st.session_state.tech_a_start_in, "ae": st.session_state.tech_a_end_in,
                            "comm": st.session_state.tech_comments_in, "rid": r_id
                        }

                        if is_editing:
                            params["id"] = int(item_ids_map[sel_item])
                            session.execute(text("""UPDATE item_stages SET stage_id=:sid, micro_status=:mst, iteration_count=:iter,
                                planned_start=:ps, planned_end=:pe, actual_start=:as, actual_end=:ae, comments=:comm, responsible_id=:rid
                                WHERE stage_progress_id=:id"""), params)
                        else:
                            session.execute(text("""INSERT INTO item_stages (item_id, stage_id, micro_status, iteration_count,
                                planned_start, planned_end, actual_start, actual_end, comments, responsible_id)
                                VALUES (:iid, :sid, :mst, :iter, :ps, :pe, :as, :ae, :comm, :rid)"""), params)

                    session.commit(); clear_cache()
                    st.success(f"✅ Готово! Обработано наборов: {len(items_to_process)}")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка БД: {e}"); session.rollback()
        with cb2:
            if is_editing and st.button("🗑 Удалить", type="secondary", use_container_width=True, key="tech_delete_final_btn"):
                session.execute(text("DELETE FROM item_stages WHERE stage_progress_id = :id"), {"id": int(item_ids_map[sel_item])})
                session.commit(); clear_cache(); st.rerun()