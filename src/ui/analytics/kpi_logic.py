import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ui.analytics.data_provider import get_analytics_snapshot

# --- ЛОКАЛЬНЫЕ ХЕЛПЕРЫ ---
def format_date_ru_local(d):
    if not d: return "—"
    months = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    return f"{d.day} {months[d.month-1]} {d.year}"

def badge_html(text, bg_color="#E0E0E0", text_color="#333", icon=""):
    # Добавлена поддержка иконки перед текстом
    prefix = f"{icon} " if icon else ""
    return (f'<span style="background-color:{bg_color};color:{text_color};'
            f'padding:2px 10px;border-radius:4px;font-size:0.7rem;font-weight:700;'
            f'display:inline-block;margin-left:5px;border:1px solid rgba(0,0,0,0.1);'
            f'white-space:nowrap;">{prefix}{text}</span>')

def get_proximity_color(target_date, mode="deadline"):
    if pd.isna(target_date): return "#BDC3C7", "#333"
    today = datetime.now().date()
    diff = (target_date.date() - today).days
    if mode == "deadline":
        if diff <= 0: return "#E74C3C", "white"
        if diff <= 3: return "#E67E22", "white"
        if diff <= 7: return "#F1C40F", "#333"
        return "#3498DB", "white"
    else:
        if diff < 0: return "#922B21", "white"
        if diff <= 7: return "#27AE60", "white"
        if diff <= 30: return "#1E8449", "white"
        return "#145A32", "white"

def render_kpi_tab():
    raw_df = get_analytics_snapshot()
    if raw_df.empty:
        st.info("Нет активных данных."); return

    # Подготовка данных
    raw_df['uid'] = raw_df.apply(lambda x: f"{x['project_id']}_{x['track_type']}_{x['stage_code']}_{x['iteration_count']}", axis=1)
    df_unique = raw_df.drop_duplicates(subset=['uid']).copy()
    active_df = df_unique[~df_unique['status'].isin(['Выполнено', 'Отменено'])].copy()

    # Распределение
    g_work = active_df[active_df['status'].isin(['В работе', 'Просрочено'])].copy()
    g_wait = active_df[active_df['status'] == 'Ожидание'].copy()
    g_hold = active_df[active_df['status'].isin(['Отложено', 'Планируется'])].copy()

    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("🔥 В работе")
        _render_smart_group(g_work, raw_df, "work", is_planned=False)
        st.write("<div style='margin-top:20px'></div>", unsafe_allow_html=True)
        st.divider()
        st.subheader("⏳ Отложено / План")
        _render_smart_group(g_hold, raw_df, "hold", is_planned=True)
    with col_right:
        st.subheader("📨 Ожидание")
        _render_smart_group(g_wait, raw_df, "wait", is_planned=False)

def _render_smart_group(df_group, raw_all, key_prefix, is_planned=False):
    if df_group.empty:
        st.caption("Задач нет"); return

    @st.fragment
    def _list_fragment():
        c_list, c_det = st.columns([0.6, 0.4])
        state_key = f"sel_uid_{key_prefix}"
        if state_key not in st.session_state: st.session_state[state_key] = None

        selected_index = 0 # Для расчета отступа

        with c_list:
            st.markdown("<style>div[data-testid='column'] button { margin-top:-2px !important; padding:0 5px !important; height:1.8rem !important; }</style>", unsafe_allow_html=True)

            for idx, (i, row) in enumerate(df_group.iterrows()):
                # Запоминаем позицию выбранного элемента
                if st.session_state[state_key] == row['uid']:
                    selected_index = idx

                # 1. Ограничение названия
                p_name = row['project_name']
                p_display = (p_name[:27] + '...') if len(p_name) > 30 else p_name
                
                # 2. Иконка трека
                track_icon = "📄" if row['track_type'] == 'bureaucracy' else "💻"
                
                # 3. Цвета
                s_color = row.get('stage_color') or "#BDC3C7"
                s_text_color = "white" if s_color.lower() in ["#3498db", "#e74c3c", "#27ae60", "#6c3483", "#2c3e50"] else "#333"
                target_dt = row['planned_start'] if is_planned else row['planned_end']
                d_bg, d_txt = get_proximity_color(target_dt, mode="start" if is_planned else "deadline")
                
                # Бейдж с иконкой
                b_stage = badge_html(f"{row['stage_name']} (ит.{int(row['iteration_count'])})", s_color, s_text_color, icon=track_icon)
                prefix_dt = "с " if is_planned else "до "
                b_date = badge_html(f"{prefix_dt}{format_date_ru_local(target_dt)}", d_bg, d_txt)

                r_info, r_btn = st.columns([0.88, 0.12])
                with r_info:
                    st.markdown(f"**{p_display}** {b_stage} {b_date}", unsafe_allow_html=True)
                with r_btn:
                    # ПОДСВЕТКА И ЛОГИКА ПЕРЕКЛЮЧЕНИЯ (Toggle)
                    is_active = (st.session_state[state_key] == row['uid'])
                    if st.button("➡️", key=f"btn_{row['uid']}", type="primary" if is_active else "secondary"):
                        # Если нажат уже активный проект — закрываем (ставим None), иначе открываем новый
                        st.session_state[state_key] = None if is_active else row['uid']
                        st.rerun()
                st.markdown("<div style='border-bottom:1px solid #f0f0f0; margin-bottom:8px;'></div>", unsafe_allow_html=True)

        with c_det:
            if st.session_state[state_key]:
                # ВЫРАВНИВАНИЕ: Создаем пустой блок, высота которого зависит от индекса строки
                # Примерная высота строки списка с учетом разделителя ~52px
                offset = selected_index * 52
                st.markdown(f"<div style='height: {offset}px;'></div>", unsafe_allow_html=True)

                # Сами детали
                selected_row = df_group[df_group['uid'] == st.session_state[state_key]].iloc[0]
                s_color = selected_row.get('stage_color') or "#BDC3C7"
                related_items = raw_all[raw_all['uid'] == selected_row['uid']]['info_name'].unique().tolist()
                items_str = ", ".join([str(i) for i in related_items if i != '—'])

                with st.container(border=True):
                    st.markdown(f"### 🏢 {selected_row['supplier_name']}")
                    st.caption(f"Проект: {selected_row['project_name']}")
                    
                    if not is_planned:
                        val = format_date_ru_local(selected_row['actual_start']) if pd.notna(selected_row['actual_start']) else "не начато"
                        st.write(f"🚀 **Фактическое начало:** {val}")
                    else:
                        val = format_date_ru_local(selected_row['planned_end']) if pd.notna(selected_row['planned_end']) else "—"
                        st.write(f"🎯 **Плановое завершение:** {val}")
                    
                    st.divider()
                    st.write(f"👤 **Ответственный:** {selected_row['responsible_name'] or '—'}")
                    if items_str: st.caption(f"📦 Состав: {items_str}")
                    st.markdown(f'<div style="margin-top:10px; padding:10px; background:#f9f9f9; border-left:4px solid {s_color};">'
                                f'<b>💬 Комментарий:</b><br>{selected_row["comments"] or "—"}</div>', 
                                unsafe_allow_html=True)
            else:
                st.info("Выберите ➡️ для просмотра деталей")

    _list_fragment()