import streamlit as st
from sqlalchemy import text
from sqlalchemy.orm import Session
from config.database import engine
from config.cache import query_db

# Импортируем наши новые модули
from ui.analytics.data_provider import get_analytics_snapshot
from ui.analytics.kpi_logic import render_kpi_tab
from ui.analytics.calendar import render_calendar_tab
from ui.analytics.progress_math import render_traffic_light_chart

def render_analytics_tab(user_role="user"):
    """Главная точка входа вкладки Аналитика"""
    
    # 1. СИНХРОНИЗАЦИЯ (Один раз при загрузке вкладки)
    with st.spinner("Синхронизация данных..."):
        _sync_overdue_log_internal()

    # 2. ПОД-НАВИГАЦИЯ (Segmented Control)
    # Используем ключ для сохранения состояния при переключении глобальных вкладок
    choice = st.segmented_control(
        "Разделы аналитики",
        options=["🎯 KPI", "📅 Календарь", "👥 Сотрудники", "🌡️ Матрицы рисков", "📄 Отчёты"],
        default="🎯 KPI",
        key="analytics_sub_nav",
        label_visibility="collapsed"
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # 3. РОУТИНГ (Вызов соответствующих модулей)
    if choice == "🎯 KPI":
        render_kpi_tab()

    elif choice == "📅 Календарь":
        render_calendar_tab()

    elif choice == "👥 Сотрудники":
        # Пока оставляем старую функцию здесь, позже вынесем в staff.py
        _render_team_performance_legacy()

    elif choice == "🌡️ Матрицы рисков":
        _render_heatmap_router()

    elif choice == "📄 Отчёты":
        # Пока оставляем старую функцию здесь, позже вынесем в reports.py
        _render_reports_legacy()

# ==========================================
# ВНУТРЕННИЕ ФУНКЦИИ (ВРЕМЕННОЕ ЖИЛЬЕ)
# ==========================================

def _render_heatmap_router():
    """Роутер для тепловых карт и светофора"""
    st.markdown("### 🌡️ Матрицы рисков и Прогресс")
    
    # Загружаем данные через провайдер для Светофора
    df = get_analytics_snapshot()
    
    modes = ["🚦 Светофор (Прогресс)", "⚖️ Юридический трек", "⚙️ Технический трек"]
    mode = st.radio("Выберите срез анализа:", modes, horizontal=True, key="hm_mode_sel_new")

    if mode == modes[0]:
        # ВЫЗОВ НОВОЙ ИСПРАВЛЕННОЙ МАТЕМАТИКИ
        render_traffic_light_chart(df)
    else:
        st.info("Разработка детальных тепловых карт в процессе переноса в новую модель...")
        # Здесь в будущем будет вызов heatmap_logic.render_heatmap(track)

def _sync_overdue_log_internal():
    """Перенесенная логика синхронизации просрочек"""
    query_buro = """
        INSERT INTO overdue_log (source_table, stage_progress_id, supplier_name, project_name, stage_name, responsible_name, planned_start, planned_end, actual_start, comments)
        SELECT 'project_stages', ps.stage_progress_id, s.supplier_name, p.project_name, stg.stage_name, u.display_name, ps.planned_start, ps.planned_end, ps.actual_start, ps.comments
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE ps.actual_end IS NULL AND ps.planned_end < CURRENT_DATE AND p.is_agreement_project = TRUE
        ON CONFLICT (source_table, stage_progress_id) DO NOTHING
    """
    query_tech = """
        INSERT INTO overdue_log (source_table, stage_progress_id, supplier_name, project_name, info_name, stage_name, responsible_name, planned_start, planned_end, actual_start, comments)
        SELECT 'item_stages', ist.stage_progress_id, s.supplier_name, p.project_name, it.info_name, stg.stage_name, u.display_name, ist.planned_start, ist.planned_end, ist.actual_start, ist.comments
        FROM item_stages ist
        JOIN project_items pi ON ist.item_id = pi.item_id
        JOIN projects p ON pi.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN info_types it ON pi.info_id = it.info_id
        JOIN stages stg ON ist.stage_id = stg.stage_id
        LEFT JOIN users u ON ist.responsible_id = u.user_id
        WHERE ist.actual_end IS NULL AND ist.planned_end < CURRENT_DATE
        ON CONFLICT (source_table, stage_progress_id) DO NOTHING
    """
    try:
        with Session(engine) as session:
            session.execute(text(query_buro))
            session.execute(text(query_tech))
            session.commit()
    except: pass

def _render_team_performance_legacy():
    st.info("Раздел 'Работа сотрудников' находится на рефакторинге. Используйте Календарь для контроля дедлайнов.")

def _render_reports_legacy():
    st.info("Раздел 'Отчёты' находится на рефакторинге.")