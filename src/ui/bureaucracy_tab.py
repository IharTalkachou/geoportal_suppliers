import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache
from config.auth import log_action

# ==========================================
# 🛠️ СЕРВИСНЫЕ ФУНКЦИИ И ЛОГИКА
# ==========================================

def format_date_ru(d):
    """Красивый формат даты: 25 июня 2026"""
    if not d: return "—"
    months = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    return f"{d.day} {months[d.month-1]} {d.year}"

def _resync_buro_iterations(session, project_id):
    """Пересчет итераций на основе хронологии"""
    rows = query_db("SELECT stage_progress_id, stage_id, micro_status, planned_start, actual_start, actual_end FROM project_stages WHERE project_id = :pid", {"pid": project_id})
    if rows.empty: return
    for s_id in rows['stage_id'].unique():
        sub = rows[rows['stage_id'] == s_id].copy()
        def get_sort_key(r):
            if r['micro_status'] == 4: return r['actual_end'] or date.max
            if r['micro_status'] == 1: return r['planned_start'] or date.min
            return r['actual_start'] or r['planned_start'] or date.min
        sub['sort_date'] = sub.apply(get_sort_key, axis=1)
        sub = sub.sort_values(by='sort_date')
        for i, (_, row) in enumerate(sub.iterrows(), 1):
            session.execute(text("UPDATE project_stages SET iteration_count = :v WHERE stage_progress_id = :id"),
                            {"v": i, "id": int(row['stage_progress_id'])})

def custom_badge(text, bg_color="#E0E0E0", text_color="#333", bold=True):
    fw = "700" if bold else "500"
    return (f'<span style="background-color:{bg_color};color:{text_color};padding:2px 10px;'
            f'border-radius:4px;font-size:0.75rem;font-weight:{fw};display:inline-block;'
            f'margin-right:5px;border:1px solid rgba(0,0,0,0.05);white-space:nowrap;">{text}</span>')

# ==========================================
# 💬 ДИАЛОГОВЫЕ ОКНА (CRUD)
# ==========================================

@st.dialog("Управление этапом")
def stage_mgmt_dialog(session, project_id, stage_map, micro_map, existing_data=None):
    is_edit = existing_data is not None
    st_names, ms_names = list(stage_map.keys()), list(micro_map.keys())

    # ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ (Фикс конфликта Session State)
    if "d_p_start" not in st.session_state:
        st.session_state.d_p_start = existing_data['planned_start'] if is_edit else date.today()
    
    if "d_p_end" not in st.session_state:
        if is_edit:
            st.session_state.d_p_end = existing_data['planned_end']
        else:
            dur = stage_map[st_names[0]]['duration']
            st.session_state.d_p_end = st.session_state.d_p_start + timedelta(days=dur)
    
    staff_df = query_db("SELECT user_id, display_name FROM users WHERE show_in_staff=True AND is_active=True ORDER BY display_name")
    staff_map = dict(zip(staff_df["display_name"], staff_df["user_id"]))
    staff_options = ["Не назначен"] + list(staff_map.keys())

    col1, col2 = st.columns(2)
    with col1:
        def on_p_start_change():
            dur = stage_map.get(st.session_state.d_stage, {}).get("duration", 0)
            st.session_state.d_p_end = st.session_state.d_p_start + timedelta(days=dur)
        def_resp = existing_data['responsible_name'] if (is_edit and existing_data.get('responsible_name')) else "Не назначен"
        st.selectbox("Этап *", st_names, key="d_stage", index=st_names.index(existing_data['stage_name']) if is_edit else 0, on_change=on_p_start_change)
        st.selectbox("Статус", ms_names, key="d_ms", index=ms_names.index(existing_data['micro_status_name']) if is_edit else 0)
        st.selectbox("👤 Ответственный", staff_options, key="d_resp", index=staff_options.index(def_resp) if def_resp in staff_options else 0)
    with col2:
        st.date_input("🗓️ План. начало", key="d_p_start", on_change=on_p_start_change)
        st.date_input("🎯 Дедлайн", key="d_p_end")
    
    st.divider()
    c3, c4 = st.columns(2)
    c3.date_input("🚀 Факт. начало", key="d_a_start", value=existing_data['actual_start'] if is_edit else None)
    c4.date_input("🏁 Факт. конец", key="d_a_end", value=existing_data['actual_end'] if is_edit else None)
    st.text_area("Комментарий", value=existing_data['comments'] if is_edit else "", key="d_comm")
    
    if is_edit:
        st.caption("📂 Документы")
        # 1. Загрузка существующих
        # Используем int() для ID, так как pandas может вернуть numpy.int64
        curr_ps_id = int(existing_data['stage_progress_id'])
        docs = query_db("SELECT * FROM stage_documents WHERE project_stage_id = :id", {"id": curr_ps_id})
        
        for _, d in docs.iterrows():
            dc1, dc2 = st.columns([0.85, 0.15])
            dc1.caption(f"📄 {d['doc_name']}")
            # Удаление
            if dc2.button("🗑", key=f"del_doc_buro_{d['doc_id']}"):
                session.execute(text("DELETE FROM stage_documents WHERE doc_id = :id"), {"id": int(d['doc_id'])})
                session.commit()
                clear_cache()
                st.rerun()
        
        # 2. Добавление нового
        with st.popover("📎 Добавить документ", width='stretch'):
            new_n = st.text_input("Название (напр. Письмо №...)")
            new_u = st.text_input("URL-ссылка")
            if st.button("Сохранить ссылку", key="btn_save_new_doc_buro"):
                if new_n and new_u:
                    try:
                        session.execute(text("""
                            INSERT INTO stage_documents (project_stage_id, doc_name, doc_url) 
                            VALUES (:id, :n, :u)
                        """), {"id": curr_ps_id, "n": new_n, "u": new_u})
                        session.commit()
                        clear_cache()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {e}")
                else:
                    st.warning("Заполните поля")

    if st.button("💾 Сохранить", type="primary", width='stretch'):
        try:
            r_id = staff_map.get(st.session_state.d_resp) if st.session_state.d_resp != "Не назначен" else None
            params = {
                "pid": project_id, "sid": stage_map[st.session_state.d_stage]["id"],
                "mst": micro_map[st.session_state.d_ms], "ps": st.session_state.d_p_start,
                "pe": st.session_state.d_p_end, "as": st.session_state.d_a_start,
                "ae": st.session_state.d_a_end, "comm": st.session_state.d_comm,
                "rid": r_id
            }
            if is_edit:
                params["id"] = int(existing_data['stage_progress_id'])
                session.execute(text("UPDATE project_stages SET stage_id=:sid, micro_status=:mst, planned_start=:ps, planned_end=:pe, actual_start=:as, actual_end=:ae, comments=:comm, responsible_id=:rid WHERE stage_progress_id=:id"), params)
            else:
                session.execute(text("INSERT INTO project_stages (project_id, stage_id, micro_status, iteration_count, planned_start, planned_end, actual_start, actual_end, comments, responsible_id) VALUES (:pid, :sid, :mst, 1, :ps, :pe, :as, :ae, :comm, :rid)"), params)
            session.commit(); _resync_buro_iterations(session, project_id); session.commit()
            from utils.project_utils import sync_project_status
            sync_project_status(session, project_id)
            clear_cache(); st.session_state.buro_toast = "✅ Изменения сохранены"; st.rerun()
        except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

