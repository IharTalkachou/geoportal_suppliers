import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
import json
from config.cache import query_db, clear_cache
from config.auth import log_action

# Хелперы из бюрократии
from ui.bureaucracy_tab import custom_badge, format_date_ru

# ==========================================
# 🛠️ СЕРВИСНЫЕ ФУНКЦИИ
# ==========================================

def _resync_tech_iterations(session, project_id):
    """Пересчет итераций для технологических этапов"""
    rows = query_db("""
        SELECT ps.stage_progress_id, ps.stage_id, ps.micro_status, 
               ps.planned_start, ps.actual_start, ps.actual_end 
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        WHERE ps.project_id = :pid AND s.track_category = '2. Технологический'
    """, {"pid": project_id})
    if rows.empty: return

    for s_id in rows['stage_id'].unique():
        sub = rows[rows['stage_id'] == s_id].copy()
        def get_sort_key(r):
            start = r['actual_start'] or r['planned_start'] or date.min
            if r['micro_status'] == 4: return (r['actual_end'] or date.max, start)
            if r['micro_status'] == 1: return (r['planned_start'] or date.min, start)
            return (start, start)
        sub['sort_key'] = sub.apply(get_sort_key, axis=1)
        sub = sub.sort_values(by='sort_key')
        for i, (_, row) in enumerate(sub.iterrows(), 1):
            session.execute(text("UPDATE project_stages SET iteration_count = :v WHERE stage_progress_id = :id"),
                            {"v": i, "id": int(row['stage_progress_id'])})

# ==========================================
# 💬 ДИАЛОГОВОЕ ОКНО (ALM 2.0 + AUTO-FILL)
# ==========================================

