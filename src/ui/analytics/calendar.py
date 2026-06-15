import streamlit as st
from streamlit_calendar import calendar
import pandas as pd
from datetime import datetime, timedelta
from ui.analytics.data_provider import get_analytics_snapshot

def render_calendar_tab():
    st.subheader("📅 Планировщик событий")
    df = get_analytics_snapshot()
    if df.empty:
        st.info("Нет данных.")
        return

    cal_df = df[df['planned_start'].notna() & df['planned_end'].notna()].copy()
    show_all = st.checkbox("🔄 Показать завершенные задачи", value=False)
    if not show_all:
        cal_df = cal_df[cal_df['status'] != 'Выполнено']

    # 1. КАЛЕНДАРЬ
    with st.expander("🗓️ Просмотр календаря", expanded=False):
        _render_calendar_fragment(cal_df)

    # 2. АГЕНДА (Список ближайших событий)
    st.markdown("---")
    st.subheader("📋 Ближайшие события (7 дней)")
    
    today = datetime.now().date()
    future_limit = today + timedelta(days=7)
    
    # Собираем все точки: и старты, и дедлайны
    agenda_items = []
    for _, r in cal_df.iterrows():
        p_start = r['planned_start'].date()
        p_end = r['planned_end'].date()
        
        detail = r['info_name'] if r['info_name'] != '—' else r['stage_name']
        title = f"{r['project_name']} | {detail}"
        
        if today <= p_start <= future_limit:
            agenda_items.append({"date": p_start, "type": "🚀 Старт", "title": title})
        if today <= p_end <= future_limit:
            agenda_items.append({"date": p_end, "type": "🎯 Дедлайн", "title": title})
    
    if not agenda_items:
        st.info("На ближайшую неделю задач не запланировано.")
    else:
        agenda_res = pd.DataFrame(agenda_items).sort_values('date')
        for ev_date, group in agenda_res.groupby('date'):
            with st.expander(f"📅 {ev_date.strftime('%d.%m.%Y')} — событий: {len(group)}"):
                for _, item in group.iterrows():
                    st.write(f"**{item['type']}**: {item['title']}")

@st.fragment
def _render_calendar_fragment(df):
    """
    Фрагмент кода, который обновляется независимо от всей страницы.
    """
    # Подготовка событий для FullCalendar
    calendar_events = []
    for _, row in df.iterrows():
        # Формируем заголовок
        detail = row['info_name'] if row['info_name'] != '—' else row['stage_name']
        title = f"{row['project_name']} | {detail}"
        
        # Определяем цвет
        is_done = row['status'] == 'Выполнено'
        if is_done:
            color = "#BDC3C7" # Серый для завершенных
        else:
            color = "#1E88E5" if row['track_type'] == 'bureaucracy' else "#43A047"

        calendar_events.append({
            "title": title,
            "start": row['planned_start'].strftime("%Y-%m-%d"),
            # FullCalendar считает дату окончания эксклюзивной, добавляем 1 день
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
            "height": 650,
            "selectable": True,
        }
        
        # Запускаем календарь
        state = calendar(events=calendar_events, options=calendar_options, key="st_calendar_widget")

    with col_info:
        # Если кликнули по событию
        if state and "eventClick" in state:
            props = state["eventClick"]["event"].get("extendedProps", {})
            
            with st.container(border=True):
                st.markdown(f"#### 🎯 Детали задачи")
                st.info(f"**{props.get('project')}**")
                st.caption(f"🏢 {props.get('supplier')}")
                
                st.write(f"📅 **План:** {props.get('p_start')} — {props.get('p_end')}")
                st.write(f"🚦 **Статус:** `{props.get('status')}`")
                st.write(f"⏳ **Факт. начало:** {props.get('a_start')}")
                
                st.divider()
                st.write(f"**Этап:** {props.get('stage')}")
                if props.get('info') != '—':
                    st.write(f"**Вид:** {props.get('info')}")
                
                st.write(f"👤 **Ответственный:** {props.get('resp')}")
                
                with st.expander("📝 Комментарий"):
                    st.write(props.get('comm'))
        else:
            st.info("💡 Выберите событие в календаре для просмотра деталей.")