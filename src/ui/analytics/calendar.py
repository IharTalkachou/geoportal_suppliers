import streamlit as st
from streamlit_calendar import calendar
import pandas as pd
from datetime import datetime, timedelta
from ui.analytics.data_provider import get_analytics_snapshot

def render_calendar_tab():
    st.subheader("📅 Планировщик событий")
    
    # 1. Загрузка данных
    df = get_analytics_snapshot()
    if df.empty:
        st.info("Нет данных для отображения.")
        return

    # 2. Подготовка данных для календаря (только задачи с датами)
    cal_df = df[df['planned_start'].notna() & df['planned_end'].notna()].copy()
    
    c1, _ = st.columns([2,1])
    with c1:
        show_all = st.checkbox("🔄 Показать завершенные задачи в сетке", value=False, key="cal_filter_done")
    
    display_cal_df = cal_df if show_all else cal_df[cal_df['status'] != 'Выполнено']

    # 3. CSS-ФИКС
    st.markdown("""
        <style>
            iframe[title="streamlit_calendar.calendar"] { min-height: 650px !important; }
        </style>
    """, unsafe_allow_html=True)

    # 4. КАЛЕНДАРЬ В ЭКСПАНДЕРЕ
    with st.expander("🗓️ Открыть календарную сетку", expanded=False):
        _render_calendar_fragment(display_cal_df)

    # 5. ОБНОВЛЕННАЯ АГЕНДА (Срез по дням с просрочками и комментариями)
    st.markdown("---")
    st.subheader("📋 Оперативная повестка (7 дней)")
    
    today_ts = pd.Timestamp.now().normalize()
    active_now_df = df[df['status'].isin(['В работе', 'Ожидание'])].copy()

    for i in range(8):  # Сегодня + 7 дней
        current_day_ts = today_ts + pd.Timedelta(days=i)
        day_str = current_day_ts.strftime('%d.%m.%Y')
        weekday = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][current_day_ts.weekday()]
        
        starts = cal_df[cal_df['planned_start'].dt.normalize() == current_day_ts]
        ends = cal_df[cal_df['planned_end'].dt.normalize() == current_day_ts]
        
        in_progress = active_now_df[
            (active_now_df['actual_start'].dt.normalize() <= current_day_ts) & 
            ((active_now_df['actual_end'].dt.normalize() >= current_day_ts) | (active_now_df['actual_end'].isna()))
        ]

        if not starts.empty or not ends.empty or not in_progress.empty:
            header_prefix = "📌 СЕГОДНЯ" if i == 0 else f"📅 {weekday}"
            evt_count = len(starts) + len(ends)
            
            with st.expander(f"{header_prefix}, {day_str} — событий: {evt_count}, в работе: {len(in_progress)}", expanded=(i==0)):
                
                # Функция для формирования красивой строки задачи
                def format_agenda_row(r, show_overdue_logic=True):
                    # 1. Проверка просрочки
                    is_overdue = False
                    if show_overdue_logic and r['status'] != 'Выполнено' and pd.notna(r['planned_end']):
                        if r['planned_end'].normalize() < today_ts:
                            is_overdue = True
                    
                    # 2. Собираем части строки
                    prefix = "⚡ " if is_overdue else ""
                    icon = "🕒" if r['status'] == 'Ожидание' else "⚙️"
                    resp = f" ({r['responsible_name']})" if r['responsible_name'] else ""
                    
                    overdue_info = ""
                    if is_overdue:
                        overdue_info = f" | **План. конец - {r['planned_end'].strftime('%d.%m.%Y')}**"
                    
                    comment = f" | _{r['comments']}_" if (pd.notna(r['comments']) and r['comments'].strip() != "") else ""
                    
                    return f"{prefix}{icon} {r['project_name']} | {r['stage_name']}{resp}{overdue_info}{comment}"

                # --- 1. Ключевые события ---
                if not starts.empty or not ends.empty:
                    st.markdown("**🎯 Ключевые события дня:**")
                    for _, r in starts.iterrows():
                        st.write(f"🚀 **Старт**: {r['project_name']} | {r['stage_name']}")
                    for _, r in ends.iterrows():
                        st.write(f"🏁 **Дедлайн**: {r['project_name']} | {r['stage_name']}")
                
                # --- 2. Текущие процессы ---
                if not in_progress.empty:
                    if not starts.empty or not ends.empty: st.write("") 
                    st.markdown("**🔥 В процессе исполнения / ожидания:**")
                    
                    for _, r in in_progress.iterrows():
                        # Избегаем дублей, если старт/дедлайн сегодня
                        is_duplicate = (r['project_id'] in starts['project_id'].values) or \
                                       (r['project_id'] in ends['project_id'].values)
                        
                        if not is_duplicate:
                            st.write(format_agenda_row(r))
        
        elif i == 0:
            st.info("На сегодня событий не запланировано.")

@st.fragment
def _render_calendar_fragment(df):
    """Фрагмент для управления календарем без перезагрузки всей страницы"""
    calendar_events = []
    for _, row in df.iterrows():
        detail = row['info_name'] if row['info_name'] != '—' else row['stage_name']
        title = f"{row['project_name']} | {detail}"
        is_done = row['status'] == 'Выполнено'
        color = "#BDC3C7" if is_done else ("#1E88E5" if row['track_type'] == 'bureaucracy' else "#43A047")

        calendar_events.append({
            "title": title,
            "start": row['planned_start'].strftime("%Y-%m-%d"),
            "end": (row['planned_end'] + timedelta(days=1)).strftime("%Y-%m-%d"),
            "color": color,
            "extendedProps": {
                "project": row['project_name'], "supplier": row['supplier_name'],
                "stage": row['stage_name'], "info": row['info_name'],
                "status": row['status'], "resp": row['responsible_name'] or "Не назначен",
                "comm": row['comments'] or "Нет",
                "p_start": row['planned_start'].strftime("%d.%m.%Y"),
                "p_end": row['planned_end'].strftime("%d.%m.%Y"),
                "a_start": row['actual_start'].strftime("%d.%m.%Y") if pd.notna(row['actual_start']) else "Не начато"
            }
        })

    col_cal, col_info = st.columns([0.7, 0.3])
    with col_cal:
        calendar_options = {
            "initialView": "dayGridMonth",
            "headerToolbar": {"left": "prev,next", "center": "title", "right": "today"},
            "locale": "ru", "firstDay": 1, "height": 600
        }
        state = calendar(events=calendar_events, options=calendar_options, key="st_calendar_widget_v4")

    with col_info:
        if state and "eventClick" in state:
            props = state["eventClick"]["event"].get("extendedProps", {})
            with st.container(border=True):
                st.markdown(f"#### 🎯 Детали")
                st.info(f"**{props.get('project')}**")
                st.write(f"📅 **План:** {props.get('p_start')} — {props.get('p_end')}")
                st.write(f"🚦 **Статус:** `{props.get('status')}`")
                st.divider()
                st.write(f"**Этап:** {props.get('stage')}")
                if props.get('info') != '—': st.write(f"**Вид:** {props.get('info')}")
                st.write(f"👤 **Отв.:** {props.get('resp')}")
                st.caption(f"💬 {props.get('comm')}")
        else:
            st.info("💡 Кликните на событие")