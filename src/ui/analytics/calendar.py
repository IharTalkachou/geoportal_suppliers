import streamlit as st
from streamlit_calendar import calendar
import pandas as pd
from datetime import datetime
from ui.analytics.data_provider import get_analytics_snapshot
from ui.analytics.kpi_logic import badge_html, format_date_ru_local

# --- ЛОКАЛЬНАЯ ЛОГИКА SLA ---
def check_sla_alert(row):
    today = datetime.now().date()
    status, code = row['status'], row['stage_code']
    p_end = row['planned_end'].date() if pd.notna(row['planned_end']) else None
    a_start = row['actual_start'].date() if pd.notna(row['actual_start']) else None
    if status == 'В работе': return bool(p_end and today >= p_end)
    if status == 'Ожидание':
        if not a_start: return False
        sla = 2 if code in ['TECH_REG_PROC', 'META_REJECT', 'DATA_REJECT'] else 10 if code in ['META_CHECK', 'DATA_CHECK'] else 5 if code in ['TECH_REG_WAIT', 'META_FIX', 'DATA_FIX'] else 7
        return (today - a_start).days >= sla
    return status == 'Просрочено'

def render_calendar_tab():
    df_raw = get_analytics_snapshot()
    if df_raw.empty:
        st.info("Нет активных данных."); return

    # 1. ПОДГОТОВКА UID И МАППИНГА НАБОРОВ
    df_raw['uid'] = df_raw.apply(lambda x: f"{x['project_id']}_{x['track_type']}_{x['stage_code']}_{x['iteration_count']}", axis=1)
    items_map = df_raw.groupby('uid')['info_name'].apply(lambda x: ", ".join([v for v in x.unique() if v != '—'])).to_dict()
    df_unique = df_raw.drop_duplicates(subset=['uid']).copy()

    def get_event_info(row):
        if row['status'] == 'Планируется': return row['planned_start'], "🚀 Старт", "#27AE60"
        if row['status'] in ['В работе', 'Ожидание', 'Просрочено']: return row['planned_end'], "🏁 Дедлайн", "#E74C3C"
        return None, None, None

    df_unique[['event_date', 'event_label', 'event_color']] = df_unique.apply(lambda r: pd.Series(get_event_info(r)), axis=1)
    events_only = df_unique[df_unique['event_date'].notna() & (df_unique['status'] != 'Выполнено')].copy()

    # 2. СОСТОЯНИЕ
    if "cal_date" not in st.session_state:
        st.session_state.cal_date = datetime.now().strftime("%Y-%m-%d")
    
    # 3. ВЕРСТКА
    col_grid, col_agenda = st.columns([0.6, 0.4])

    with col_grid:
        _render_calendar_component(events_only)

    with col_agenda:
        _render_dynamic_agenda(st.session_state.cal_date, events_only, df_raw, items_map)

@st.fragment
def _render_calendar_component(events_df):
    calendar_events = []
    for _, row in events_df.iterrows():
        d_str = row['event_date'].strftime("%Y-%m-%d")
        calendar_events.append({
            "title": f"{row['project_name'][:15]}..",
            "start": d_str, "end": d_str, "color": row['event_color'],
            "allDay": True, "extendedProps": {"uid": row['uid'], "date": d_str}
        })

    calendar_options = {
        "initialView": "dayGridMonth", "locale": "ru", "firstDay": 1, "height": 650,
        "headerToolbar": {"left": "prev,next today", "center": "title", "right": ""},
        "selectable": True,
    }

    st.markdown("""
        <style>
            .fc-event { border-radius: 4px !important; padding: 2px 4px !important; font-size: 0.7rem !important; border: none !important; cursor: pointer !important; }
            .fc-event-title { font-weight: 600 !important; color: white !important; }
        </style>
    """, unsafe_allow_html=True)

    state = calendar(events=calendar_events, options=calendar_options, key="control_calendar_v12_final")

    # --- 🛡️ ИСПРАВЛЕНИЕ СДВИГА ДАТЫ (СМЕЩЕНИЕ ПОЛУДНЕМ) ---
    new_date = None
    if state.get("dateClick"):
        # Если пришло 2026-06-30T21:00:00... добавим 6 часов и получим 2026-07-01 03:00:00
        raw_val = state["dateClick"]["date"]
        new_date = (pd.to_datetime(raw_val).tz_localize(None) + pd.Timedelta(hours=6)).strftime("%Y-%m-%d")
    elif state.get("eventClick"):
        new_date = state["eventClick"]["event"]["extendedProps"]["date"]

    if new_date and st.session_state.cal_date != new_date:
        st.session_state.cal_date = new_date
        st.rerun()

def _render_dynamic_agenda(selected_date_str, events_df, all_df_raw, items_map):
    # Также применяем смещение для отображения заголовка, чтобы не было "вчера"
    sel_date = (pd.to_datetime(selected_date_str) + pd.Timedelta(hours=6)).date()
    
    st.markdown(f"### 📅 {format_date_ru_local(sel_date)}")
    
    day_events = events_df[events_df['event_date'].dt.date == sel_date]
    st.markdown("##### 🎯 События этого дня")
    
    if day_events.empty:
        st.caption("Событий не запланировано.")
    else:
        for _, r in day_events.iterrows():
            t_icon = "📄" if r['track_type'] == 'bureaucracy' else "💻"
            s_color = r.get('stage_color') or "#BDC3C7"
            items_str = items_map.get(r['uid'], "")
            with st.container(border=True):
                st.markdown(f"**{r['project_name']}**")
                st.markdown(f"{r['event_label']} {t_icon} {badge_html(r['stage_name'], s_color, 'white')}", unsafe_allow_html=True)
                if items_str: st.markdown(f"<div style='font-size:0.8rem; margin: 4px 0;'>📦 {items_str}</div>", unsafe_allow_html=True)
                comm = r['comments'] if r['comments'] else "—"
                st.markdown(f'<div style="font-size:0.85rem; color:#444;">💬 {comm}</div>', unsafe_allow_html=True)

    st.write("")
    if st.toggle("Показать задачи в процессе", key="show_proc"):
        st.markdown("##### ⚙️ Текущая работа")
        in_progress = all_df_raw[
            (all_df_raw['status'].isin(['В работе', 'Ожидание', 'Просрочено'])) &
            (all_df_raw['actual_start'].dt.date <= sel_date) &
            ((all_df_raw['actual_end'].dt.date > sel_date) | (all_df_raw['actual_end'].isna()))
        ].drop_duplicates(subset=['uid']).copy()

        if in_progress.empty:
            st.caption("Активных задач нет.")
        else:
            for _, r in in_progress.iterrows():
                alert = "⚡ " if check_sla_alert(r) else ""
                t_icon = "📄" if r['track_type'] == 'bureaucracy' else "💻"
                s_color = r.get('stage_color') or "#BDC3C7"
                items_str = items_map.get(r['uid'], "")
                with st.container(border=True):
                    st.markdown(f"{alert}{t_icon} **{r['project_name']}**")
                    st.markdown(f"{badge_html(r['stage_name'], s_color, 'white')} {badge_html(r['status'], '#F0F0F0', '#333')}", unsafe_allow_html=True)
                    if items_str: st.markdown(f"<div style='font-size:0.8rem; margin-top:2px;'>📦 {items_str}</div>", unsafe_allow_html=True)
                    if r['comments']: st.markdown(f'<div style="font-size:0.82rem; color:#666; margin-top:4px;">💬 {r["comments"]}</div>', unsafe_allow_html=True)