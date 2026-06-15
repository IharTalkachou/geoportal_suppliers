import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from ui.analytics.data_provider import get_analytics_snapshot
from config.cache import query_db

TODAY = datetime.now().date()

def render_kpi_tab():
    df = get_analytics_snapshot()
    if df.empty:
        st.info("Нет данных.")
        return

    # --- 1. ЛОГИКА АЛЕРТОВ (⚡) ---
    def calc_alert(row):
        p_end = row['planned_end'].date() if pd.notna(row['planned_end']) else None
        a_start = row['actual_start'].date() if pd.notna(row['actual_start']) else None
        if row['status'] == 'В работе':
            return bool(p_end and TODAY >= p_end)
        if row['status'] == 'Ожидание':
            return bool(a_start and (TODAY - a_start).days >= 7)
        return False

    df['has_alert'] = df.apply(calc_alert, axis=1)
    # Формируем имя для таблицы
    df['display_name'] = df.apply(lambda x: f"⚡ {x['project_name']}" if x['has_alert'] else x['project_name'], axis=1)

    # --- 2. ГРУППИРОВКА ---
    active_df = df[~df['status'].isin(['Выполнено', 'Отменено'])].copy()
    
    # Для KPI мы должны показывать только один "самый важный" статус на проект в каждой категории
    # Но если в проекте 2 активных трека - они оба должны быть видны.
    
    g_work = active_df[active_df['status'] == 'В работе'].sort_values('has_alert', ascending=False)
    g_wait = active_df[active_df['status'] == 'Ожидание'].sort_values('has_alert', ascending=False)
    g_hold = active_df[active_df['status'].isin(['Отложено', 'Планируется'])]

    # --- 3. ВЕРХНИЙ РЯД МЕТРИК ---
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(f"{'⚡ ' if g_work['has_alert'].any() else ''}В работе", len(g_work))
    with c2:
        st.metric(f"{'⚡ ' if g_wait['has_alert'].any() else ''}Ожидание", len(g_wait))
    with c3:
        st.metric("Отложено / План", len(g_hold))

    # --- 4. ОСНОВНЫЕ СПИСКИ (РАБОТА) ---
    e1, e2, e3 = st.columns(3)
    with e1:
        with st.expander("Список (Работа)", expanded=False):
            _draw_side_by_side_details(g_work, "kpi_work")
    with e2:
        with st.expander("Список (Ожидание)", expanded=False):
            _draw_side_by_side_details(g_wait, "kpi_wait")
    with e3:
        with st.expander("Список (План)", expanded=False):
            _draw_side_by_side_details(g_hold, "kpi_hold")

    st.markdown("---")

    # --- 5. ТЕХНИЧЕСКАЯ РАБОТА ---
    # Логика: Технологические этапы, где 'Публикация' еще не 'Выполнена'
    # В нашей модели Snapshot это легко:
    tech_active = active_df[active_df['track_type'] == 'tech'].copy()
    
    st.metric("⚙️ Текущая техническая работа", len(tech_active))
    with st.expander("Детализация технической работы", expanded=False):
        if not tech_active.empty:
            # Убрали поставщика, добавили комментарии + маски
            st.dataframe(
                tech_active[['project_name', 'info_name', 'stage_name', 'status', 'actual_start', 'comments']], 
                width="stretch", hide_index=True,
                column_config={
                    "project_name": "Проект", "info_name": "Вид сведений",
                    "stage_name": "Стадия", "status": "Статус",
                    "actual_start": st.column_config.DateColumn("Старт", format="DD.MM.YYYY"), # 👈 Явный формат
                    "comments": "Комментарий"
                }
            )
        else: st.info("Нет активных технических задач.")

    # --- 6. ДЕДЛАЙНЫ 7 ДНЕЙ ---
    soon_df = active_df[
        (active_df['planned_end'].dt.date >= TODAY) & 
        (active_df['planned_end'].dt.date <= TODAY + timedelta(days=7))
    ].sort_values('planned_end')
    
    st.metric("📅 Дедлайны ≤7 дней", len(soon_df))
    with st.expander("Задачи с близким дедлайном", expanded=False):
        if not soon_df.empty:
            # Добавили комментарии + маски
            st.dataframe(
                soon_df[['project_name', 'stage_name', 'planned_end', 'responsible_name', 'comments']], 
                width="stretch", hide_index=True,
                column_config={
                    "project_name": "Проект", "stage_name": "Этап",
                    "planned_end": st.column_config.DateColumn("Дедлайн", format="DD.MM.YYYY"), # 👈 Явный формат
                    "responsible_name": "Ответственный",
                    "comments": "Комментарий"
                }
            )
        else: st.info("Нет близких дедлайнов.")

    # --- 7. ИСТОРИЯ ПРОСРОЧЕК ---
    st.markdown("#### 🚨 История зафиксированных просрочек")
    p_choice = st.selectbox("Период совершения просрочки:", ["Все время", "Текущая неделя", "Текущий месяц", "Год"], key="ov_sel")
    
    # Тут запрос идет к спец. таблице логов
    q_overdue = "SELECT supplier_name, project_name, stage_name, planned_end, responsible_name FROM overdue_log"
    if p_choice != "Все время":
        imap = {"Текущая неделя": "week", "Текущий месяц": "month", "Год": "year"}
        q_overdue += f" WHERE planned_end >= date_trunc('{imap[p_choice]}', now())"
    
    ov_data = query_db(q_overdue + " ORDER BY planned_end DESC")
    st.metric("Всего просрочек", len(ov_data))
    with st.expander("Просмотр истории просрочек", expanded=False):
        st.dataframe(ov_data, width="stretch", hide_index=True)

def _draw_side_by_side_details(df_group, key_prefix):
    """Компоновка: Таблица (45%) | Детали (55%)"""
    if df_group.empty:
        st.caption("Нет данных")
        return

    c_list, c_det = st.columns([0.45, 0.55])
    
    with c_list:
        selection = st.dataframe(
            df_group[['display_name']], 
            width="stretch", hide_index=True, 
            on_select="rerun", selection_mode="single-row",
            key=f"{key_prefix}_tbl",
            column_config={"display_name": "Проект"}
        )

    with c_det:
        rows = selection.get("selection", {}).get("rows", [])
        if rows:
            row = df_group.iloc[rows[0]]
            with st.container(border=True):
                st.markdown(f"**{row['project_name']}**")
                st.caption(f"🏢 {row['supplier_name']}")
                st.write(f"📅 План: {row['planned_end'].strftime('%d.%m.%Y') if pd.notna(row['planned_end']) else '—'}")
                st.write(f"🚦 Статус: `{row['status']}`")
                st.divider()
                st.write(f"**Этап:** {row['stage_name']}")
                if row['info_name'] != '—':
                    st.write(f"**Вид:** {row['info_name']}")
                st.write(f"👤 **Ответственный:** {row['responsible_name'] or '—'}")
                st.info(row['comments'] or "Нет комментария")
        else:
            st.info("Выберите проект")