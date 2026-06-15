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

    # 2. Фильтрация
    cal_df = df[df['planned_start'].notna() & df['planned_end'].notna()].copy()
    
    c1, _ = st.columns([2,1])
    with c1:
        show_all = st.checkbox("🔄 Показать завершенные задачи", value=False, key="cal_filter_done")
    
    if not show_all:
        cal_df = cal_df[cal_df['status'] != 'Выполнено']

    # 3. CSS-ФИКС для корректной отрисовки внутри экспандера
    st.markdown("""
        <style>
            /* Устанавливаем минимальную высоту для iframe календаря */
            iframe[title="streamlit_calendar.calendar"] { 
                min-height: 650px !important; 
            }
            /* Убираем лишние отступы внутри экспандера для календаря */
            .stExpander > div:first-child > div:nth-child(2) {
                padding: 0.5rem 1rem 1rem 1rem !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # 4. КАЛЕНДАРЬ В ЭКСПАНДЕРЕ
    with st.expander("🗓️ Открыть календарную сетку", expanded=False):
        _render_calendar_fragment(cal_df)

    # 5. АГЕНДА (Список на 7 дней)
    st.markdown("---")
    st.subheader("📋 Ближайшие события (7 дней)")
    
    today = datetime.now().date()
    future_limit = today + timedelta(days=7)
    
    agenda_items = []
    for _, r in cal_df.iterrows():
        # Берем только дату без времени
        p_start = r['planned_start'].date()
        p_end = r['planned_end'].date()
        
        detail = r['info_name'] if r['info_name'] != '—' else r['stage_name']
        title = f"{r['project_name']} | {detail}"
        
        # Добавляем в список, если попадает в окно 7 дней
        if today <= p_start <= future_limit:
            agenda_items.append({"date": p_start, "type": "🚀 Старт", "title": title})
        if today <= p_end <= future_limit:
            agenda_items.append({"date": p_end, "type": "🎯 Дедлайн", "title": title})
    
    if not agenda_items:
        st.info("На ближайшие 7 дней задач не запланировано.")
    else:
        # Сортируем и выводим по дням
        agenda_res = pd.DataFrame(agenda_items).sort_values('date')
        for ev_date, group in agenda_res.groupby('date'):
            with st.expander(f"📅 {ev_date.strftime('%d.%m.%Y')} — событий: {len(group)}", expanded=False):
                for _, item in group.iterrows():
                    st.write(f"**{item['type']}**: {item['title']}")

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
                "project": row['project_name'],
                "supplier": row['supplier_name'],
                "stage": row['stage_name'],
                "info": row['info_name'],
                "status": row['status'],
                "resp": row['responsible_name'] or "Не назначен",
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
            "locale": "ru",
            "firstDay": 1,
            "height": 600
        }
        state = calendar(events=calendar_events, options=calendar_options, key="st_calendar_widget_v2")

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
                if props.get('info') != '—':
                    st.write(f"**Вид:** {props.get('info')}")
                st.write(f"👤 **Отв.:** {props.get('resp')}")
                st.caption(f"💬 {props.get('comm')}")
        else:
            st.info("💡 Кликните на событие")