@st.dialog("Управление тех. этапом", width="large")
def tech_mgmt_dialog(session, project_id, stage_map, micro_map, project_items, existing_data=None):
    is_edit = existing_data is not None
    st_names = list(stage_map.keys())
    ms_names = list(micro_map.keys())
    
    # 1. ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ
    if "td_stage" not in st.session_state:
        st.session_state.td_stage = existing_data['stage_name'] if is_edit else st_names[0]
    if "td_ms" not in st.session_state:
        st.session_state.td_ms = existing_data['micro_status_name'] if is_edit else ms_names[0]
    if "td_p_start" not in st.session_state:
        st.session_state.td_p_start = existing_data['planned_start'] if is_edit else date.today()
    if "td_affected_ids" not in st.session_state:
        st.session_state.td_affected_ids = existing_data['affected_item_ids'] if (is_edit and existing_data.get('affected_item_ids')) else []
    if "td_a_start" not in st.session_state:
        st.session_state.td_a_start = existing_data['actual_start'] if is_edit else None
    if "td_a_end" not in st.session_state:
        st.session_state.td_a_end = existing_data['actual_end'] if is_edit else None

    # 2. ЛОГИКА АВТОПОДСТАНОВКИ И SLA
    def update_logic_callback():
        sel_stage_info = stage_map[st.session_state.td_stage]
        sel_code = sel_stage_info['code']
        ids = st.session_state.td_affected_ids
        
        # 🟢 ЛОГИКА ВЫБОРА ИСТОЧНИКА СРОКА
        # meta_days и data_days нужны только на этапах Размещение метаданных Поставщиком и Размещение наборов
        # Коды этапов: META_WAIT и DATA_WAIT (проверь соответствие в своей таблице stages)
        
        if sel_code == 'META_WAIT' and ids:
            days = project_items[project_items['item_id'].isin(ids)]['meta_days'].max()
        elif sel_code == 'DATA_WAIT' and ids:
            days = project_items[project_items['item_id'].isin(ids)]['data_days'].max()
        else:
            # Для всех остальных этапов читаем duration_days из таблицы stages (из справочника)
            days = sel_stage_info.get('duration', 0)
        
        st.session_state.td_p_end = st.session_state.td_p_start + timedelta(days=int(days or 0))

        # Б. Автозаполнение фактических дат (Пункт 3)
        # Если статус "В работе" (2) или "Ожидание" (3)
        cur_ms_id = micro_map[st.session_state.td_ms]
        if cur_ms_id in [2, 3] and not is_edit:
            st.session_state.td_a_start = st.session_state.td_p_start
            # Если это веха
            if sel_stage_info['type'] == 'Веха':
                st.session_state.td_a_end = st.session_state.td_p_start

    # Предварительный расчет для первой отрисовки
    if "td_p_end" not in st.session_state:
        if is_edit: st.session_state.td_p_end = existing_data['planned_end']
        else: update_logic_callback()

    # 3. ОТРИСОВКА
    col1, col2 = st.columns(2)
    with col1:
        st.selectbox("Технологический этап *", st_names, key="td_stage", on_change=update_logic_callback)
        st.selectbox("Статус", ms_names, key="td_ms")
        
        staff_df = query_db("SELECT user_id, display_name FROM users WHERE show_in_staff=True AND is_active=True ORDER BY display_name")
        staff_map = dict(zip(staff_df["display_name"], staff_df["user_id"]))
        staff_options = ["Не назначен"] + list(staff_map.keys())
        def_resp = existing_data['responsible_name'] if (is_edit and existing_data.get('responsible_name')) else "Не назначен"
        st.selectbox("👤 Ответственный", staff_options, key="td_resp", index=staff_options.index(def_resp) if def_resp in staff_options else 0)

    with col2:
        st.date_input("🗓️ План. начало", key="td_p_start", on_change=update_logic_callback)
        st.date_input("🎯 Дедлайн (SLA)", key="td_p_end")

    st.divider()
    
    # 4. МУЛЬТИСЕЛЕКТ НАБОРОВ
    st.markdown("**📦 Виды сведений:**")
    cur_stage_id = stage_map[st.session_state.td_stage]['id']
    
    # Фильтруем закрытые только для НОВЫХ этапов "Публикация"
    available_items = project_items.copy()
    '''if not is_edit:
        closed_q = query_db("""
            SELECT DISTINCT jsonb_array_elements_text(affected_item_ids)::int as item_id
            FROM project_stages WHERE project_id = :pid AND stage_id = :sid AND micro_status = 4
        """, {"pid": project_id, "sid": cur_stage_id})
        closed_ids = closed_q['item_id'].tolist() if not closed_q.empty else []
        available_items = available_items[~available_items['item_id'].isin(closed_ids)]'''
    
    '''if available_items.empty and not is_edit:
        st.warning("⚠️ Все наборы уже прошли этот этап."); affected_ids = []
    else:'''
    item_opts = {f"{r['dataset_name']} | {r['info_name']}": int(r['item_id']) for _, r in available_items.iterrows()}
    
    def on_items_change():
        st.session_state.td_affected_ids = [item_opts[l] for l in st.session_state.td_multi_items]
        update_logic_callback()

    st.multiselect(
        "Выберите виды сведений *", options=list(item_opts.keys()), 
        default=[l for l, iid in item_opts.items() if iid in st.session_state.td_affected_ids],
        key="td_multi_items", on_change=on_items_change
    )
    affected_ids = st.session_state.td_affected_ids

    st.divider()
    c3, c4 = st.columns(2)
    is_not_started = micro_map[st.session_state.td_ms] in (1, 5)  # Планируется / Отложено
    if is_not_started:
        st.session_state.td_a_start = None
        st.session_state.td_a_end = None
    c3.date_input("🚀 Факт. начало", key="td_a_start", disabled=is_not_started)
    c4.date_input("🏁 Факт. конец", key="td_a_end", disabled=is_not_started)
    
    st.text_area("Комментарий", value=existing_data['comments'] if is_edit else "", key="td_comm")

    if st.button("💾 Сохранить тех. этап", type="primary", width='stretch'):
        if not affected_ids: st.error("Выберите виды сведений"); return
        try:
            r_id = staff_map.get(st.session_state.td_resp) if st.session_state.td_resp != "Не назначен" else None
            params = {
                "pid": project_id, "sid": stage_map[st.session_state.td_stage]["id"],
                "mst": micro_map[st.session_state.td_ms], "ps": st.session_state.td_p_start,
                "pe": st.session_state.td_p_end, "as": st.session_state.td_a_start,
                "ae": st.session_state.td_a_end, "comm": st.session_state.td_comm,
                "items": json.dumps(affected_ids), "rid": r_id
            }
            if is_edit:
                params["id"] = int(existing_data['stage_progress_id'])
                session.execute(text("""UPDATE project_stages SET stage_id=:sid, micro_status=:mst, planned_start=:ps, 
                    planned_end=:pe, actual_start=:as, actual_end=:ae, comments=:comm, affected_item_ids=:items, responsible_id=:rid 
                    WHERE stage_progress_id=:id"""), params)
            else:
                session.execute(text("""INSERT INTO project_stages (project_id, stage_id, micro_status, iteration_count,
                    planned_start, planned_end, actual_start, actual_end, comments, affected_item_ids, responsible_id)
                    VALUES (:pid, :sid, :mst, 1, :ps, :pe, :as, :ae, :comm, :items, :rid)"""), params)
            session.commit(); _resync_tech_iterations(session, project_id); session.commit(); clear_cache(); st.rerun()
        except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