@st.dialog("Удаление")
def confirm_delete_dialog(session, stage_id, project_id):
    st.warning("Удалить этот этап?")
    if st.button("❌ Да, удалить", type="primary", width='stretch'):
        session.execute(text("DELETE FROM project_stages WHERE stage_progress_id = :id"), {"id": stage_id})
        session.commit(); _resync_buro_iterations(session, project_id); session.commit(); clear_cache(); st.rerun()

# ==========================================
# 📊 ОСНОВНОЙ ЭКРАН
# ==========================================

def render_bureaucracy_tab(session, project_id, user_role="user"):
    is_readonly = (user_role == "user")
    
    # 1. Справочники
    s_ref = query_db("SELECT stage_id, stage_name, duration_days FROM stages WHERE track_category = '1. Документарный' ORDER BY stage_order")
    m_ref = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses")
    stage_map = {r['stage_name']: {"id": int(r['stage_id']), "duration": int(r['duration_days'] or 0)} for _, r in s_ref.iterrows()}
    micro_map = {r['micro_status_name']: int(r['micro_status_id']) for _, r in m_ref.iterrows()}

    # 2. Данные
    df = query_db("""
        SELECT ps.*, s.stage_name, s.stage_order, ms.micro_status_name, u.display_name as responsible_name
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE ps.project_id = :pid 
          AND s.track_category = '1. Документарный'  -- 👈 ВОТ ЭТОТ ФИЛЬТР УБЕРЕТ ТЕХНОЛОГИЮ
        ORDER BY 
            CASE WHEN ps.micro_status = 4 THEN 1 ELSE 0 END ASC, 
            COALESCE(ps.actual_end, ps.actual_start, ps.planned_start) DESC,
            s.stage_order DESC -- 👈 ТЕПЕРЬ ПРИ РАВНЫХ ДАТАХ ПОБЕДИТ ТОТ, КТО ПОСЛЕДНИЙ В СПИСКЕ ЭТАПОВ
    """, {"pid": project_id})

    if "buro_toast" in st.session_state:
        st.toast(st.session_state.buro_toast); del st.session_state.buro_toast

    h_col1, h_col2 = st.columns([0.8, 0.2])
    h_col1.subheader("📜 Бюрократический трек")
    if not is_readonly:
        if h_col2.button("➕ Добавить этап", width='stretch', type="primary"):
            for k in ["d_stage", "d_ms", "d_p_start", "d_p_end", "d_comm", "d_resp", "d_a_start", "d_a_end"]:
                if k in st.session_state: del st.session_state[k]
            stage_mgmt_dialog(session, project_id, stage_map, micro_map)

    # Распределение
    work_df = df[df['micro_status'].isin([2, 3, 6])]
    plan_df = df[df['micro_status'].isin([1, 5])]
    done_df = df[df['micro_status'] == 4]

    c_work, c_plan, c_done = st.columns(3)

    with c_work:
        st.markdown("##### ⚡ В работе / Ожидание")
        for _, row in work_df.iterrows():
            render_stage_card(session, row, project_id, stage_map, micro_map, is_readonly)

    with c_plan:
        st.markdown("##### 🗓️ Плановые")
        for _, row in plan_df.iterrows():
            render_stage_card(session, row, project_id, stage_map, micro_map, is_readonly)

    with c_done:
        st.markdown("##### ✅ Выполнено")
        for _, row in done_df.iterrows():
            render_stage_card(session, row, project_id, stage_map, micro_map, is_readonly)

