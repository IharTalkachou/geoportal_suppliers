import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ui.analytics.data_provider import get_analytics_snapshot
# Импортируем наши проверенные хелперы
from ui.analytics.kpi_logic import badge_html, format_date_ru_local, get_proximity_color, check_sla_alert

def render_staff_tab():
    st.subheader("👥 Оперативный контроль и нагрузка сотрудников")
    
    # 1. Получаем данные и фильтруем Оператора
    df_raw = get_analytics_snapshot()
    if df_raw.empty:
        st.info("Нет данных для анализа."); return

    # Исключаем Белгеодезию (Оператора) из статистики сотрудников
    df_raw = df_raw[~df_raw['supplier_name'].str.contains('Белгеодезия', case=False, na=False)]

    # Подготовка уникального ключа задачи (UID)
    df_raw['uid'] = df_raw.apply(lambda x: f"{x['project_id']}_{x['track_type']}_{x['stage_code']}_{x['iteration_count']}", axis=1)
    
    # Считаем алерты SLA
    df_raw['has_alert'] = df_raw.apply(check_sla_alert, axis=1)
    
    # Группируем по UID для уникальных задач
    df_unique = df_raw.drop_duplicates(subset=['uid']).copy()

    # 2. ВЕРХНЯЯ ПАНЕЛЬ МЕТРИК (СВОДКА)
    active_mask = df_unique['status'].isin(['В работе', 'Ожидание', 'Планируется', 'Отложено'])
    active_tasks = df_unique[active_mask]
    
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Задач в работе", len(active_tasks))
    with m2:
        overdue_count = len(active_tasks[active_tasks['has_alert'] == True])
        st.metric("Просрочено / Горит", overdue_count, delta=-overdue_count, delta_color="inverse")
    with m3:
        # Среднее кол-во задач на одного активного сотрудника
        active_staff_count = active_tasks['responsible_name'].nunique()
        load_avg = round(len(active_tasks) / active_staff_count, 1) if active_staff_count > 0 else 0
        st.metric("Средняя нагрузка", f"{load_avg} задачи/чел")

    st.write("")

    # 3. ОСНОВНЫЕ РАЗДЕЛЫ
    tab_current, tab_history = st.tabs(["🔥 Текущая загрузка", "✅ История выполнения"])

    with tab_current:
        _render_active_load_section(active_tasks, df_raw)

    with tab_history:
        _render_staff_history_section(df_unique)

def _render_active_load_section(active_tasks, df_raw):
    """Блок анализа текущей нагрузки с фильтрами"""
    c1, c2, c3 = st.columns([1, 1, 1])
    
    with c1:
        # Фильтр по сотрудникам
        staff_list = sorted([s for s in active_tasks['responsible_name'].unique() if s])
        sel_staff = st.multiselect("Исполнители:", staff_list, placeholder="Все сотрудники")
    
    with c2:
        # 🟢 НОВЫЙ ФИЛЬТР: Микростатусы
        status_list = ["В работе", "Ожидание", "Планируется", "Отложено"]
        sel_statuses = st.multiselect("Статусы:", status_list, placeholder="Все статусы")

    with c3:
        proj_list = sorted(active_tasks['project_name'].unique())
        sel_projs = st.multiselect("Проекты:", proj_list, placeholder="Все проекты")

    # Применение фильтров
    disp_df = active_tasks.copy()
    if sel_staff: 
        disp_df = disp_df[disp_df['responsible_name'].isin(sel_staff)]
    if sel_statuses: 
        disp_df = disp_df[disp_df['status'].isin(sel_statuses)]
    if sel_projs: 
        disp_df = disp_df[disp_df['project_name'].isin(sel_projs)]

    if disp_df.empty:
        st.info("Задачи не найдены."); return

    # Рендер Master-Detail
    _render_staff_task_grid(disp_df, df_raw, "active")

def _render_staff_history_section(df_unique):
    """Блок архива выполненных работ"""
    done_base = df_unique[df_unique['status'] == 'Выполнено'].copy()
    
    c1, c2 = st.columns(2)
    with c1:
        period = st.selectbox("За период:", ["Текущий месяц", "Текущая неделя", "Год", "Все время"], key="staff_h_p")
    
    # Логика фильтрации дат
    today = datetime.now()
    if period == "Текущая неделя": start_date = today - timedelta(days=today.weekday())
    elif period == "Текущий месяц": start_date = today.replace(day=1)
    elif period == "Год": start_date = today.replace(month=1, day=1)
    else: start_date = datetime(2000, 1, 1)

    done_filtered = done_base[done_base['actual_end'] >= pd.Timestamp(start_date)].copy()

    with c2:
        staff_done = sorted([s for s in done_filtered['responsible_name'].unique() if s])
        sel_h_staff = st.multiselect("Сотрудник:", staff_done, placeholder="Все")

    if sel_h_staff:
        done_filtered = done_filtered[done_filtered['responsible_name'].isin(sel_h_staff)]

    if done_filtered.empty:
        st.caption("Записей не найдено."); return

    st.dataframe(
        done_filtered[['responsible_name', 'project_name', 'stage_name', 'actual_end', 'comments']],
        width='stretch', hide_index=True,
        column_config={
            "responsible_name": "Кто выполнил",
            "project_name": "Проект",
            "stage_name": "Этап",
            "actual_end": st.column_config.DateColumn("Дата", format="DD.MM.YYYY"),
            "comments": "Итог / Комментарий"
        }
    )

