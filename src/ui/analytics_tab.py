import streamlit as st
from sqlalchemy import text
from sqlalchemy.orm import Session
from config.database import engine
from config.cache import query_db


# Импортируем наши новые модули
from ui.analytics.data_provider import get_analytics_snapshot, clear_analytics_cache
from ui.analytics.kpi_logic import render_kpi_tab
from ui.analytics.calendar import render_calendar_tab
from ui.analytics.progress_math import render_traffic_light_chart
from ui.analytics.staff import render_staff_tab
from ui.analytics.heatmap import render_heatmap_tab
from ui.analytics.reports import render_reports_tab
from ui.analytics.report_docx import render_monthly_report_tab

def render_analytics_tab(user_role="user"):
    """Главная точка входа вкладки Аналитика"""
    
    # 1. ШАПКА И ОБНОВЛЕНИЕ
    col_h, col_ref = st.columns([0.8, 0.2])
    with col_ref:
        if st.button("🔄 Обновить данные", width='stretch'):
            clear_analytics_cache()
            st.rerun()
    
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
        render_staff_tab()

    elif choice == "🌡️ Матрицы рисков":
        _render_heatmap_router()

    elif choice == "📄 Отчёты":
        render_reports_tab()

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
    """Обновленная логика синхронизации просрочек с поддержкой JSONB и единой таблицы этапов"""
    
    # 1. Запрос для Бюрократии (Категория 1)
    query_buro = """
        INSERT INTO overdue_log (source_table, stage_progress_id, supplier_name, project_name, stage_name, responsible_name, planned_start, planned_end, actual_start, comments)
        SELECT 'project_stages', ps.stage_progress_id, s.supplier_name, p.project_name, stg.stage_name, u.display_name, ps.planned_start, ps.planned_end, ps.actual_start, ps.comments
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE ps.actual_end IS NULL 
          AND ps.planned_end < CURRENT_DATE 
          AND stg.track_category = '1. Документарный'
          AND p.is_agreement_project = TRUE
        ON CONFLICT (source_table, stage_progress_id) DO NOTHING
    """
    
    # 2. Запрос для Технологии (Категория 2) с вытягиванием названий наборов из массива JSONB
    query_tech = """
        INSERT INTO overdue_log (source_table, stage_progress_id, supplier_name, project_name, info_name, stage_name, responsible_name, planned_start, planned_end, actual_start, comments)
        SELECT 
            'project_stages', 
            ps.stage_progress_id, 
            s.supplier_name, 
            p.project_name, 
            (
                SELECT STRING_AGG(it_inner.info_name, ', ')
                FROM project_items pi_inner
                JOIN info_types it_inner ON pi_inner.info_id = it_inner.info_id
                WHERE pi_inner.item_id IN (
                    SELECT jsonb_array_elements_text(ps.affected_item_ids)::int
                )
            ) as info_name,
            stg.stage_name, 
            u.display_name, 
            ps.planned_start, 
            ps.planned_end, 
            ps.actual_start, 
            ps.comments
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE ps.actual_end IS NULL 
          AND ps.planned_end < CURRENT_DATE 
          AND stg.track_category = '2. Технологический'
        ON CONFLICT (source_table, stage_progress_id) DO NOTHING
    """
    
    try:
        with Session(engine) as session:
            session.execute(text(query_buro))
            session.execute(text(query_tech))
            session.commit()
    except Exception as e:
        st.error(f"Ошибка синхронизации лога: {e}") # Для отладки, если нужно
        pass

def _render_heatmap_router():
    """Обновленный роутер: Светофор + Тепловые карты"""
    
    # Теперь мы используем Segmented Control для переключения ВНУТРИ раздела
    hm_choice = st.segmented_control(
        "Вид матрицы",
        options=["🚦 Светофор (Прогресс)", "🌡️ Детальные карты задержек"],
        default="🚦 Светофор (Прогресс)",
        key="hm_internal_nav",
        label_visibility="collapsed"
    )
    st.markdown("<br>", unsafe_allow_html=True)

    df = get_analytics_snapshot()

    if hm_choice == "🚦 Светофор (Прогресс)":
        render_traffic_light_chart(df)
    else:
        # Вызов нашего нового файла
        render_heatmap_tab()