def render_stage_card(session, row, project_id, stage_map, micro_map, is_readonly):
    """Универсальный отрисовщик карточек по типам статусов"""
    ms = row['micro_status']
    is_overdue = (ms == 6)
    
    # Определение просрочки для выполненных
    was_late = False
    if ms == 4 and row['actual_end'] and row['planned_end']:
        if row['actual_end'] > row['planned_end']: was_late = True

    # 1. Цветовая схема
    colors = {4: "#27AE60", 6: "#E74C3C", 2: "#3498DB", 1: "#95A5A6", 3: "#F39C12", 5: "#7F8C8D"}
    main_color = colors.get(ms, "#BDC3C7")
    bg_color = "#FFF9F9" if is_overdue else "#FFFFFF"
    border_style = f"2px solid {main_color}" if is_overdue else "1px solid #E0E0E0"

    card_key = f"card_{row['stage_progress_id']}"
    if is_overdue:
        st.markdown(f'<style>div[data-testid="stVerticalBlockBorderWrapper"]:has(>.st-key-{card_key}) {{ border: {border_style} !important; background-color: {bg_color} !important; }}</style>', unsafe_allow_html=True)

    with st.container(border=True, key=card_key):
        # СТРОКА 1: Статус и даты
        if ms == 4: # Выполнено
            bolt = " ⚡" if was_late else ""
            txt = f"{row['micro_status_name']} {format_date_ru(row['actual_end'])}{bolt}"
            st.markdown(custom_badge(txt, main_color, "white"), unsafe_allow_html=True)
        
        elif ms == 1: # Планируется
            txt = f"Планируется с {format_date_ru(row['planned_start'])} по {format_date_ru(row['planned_end'])}"
            st.markdown(custom_badge(txt, main_color, "white"), unsafe_allow_html=True)
        
        elif ms == 5: # Отложено
            txt = f"Отложено до {format_date_ru(row['planned_start'])}"
            st.markdown(custom_badge(txt, main_color, "white"), unsafe_allow_html=True)
        
        else: # В работе / Ожидание / Просрочено
            start_txt = f"с {format_date_ru(row['actual_start'] or row['planned_start'])}"
            if is_overdue:
                txt = f"ПРОСРОЧЕНО! Дедлайн {format_date_ru(row['planned_end'])}"
            else:
                txt = f"{row['micro_status_name']} {start_txt}"
            st.markdown(custom_badge(txt, main_color, "white"), unsafe_allow_html=True)

        # СТРОКА 2: Комментарий (Защищенный b-тег для обхода проблем разметки)
        comm_text = row['comments'] or "—"
        st.markdown(f'<div style="margin: 8px 0; font-size: 0.95rem;"><b>💬 {comm_text}</b></div>', unsafe_allow_html=True)

        # СТРОКА 3: Этап + Итерация и Исполнитель
        b_stage = custom_badge(f"{row['stage_name']} (ит. {int(row['iteration_count'])})", "#F4ECF7", "#6C3483")
        b_resp = custom_badge(row['responsible_name'] or "Не назначен", "#FEF9E7", "#9A7D0A")
        st.markdown(f"<div>{b_stage}{b_resp}</div>", unsafe_allow_html=True)

        # СТРОКА 4: Файлы
        docs = query_db("SELECT doc_name, doc_url FROM stage_documents WHERE project_stage_id = :id", {"id": int(row['stage_progress_id'])})
        if not docs.empty:
            links = [f'<a href="{d["doc_url"]}" target="_blank" style="text-decoration:none; font-size:0.8rem;">📄 {d["doc_name"]}</a>' for _, d in docs.iterrows()]
            st.markdown('<div style="margin-top:8px;">' + " ".join(links) + '</div>', unsafe_allow_html=True)
        
        # СТРОКА 5: Действия
        if not is_readonly:
            st.write("")
            with st.popover("⚙️ Действия"):
                if st.button("✏️ Редактировать", key=f"ed_{row['stage_progress_id']}", width='stretch'):
                    stage_mgmt_dialog(session, project_id, stage_map, micro_map, existing_data=row)
                if st.button("🗑 Удалить", key=f"dl_{row['stage_progress_id']}", width='stretch'):
                    confirm_delete_dialog(session, int(row['stage_progress_id']), project_id)