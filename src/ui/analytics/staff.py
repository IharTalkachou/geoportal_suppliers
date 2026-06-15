import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ui.analytics.data_provider import get_analytics_snapshot

def render_staff_tab():
    st.subheader("👥 Оперативный контроль и нагрузка сотрудников")
    
    # 1. Получаем данные
    df = get_analytics_snapshot()
    if df.empty:
        st.info("Нет данных для анализа.")
        return

    # Разделяем данные
    active_base = df[df['status'].isin(['В работе', 'Ожидание', 'Планируется'])].copy()
    done_base = df[df['status'] == 'Выполнено'].copy()

    # ==========================================
    # ЭКСПАНДЕР 1: ЗАДАЧИ В РАБОТЕ
    # ==========================================
    with st.expander("🔥 Задачи в работе", expanded=False):
        
        c1, c2 = st.columns(2)
        
        with c1:
            # 1. Фильтр по микростатусу
            available_statuses = sorted(active_base['status'].unique().tolist())
            sel_statuses = st.multiselect(
                "Фильтр по статусу:", 
                options=available_statuses,
                default=available_statuses,
                key="staff_active_status_filter"
            )
        
        # Предварительная фильтрация для списка сотрудников
        active_filtered_by_status = active_base[active_base['status'].isin(sel_statuses)]
        
        with c2:
            # 2. Фильтр по сотрудникам (зависит от выбранных статусов)
            staff_stats = active_filtered_by_status.groupby("responsible_name").size().reset_index(name="count")
            staff_options = [f"{r['responsible_name']} | {r['count']} задач" for _, r in staff_stats.iterrows()]
            
            sel_staff = st.multiselect(
                "Фильтр по сотрудникам:", 
                options=staff_options, 
                placeholder="Все исполнители",
                key="staff_active_load_filter"
            )

        # Итоговая фильтрация активных задач
        display_active = active_filtered_by_status.copy()
        if sel_staff:
            selected_names = [s.split(" | ")[0] for s in sel_staff]
            display_active = display_active[display_active["responsible_name"].isin(selected_names)]

        if display_active.empty:
            st.info("Задачи с выбранными параметрами не найдены.")
        else:
            # Вызов фрагмента для сетки (Таблица + Карточка)
            _render_active_tasks_grid(display_active)


    # ==========================================
    # ЭКСПАНДЕР 2: ВЫПОЛНЕННЫЕ ЗАДАЧИ
    # ==========================================
    with st.expander("✅ Выполненные задачи", expanded=False):
        
        c3, c4 = st.columns(2)
        
        with c3:
            period = st.selectbox(
                "Период завершения:", 
                ["Все время", "Текущая неделя", "Текущий месяц", "Год"], 
                key="staff_done_period"
            )
        
        # Логика дат
        today = datetime.now()
        if period == "Текущая неделя":
            start_date = today - timedelta(days=today.weekday())
        elif period == "Текущий месяц":
            start_date = today.replace(day=1)
        elif period == "Год":
            start_date = today.replace(month=1, day=1)
        else:
            start_date = datetime(2000, 1, 1)

        # Фильтруем по периоду ПЕРЕД выбором сотрудника
        done_in_period = done_base[done_base['actual_end'] >= pd.Timestamp(start_date)].copy()
        
        with c4:
            # Список сотрудников, кто реально ЧТО-ТО СДАЛ в этот период
            done_staff_list = sorted(done_in_period['responsible_name'].unique().tolist())
            sel_done_staff = st.multiselect(
                "Фильтр по сотрудникам:",
                options=done_staff_list,
                placeholder="Все сотрудники",
                key="staff_done_person_filter"
            )

        # Итоговая фильтрация выполненных
        display_done = done_in_period.copy()
        if sel_done_staff:
            display_done = display_done[display_done["responsible_name"].isin(sel_done_staff)]

        if display_done.empty:
            st.info("Выполненных задач за этот период не найдено.")
        else:
            st.dataframe(
                display_done[['responsible_name', 'project_name', 'stage_name', 'actual_end', 'comments']],
                width="stretch", hide_index=True,
                column_config={
                    "responsible_name": "Сотрудник",
                    "project_name": "Проект",
                    "stage_name": "Этап",
                    "actual_end": st.column_config.DateColumn("Дата финиша", format="DD.MM.YYYY"),
                    "comments": "Комментарий"
                }
            )

@st.fragment
def _render_active_tasks_grid(df):
    """Фрагмент для детального просмотра активных задач (без моргания страницы)"""
    col_list, col_card = st.columns([0.45, 0.55])
    
    with col_list:
        list_df = df[['responsible_name', 'project_name', 'status']].copy()
        # Для таблицы объединяем имя и проект, чтобы было наглядно
        list_df['display_name'] = list_df['responsible_name'] + ": " + list_df['project_name']
        
        selection = st.dataframe(
            list_df[['display_name', 'status']],
            width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            key="staff_active_selector_fragment",
            column_config={
                "display_name": "Исполнитель и проект",
                "status": "Статус"
            }
        )

    with col_card:
        rows = selection.get("selection", {}).get("rows", [])
        if rows:
            row = df.iloc[rows[0]]
            with st.container(border=True):
                st.markdown(f"#### {row['project_name']}")
                st.write(f"👤 **Ответственный:** {row['responsible_name']}")
                st.write(f"🚦 **Микростатус:** `{row['status']}`")
                
                p_start = row['planned_start'].strftime('%d.%m.%Y') if pd.notna(row['planned_start']) else '—'
                p_end = row['planned_end'].strftime('%d.%m.%Y') if pd.notna(row['planned_end']) else '—'
                st.write(f"📅 **Сроки по плану:** {p_start} — {p_end}")
                
                st.divider()
                st.write(f"**Этап:** {row['stage_name']}")
                if row['info_name'] != '—':
                    st.write(f"📦 **Вид сведений:** {row['info_name']}")
                
                st.write("**Комментарий:**")
                st.info(row['comments'] or "Нет комментария")
        else:
            st.info("💡 Выберите задачу в списке слева")