@st.fragment
def _render_staff_task_grid(disp_df, raw_all, key_prefix):
    """Интерактивная сетка задач сотрудников (0.6 / 0.4)"""
    c_list, c_det = st.columns([0.6, 0.4])
    
    state_key = f"staff_sel_{key_prefix}"
    if state_key not in st.session_state: st.session_state[state_key] = None

    selected_idx = 0

    with c_list:
        st.markdown("<style>div[data-testid='column'] button { margin-top:-2px !important; padding:0 5px !important; height:1.8rem !important; }</style>", unsafe_allow_html=True)
        
        for idx, (i, row) in enumerate(disp_df.iterrows()):
            if st.session_state[state_key] == row['uid']: selected_idx = idx
            
            # Рендер строки
            alert = "⚡ " if row['has_alert'] else ""
            t_icon = "📄" if row['track_type'] == 'bureaucracy' else "💻"
            
            p_name = row['project_name']
            p_display = (p_name[:50] + '..') if len(p_name) > 28 else p_name
            
            s_color = row.get('stage_color') or "#BDC3C7"
            s_txt_color = "white" if s_color.lower() in ["#3498db", "#e74c3c", "#27ae60"] else "#333"
            
            # Цвет срока
            d_bg, d_txt = get_proximity_color(row['planned_end'], mode="deadline")
            
            b_stage = badge_html(f"{row['stage_name']}", s_color, s_txt_color, icon=t_icon)
            b_date = badge_html(f"до {format_date_ru_local(row['planned_end'])}", d_bg, d_txt)

            r_info, r_btn = st.columns([0.88, 0.12])
            with r_info:
                st.markdown(f"**{row['responsible_name']}**: {p_display} {b_stage} {b_date}", unsafe_allow_html=True)
            with r_btn:
                is_active = (st.session_state[state_key] == row['uid'])
                if st.button("➡️", key=f"sbtn_{row['uid']}", type="primary" if is_active else "secondary"):
                    st.session_state[state_key] = None if is_active else row['uid']
                    st.rerun()
            st.markdown("<div style='border-bottom:1px solid #f0f0f0; margin-bottom:8px;'></div>", unsafe_allow_html=True)

    with c_det:
        if st.session_state[state_key]:
            # 🟢 ИСПРАВЛЕНИЕ: Безопасный поиск выбранной строки
            selection_match = disp_df[disp_df['uid'] == st.session_state[state_key]]
            
            if not selection_match.empty:
                # Если задача найдена в текущем (отфильтрованном) списке
                selected_row = selection_match.iloc[0]
                
                # Выравнивание (используем ранее вычисленный индекс)
                st.markdown(f"<div style='height: {selected_idx * 52}px;'></div>", unsafe_allow_html=True)
                
                # Собираем наборы
                items = raw_all[raw_all['uid'] == selected_row['uid']]['info_name'].unique().tolist()
                items_str = ", ".join([str(i) for i in items if i != '—'])

                with st.container(border=True):
                    st.markdown(f"### 🏢 {selected_row['supplier_name']}")
                    st.write(f"**Проект:** {selected_row['project_name']}")
                    st.write(f"🚦 **Статус:** `{selected_row['status']}`")
                    
                    if items_str:
                        st.markdown(f"<div style='background:#f8f9fa; padding:5px; border-radius:4px; font-size:0.85rem;'>📦 {items_str}</div>", unsafe_allow_html=True)
                    
                    st.divider()
                    st.markdown(f'<b>💬 Комментарий:</b><br>{selected_row["comments"] or "—"}', unsafe_allow_html=True)
            else:
                # 🟢 ИСПРАВЛЕНИЕ: Если задача была отфильтрована, сбрасываем выбор
                st.session_state[state_key] = None
                st.info("Выбранная задача скрыта фильтром. Выберите другую задачу из списка.")
        else:
            st.info("Выберите ➡️ для деталей задачи")