# ==========================================
# 📊 ОСНОВНОЙ ТАБ
# ==========================================

def render_technology_tab(session, project_id, user_role="user"):
    is_readonly = (user_role == "user")
    
    with st.spinner("Загрузка технологий..."):
        # 1. Состав + SLA
        project_items = query_db("""
            SELECT pi.item_id, d.dataset_name, i.info_name, pi.meta_days, pi.data_days
            FROM project_items pi
            JOIN datasets d ON pi.dataset_id = d.dataset_id
            JOIN info_types i ON pi.info_id = i.info_id
            WHERE pi.project_id = :pid
        """, {"pid": project_id})

        if project_items.empty:
            st.warning("⚠️ Добавьте наборы во вкладке 'Состав'."); return

        # 2. Справочники
        s_ref = query_db("SELECT stage_id, stage_name, duration_days, stage_code, stage_type FROM stages WHERE track_category = '2. Технологический' ORDER BY stage_order")
        m_ref = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses")
        
        # Включаем stage_type в карту
        stage_map = {r['stage_name']: {"id": int(r['stage_id']), "duration": int(r['duration_days'] or 0), "code": r['stage_code'], "type": r['stage_type']} for _, r in s_ref.iterrows()}
        micro_map = {r['micro_status_name']: int(r['micro_status_id']) for _, r in m_ref.iterrows()}

        # 3. Данные (Исправлена сортировка)
        df = query_db("""
            SELECT ps.*, s.stage_name, ms.micro_status_name, u.display_name as responsible_name
            FROM project_stages ps
            JOIN stages s ON ps.stage_id = s.stage_id
            JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
            LEFT JOIN users u ON ps.responsible_id = u.user_id
            WHERE ps.project_id = :pid AND s.track_category = '2. Технологический'
            ORDER BY CASE WHEN ps.micro_status = 4 THEN 1 ELSE 0 END ASC, 
                     COALESCE(ps.actual_end, ps.actual_start, ps.planned_start) DESC,
                     s.stage_order DESC
        """, {"pid": project_id})

    h1, h2 = st.columns([0.8, 0.2])
    h1.subheader("⚙️ Технологический цикл")
    if not is_readonly and h2.button("➕ Тех. этап", width='stretch', type="primary"):
        for k in ["td_stage", "td_ms", "td_p_start", "td_p_end", "td_affected_ids", "td_multi_items", "td_resp", "td_a_start", "td_a_end"]:
            if k in st.session_state: del st.session_state[k]
        tech_mgmt_dialog(session, project_id, stage_map, micro_map, project_items)

    # Канбан
    col_work, col_plan, col_done = st.columns(3)
    with col_work:
        st.markdown("##### ⚡ В работе")
        for _, row in df[df['micro_status'].isin([2, 3, 6])].iterrows():
            render_tech_card(session, row, project_id, stage_map, micro_map, project_items, is_readonly)
    with col_plan:
        st.markdown("##### 🗓️ Планируется")
        for _, row in df[df['micro_status'].isin([1, 5])].iterrows():
            render_tech_card(session, row, project_id, stage_map, micro_map, project_items, is_readonly)
    with col_done:
        st.markdown("##### ✅ Опубликовано")
        for _, row in df[df['micro_status'] == 4].iterrows():
            render_tech_card(session, row, project_id, stage_map, micro_map, project_items, is_readonly)

def render_tech_card(session, row, project_id, stage_map, micro_map, project_items, is_readonly):
    ms = row['micro_status']
    is_overdue = (ms == 6)
    main_color = {4: "#27AE60", 6: "#E74C3C", 2: "#3498DB", 1: "#95A5A6", 3: "#F39C12", 5: "#7F8C8D"}.get(ms, "#BDC3C7")

    card_key = f"tcard_{row['stage_progress_id']}"
    with st.container(border=True, key=card_key):
        # 1. Заголовок (Статус + Дата начала)
        start_dt = row['actual_start'] or row['planned_start']
        txt = f"{row['micro_status_name']} с {format_date_ru(start_dt)}"
        if ms == 4: txt = f"{row['micro_status_name']} {format_date_ru(row['actual_end'])}"
        st.markdown(custom_badge(txt, main_color, "white"), unsafe_allow_html=True)
        
        # 2. Срок (Пункт 2 - только для активных)
        if ms in [2, 3, 6]:
            deadline_txt = f"Срок — {format_date_ru(row['planned_end'])}"
            st.markdown(custom_badge(deadline_txt, "#FDEBD0", "#935116", bold=False), unsafe_allow_html=True)

        # 3. Комментарий (Пункт 4 - дублируем имя этапа если пусто)
        display_comm = row['comments'] if row['comments'] and str(row['comments']).strip() else row['stage_name']
        st.markdown(f'<div style="margin: 8px 0;"><b>💬 {display_comm}</b></div>', unsafe_allow_html=True)

        # 4. Этап и Исполнитель
        b_stage = custom_badge(f"{row['stage_name']} (ит. {int(row['iteration_count'])})", "#F4ECF7", "#6C3483")
        b_resp = custom_badge(row['responsible_name'] or "Не назначен", "#FEF9E7", "#9A7D0A")
        st.markdown(f"<div>{b_stage}{b_resp}</div>", unsafe_allow_html=True)
        
        # 5. Наборы
        affected_ids = row.get('affected_item_ids', [])
        if affected_ids:
            import json
            if isinstance(affected_ids, str):
                try: affected_ids = json.loads(affected_ids)
                except: affected_ids = []
                
            names = project_items[project_items['item_id'].isin(affected_ids)]['info_name'].tolist()
            st.markdown("**📦 Применено к:**")
            for name in names:
                st.markdown(f"<div style='font-size:0.8rem; margin: 1px 0; color: #444;'>• {name}</div>", unsafe_allow_html=True)

        # 6. Действия
        if not is_readonly:
            with st.popover("⚙️"):
                if st.button("✏️", key=f"te_{row['stage_progress_id']}", width='stretch'):
                    for k in ["td_stage", "td_ms", "td_p_start", "td_p_end", "td_affected_ids", "td_multi_items", "td_resp", "td_a_start", "td_a_end"]:
                        if k in st.session_state: del st.session_state[k]
                    tech_mgmt_dialog(session, project_id, stage_map, micro_map, project_items, existing_data=row)
                if st.button("🗑", key=f"td_{row['stage_progress_id']}", width='stretch'):
                    session.execute(text("DELETE FROM project_stages WHERE stage_progress_id = :id"), {"id": int(row['stage_progress_id'])})
                    session.commit(); _resync_tech_iterations(session, project_id); session.commit(); clear_cache(); st.rerun()