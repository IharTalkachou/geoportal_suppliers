import streamlit as st
from streamlit_calendar import calendar
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session
from config.cache import query_db, clear_cache
from config.database import engine  # 👈 Импортируем существующий движок
import plotly.express as px
import plotly.graph_objects as go
import io
from datetime import datetime, timedelta
from ui.shared_components import render_survey_viewer
import time
from datetime import datetime, timedelta

# ==========================================
# 🔄 СЕРВИСНЫЕ ФУНКЦИИ
# ==========================================

def sync_overdue_log():
    """
    Автоматически фиксирует просроченные этапы в таблицу overdue_log.
    Создает 'снимок' данных на момент совершения просрочки.
    """
    # 1. Запрос для Бюрократии (Проекты первичного подключения)
    query_buro = """
        INSERT INTO overdue_log (source_table, stage_progress_id, supplier_name, project_name, stage_name, responsible_name, planned_start, planned_end, actual_start, comments)
        SELECT 
            'project_stages', ps.stage_progress_id, s.supplier_name, p.project_name, stg.stage_name, u.display_name,
            ps.planned_start, ps.planned_end, ps.actual_start, ps.comments
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE ps.actual_end IS NULL 
          AND ps.planned_end < CURRENT_DATE
          AND p.is_agreement_project = TRUE
        ON CONFLICT (source_table, stage_progress_id) DO NOTHING
    """
    
    # 2. Запрос для Технологии
    query_tech = """
        INSERT INTO overdue_log (source_table, stage_progress_id, supplier_name, project_name, info_name, stage_name, responsible_name, planned_start, planned_end, actual_start, comments)
        SELECT 
            'item_stages', ist.stage_progress_id, s.supplier_name, p.project_name, it.info_name, stg.stage_name, u.display_name,
            ist.planned_start, ist.planned_end, ist.actual_start, ist.comments
        FROM item_stages ist
        JOIN project_items pi ON ist.item_id = pi.item_id
        JOIN projects p ON pi.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN info_types it ON pi.info_id = it.info_id
        JOIN stages stg ON ist.stage_id = stg.stage_id
        LEFT JOIN users u ON ist.responsible_id = u.user_id
        WHERE ist.actual_end IS NULL 
          AND ist.planned_end < CURRENT_DATE
        ON CONFLICT (source_table, stage_progress_id) DO NOTHING
    """
    
    try:
        with Session(engine) as session:
            session.execute(text(query_buro))
            session.execute(text(query_tech))
            session.commit()
    except:
        pass

# ==========================================
# 📊 ОСНОВНАЯ ФУНКЦИЯ ВКЛАДКИ
# ==========================================

def render_analytics_tab(user_role="user"):
    # Синхронизируем просрочки
    sync_overdue_log()

    tabs = st.tabs(["🎯 KPI", "📅 Календарь", "👥 Работа сотрудников", "🌡️ Тепловая карта трения", "📄 Отчёты"])

    with tabs[0]:
        render_kpi_dashboard_v3(user_role)

    with tabs[1]:
        render_calendar_view()

    with tabs[2]:
        render_team_performance_view()

    with tabs[3]:
        render_heatmap_view()

    with tabs[4]:
        render_reports_view()

# ==========================================
# 🎯 KPI DASHBOARD (V3)
# ==========================================
def render_kpi_dashboard_v3(user_role):
    TODAY = pd.Timestamp.today().normalize()

    # Вспомогательная функция для нумерации
    def get_kpi_with_details(query_sql, params=None):
        df = query_db(query_sql, params)
        if not df.empty:
            df.insert(0, '№ п/п', range(1, len(df) + 1))
        return df

    # ==========================================
    # 1. 📜 Соглашения в работе
    # ==========================================
    q_ag_details = """
        SELECT s.supplier_name as "Поставщик", p.project_name as "Проект", 
               stg.stage_name as "Стадия", ms.micro_status_name as "Статус", 
               ps.comments as "Комментарий", ps.actual_start as "Старт", 
               u.display_name as "Ответственный"
        FROM project_stages ps 
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id 
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id 
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE p.is_agreement_project = TRUE 
          AND ms.micro_status_name IN ('В работе', 'Ожидание')
          AND NOT EXISTS (
              SELECT 1 FROM project_stages ps3 JOIN stages s3 ON ps3.stage_id = s3.stage_id 
              JOIN ref_micro_statuses ms3 ON ps3.micro_status = ms3.micro_status_id
              WHERE ps3.project_id = p.project_id AND s3.stage_name = 'Документ подписан' AND ms3.micro_status_name = 'Выполнено'
          )
        ORDER BY ps.actual_start ASC NULLS LAST
    """
    ag_df = get_kpi_with_details(q_ag_details)
    st.metric("📜 Соглашений в работе", len(ag_df))
    with st.expander("Детализация соглашений в работе", expanded=False):
        if not ag_df.empty:
            st.dataframe(ag_df, width="stretch", hide_index=True)
        else: st.info("Нет активных стадий по соглашениям.")
    st.markdown("---")

    # ==========================================
    # 2. ⚙️ Текущая техническая работа
    # ==========================================
    q_tech_details = """
        SELECT s.supplier_name as "Поставщик", p.project_name as "Проект", 
               it.info_name as "Вид сведений", stg.stage_name as "Стадия", 
               ms.micro_status_name as "Статус", ist.comments as "Комментарий", 
               ist.actual_start as "Старт", u.display_name as "Ответственный"
        FROM item_stages ist 
        JOIN project_items pi ON ist.item_id = pi.item_id
        JOIN projects p ON pi.project_id = p.project_id 
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN info_types it ON pi.info_id = it.info_id 
        JOIN stages stg ON ist.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id 
        LEFT JOIN users u ON ist.responsible_id = u.user_id
        WHERE ms.micro_status_name IN ('В работе', 'Ожидание')
          AND NOT EXISTS (
              SELECT 1 FROM item_stages ist2 JOIN stages s2 ON ist2.stage_id = s2.stage_id 
              JOIN ref_micro_statuses ms2 ON ist2.micro_status = ms2.micro_status_id
              WHERE ist2.item_id = pi.item_id AND s2.stage_name = 'Публикация набора' AND ms2.micro_status_name = 'Выполнено'
          )
        ORDER BY ist.actual_start ASC NULLS LAST
    """
    tech_df = get_kpi_with_details(q_tech_details)
    st.metric("⚙️ Текущая техническая работа", len(tech_df))
    with st.expander("Детализация технической работы", expanded=False):
        if not tech_df.empty:
            st.dataframe(tech_df, width="stretch", hide_index=True)
        else: st.info("Нет активных технических задач.")
    st.markdown("---")

    # ==========================================
    # 3. 📅 Дедлайны ≤7 дней
    # ==========================================
    q_soon_sql = """
        SELECT supplier_name, project_name, info_name, stage_name, micro_status_name, 
               comments, planned_start, planned_end, actual_start, responsible_name
        FROM (
            SELECT s.supplier_name, p.project_name, '—' as info_name, stg.stage_name, 
                   ms.micro_status_name, ps.comments, ps.planned_start, ps.planned_end, ps.actual_start, u.display_name as responsible_name
            FROM project_stages ps 
            JOIN projects p ON ps.project_id = p.project_id 
            JOIN suppliers s ON p.supplier_id = s.supplier_id 
            JOIN stages stg ON ps.stage_id = stg.stage_id 
            JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id 
            LEFT JOIN users u ON ps.responsible_id = u.user_id
            UNION ALL
            SELECT s.supplier_name, p.project_name, it.info_name, stg.stage_name, 
                   ms.micro_status_name, ist.comments, ist.planned_start, ist.planned_end, ist.actual_start, u.display_name as responsible_name
            FROM item_stages ist 
            JOIN project_items pi ON ist.item_id = pi.item_id 
            JOIN projects p ON pi.project_id = p.project_id 
            JOIN suppliers s ON p.supplier_id = s.supplier_id 
            JOIN info_types it ON pi.info_id = it.info_id 
            JOIN stages stg ON ist.stage_id = stg.stage_id 
            JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id 
            LEFT JOIN users u ON ist.responsible_id = u.user_id
        ) as combined
        WHERE planned_end BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days' 
          AND micro_status_name != 'Выполнено'
        ORDER BY planned_end ASC
    """
    soon_df = get_kpi_with_details(q_soon_sql)
    st.metric("📅 Дедлайны ≤7 дней", len(soon_df))
    with st.expander("Задачи с близким дедлайном", expanded=False):
        if not soon_df.empty:
            st.dataframe(soon_df, width="stretch", hide_index=True)
        else: st.info("На ближайшие 7 дней дедлайнов не обнаружено.")
    st.markdown("---")

    # ==========================================
    # 4. 🚨 Просрочено этапов (Логика по planned_end)
    # ==========================================
    st.markdown("#### 🚨 Просрочено этапов")
    p_choice = st.selectbox("Период совершения просрочки (по плану):", ["Все время", "Текущая неделя", "Текущий месяц", "Квартал", "Год"], key="overdue_filter")
    
    q_overdue = """
        SELECT supplier_name, project_name, stage_name, planned_start, planned_end, actual_start, responsible_name 
        FROM overdue_log 
    """
    if p_choice != "Все время":
        interval_map = {
            "Текущая неделя": "week",
            "Текущий месяц": "month",
            "Квартал": "quarter",
            "Год": "year"
        }
        q_overdue += f" WHERE planned_end >= date_trunc('{interval_map[p_choice]}', now())"
    
    overdue_data = get_kpi_with_details(q_overdue + " ORDER BY planned_end DESC")
    st.metric("Кол-во зафиксированных просрочек", len(overdue_data))
    with st.expander("Просмотр истории просрочек", expanded=False):
        if not overdue_data.empty:
            st.dataframe(overdue_data, width="stretch", hide_index=True)

# ==========================================
# 📄 ФУНКЦИИ ОТЧЕТОВ (ВКЛАДКА 5)
# ==========================================

def render_reports_view():
    st.markdown("### 📋 Формирование регламентных отчётов")
    report_type = st.selectbox("Выберите тип отчёта:", [
        "1. Реестр подписанных соглашений", 
        "2. Сводный отчёт о ходе выполнения (Бюрократия)", 
        "3. Реестр предоставляемых сведений", 
        "4. Просмотр технических опросников"
    ])
    
    if report_type == "1. Реестр подписанных соглашений":
        render_agreement_registry_report("Все", "Все")
    elif report_type == "2. Сводный отчёт о ходе выполнения (Бюрократия)":
        render_progress_bureaucracy_report("Все", "Все")
    elif report_type == "3. Реестр предоставляемых сведений":
        render_provided_data_registry()
    elif report_type == "4. Просмотр технических опросников":
        render_survey_explorer_report()

# Функции создания отчётов
def render_agreement_registry_report(sel_supplier, sel_period):
    """Отчёт 1: Реестр соглашений с учетом фильтра проекта-соглашения"""
    
    # 1. SQL запрос с фильтром по признаку проекта-соглашения
    query = """
        SELECT 
            s.supplier_name,
            ps.actual_end as agreement_date
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE stg.stage_name = 'Документ подписан' 
          AND ms.micro_status_name = 'Выполнено'
          AND ps.actual_end IS NOT NULL
          AND p.is_agreement_project = TRUE  -- 👈 ГЛАВНЫЙ ФИЛЬТР
    """
    
    # Добавляем фильтрацию по поставщику, если он выбран в глобальных фильтрах
    params = {}
    if sel_supplier != "Все":
        query += " AND s.supplier_name = :sup"
        params["sup"] = sel_supplier

    query += " ORDER BY ps.actual_end ASC"
    
    df = query_db(query, params)

    if df.empty:
        st.info("📭 Подписанные соглашения не найдены (проверьте флаг 'Проект первичного подключения' в реквизитах проектов).")
        return

    # 2. Формирование дат и динамического номера
    df['agreement_date'] = pd.to_datetime(df['agreement_date'])

    
    # ❗ ВАЖНО: Фильтр по периоду применяем к уже готовому списку
    # (здесь можно добавить логику фильтрации по sel_period аналогично KPI)

    df = df.sort_values('agreement_date').reset_index(drop=True)
    df.insert(0, "Номер соглашения", "")
    for i in range(len(df)):
        df.loc[i, "Номер соглашения"] = f"{i + 1}/{df.loc[i, 'agreement_date'].year}"

    display_df = df[["Номер соглашения", "supplier_name", "agreement_date"]]
    display_df.columns = ["Номер соглашения", "Наименование поставщика", "Дата соглашения"]
    # даты — это объекты datetime (для Excel)
    display_df['Дата соглашения'] = pd.to_datetime(display_df['Дата соглашения']).dt.date
    
    # Динамический расчет высоты: заголовок + (строки * высота) + небольшой запас
    # Помогает убрать пустые строки внизу таблицы
    row_height = 35
    dynamic_height = min(600, (len(display_df) + 1) * row_height + 10)
        
    # 1. Визуал
    st.dataframe(
        display_df, 
        width='stretch', 
        hide_index=True, 
        height=dynamic_height
    )
    
    # 2. Экспорт в XLSX (Исправленный формат даты)
    buffer = io.BytesIO()
    # задать формат даты прямо при создании Writer
    with pd.ExcelWriter(buffer, engine='xlsxwriter', datetime_format='dd.mm.yyyy') as writer:
        display_df.to_excel(writer, sheet_name='Реестр', index=False)
        
        workbook  = writer.book
        worksheet = writer.sheets['Реестр']
        
        # Настраиваем колонки
        text_format = workbook.add_format({'num_format': '@', 'align': 'left'})
        worksheet.set_column('A:A', 20, text_format)
        worksheet.set_column('B:B', 60)
        worksheet.set_column('C:C', 18)

    st.download_button(
        label="📥 Скачать реестр (Excel)",
        data=buffer.getvalue(),
        file_name=f"registry_{pd.Timestamp.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def render_progress_bureaucracy_report(sel_supplier_global, sel_period):
    st.markdown("#### ⚙️ Настройки отчёта")
    
    # 1. Загружаем первичный срез данных
    query = """
        SELECT 
            s.supplier_id, s.supplier_name, s.is_mandatory,
            stg.stage_id, stg.stage_name, stg.stage_order,
            ps.comments, ps.actual_end, ps.iteration_count
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        WHERE stg.track_category = '1. Документарный'
          AND p.is_agreement_project = TRUE
          AND ps.actual_end IS NOT NULL
    """
    df_raw = query_db(query)
    
    if df_raw.empty:
        st.info("📭 Данные не найдены.")
        return

    # Определяем "Завершенных" (у кого есть этап 8 "Документ подписан")
    completed_ids = df_raw[df_raw['stage_order'] == 8]['supplier_id'].unique()
    
    # 2. Виджеты управления
    col_toggle, _ = st.columns([2,1])
    with col_toggle:
        # Логика инвертирована по твоему запросу (п. 2)
        show_completed = st.checkbox("✅ Показать поставщиков с уже подписанными соглашениями", value=False)

    # Фильтруем df_raw в зависимости от чекбокса
    if not show_completed:
        df_filtered = df_raw[~df_raw['supplier_id'].isin(completed_ids)].copy()
    else:
        df_filtered = df_raw.copy()

    # 3. Мультибоксы выбора поставщиков (п. 3)
    mandatory_list = sorted(df_filtered[df_filtered['is_mandatory'] == True]['supplier_name'].unique())
    others_list = sorted(df_filtered[df_filtered['is_mandatory'] == False]['supplier_name'].unique())

    c1, c2 = st.columns(2)
    with c1:
        sel_mand = st.multiselect("⭐ Выбор ОНПД поставщиков:", options=mandatory_list, placeholder="Все доступные")
    with c2:
        sel_oth = st.multiselect("📂 Выбор прочих поставщиков:", options=others_list, placeholder="Все доступные")

    # Финальная фильтрация данных на основе выбора в мультибоксах
    # Если в мультибоксе ничего не выбрано - значит показываем всех из этой категории
    final_df = df_filtered.copy()
    
    # Собираем список всех имен, которые должны остаться
    allowed_names = []
    if not sel_mand and not sel_oth:
        allowed_names = df_filtered['supplier_name'].unique()
    else:
        # Если что-то выбрано, берем выбранное + то, что НЕ входило в списки выбора (для страховки)
        allowed_names = sel_mand + sel_oth

    final_df = final_df[final_df['supplier_name'].isin(allowed_names)]

    if final_df.empty:
        st.warning("Ни один поставщик не соответствует выбранным критериям.")
        return

    # Переходим к обработке (Шаг 2)
    process_and_show_bureaucracy_report_v2(final_df)

def process_and_show_bureaucracy_report_v2(df):
    df['actual_end'] = pd.to_datetime(df['actual_end'])

    # 1. Расчет ранга проработки (по самому последнему этапу в истории)
    max_stages = df.groupby('supplier_name')['stage_order'].max().reset_index()
    max_stages['rank'] = max_stages['stage_order'].apply(lambda x: "Высокая (этапы 7-8)" if x >= 7 else "Низкая (этапы 1-6)")
    df = df.merge(max_stages[['supplier_name', 'rank']], on='supplier_name')

    # 2. ЛОГИКА ОСТРОВОВ
    # Сортируем строго: Поставщик -> Дата факта -> Порядок справочника (для вех в один день)
    df = df.sort_values(['supplier_name', 'actual_end', 'stage_order', 'iteration_count'])
    
    df['new_group'] = (df['stage_id'] != df['stage_id'].shift()) | (df['supplier_name'] != df['supplier_name'].shift())
    df['group_id'] = df['new_group'].cumsum()

    # В агрегации сохраняем date_min для финальной сортировки
    grouped = df.groupby(['group_id', 'supplier_name', 'rank', 'is_mandatory', 'stage_name']).agg({
        'stage_order': 'first',
        'actual_end': ['min', 'max'],
        'comments': lambda x: ". ".join([str(c) for c in x if pd.notna(c) and str(c).strip() != "Нет"])
    }).reset_index()

    grouped.columns = ['group_id', 'supplier_name', 'rank', 'is_mandatory', 'stage_name', 'stage_order', 'date_min', 'date_max', 'all_comments']

    # 3. Формируем финальные текстовые значения
    def format_date_range(row):
        d1 = row['date_min'].strftime('%d.%m.%Y')
        d2 = row['date_max'].strftime('%d.%m.%Y')
        return d1 if d1 == d2 else f"{d1}–{d2}"

    def format_stage_text(row):
        comm = row['all_comments'].strip()
        # Убираем лишние точки в конце, если они есть
        comm = comm.rstrip('.')
        return f"{row['stage_name']} | {comm}" if comm else row['stage_name']

    grouped['Дата'] = grouped.apply(format_date_range, axis=1)
    grouped['Пройденные этапы'] = grouped.apply(format_stage_text, axis=1)

    # 4. Разделение и отрисовка
    df_mandatory = grouped[grouped['is_mandatory'] == True].copy()
    df_others = grouped[grouped['is_mandatory'] == False].copy()

    def render_smart_table(sub_df, title, color, use_ranking=False):
        if sub_df.empty: return
        
        st.markdown(f"<h4 style='color: {color};'>{title}</h4>", unsafe_allow_html=True)
        
        # 1. Сортировка: Поставщик -> Самая ранняя дата в группе этапов
        # Теперь этапы внутри поставщика будут идти строго по дате появления
        if use_ranking:
            sort_cols = ['rank', 'supplier_name', 'date_min'] # 👈 Заменили stage_order на date_min
            asc_logic = [True, True, True] 
        else:
            sort_cols = ['supplier_name', 'date_min'] # 👈 Заменили stage_order на date_min
            asc_logic = [True, True]
        
        sub_df = sub_df.sort_values(by=sort_cols, ascending=asc_logic)
        
        # 2. Присваиваем № п/п (строго как текст)
        unique_sups = list(dict.fromkeys(sub_df['supplier_name']))
        sup_to_no = {name: str(i+1) for i, name in enumerate(unique_sups)}
        sub_df['№ п/п'] = sub_df['supplier_name'].map(sup_to_no)

        # 3. МЕТОД ЧИСТОЙ ГРУППЫ
        sub_df['is_duplicated'] = sub_df.duplicated(subset=['supplier_name'])
        display_df = sub_df.copy()
        
        # Конвертируем колонки в текст ПЕРЕД очисткой дублей
        display_df['supplier_name'] = display_df['supplier_name'].astype(str)
        if use_ranking:
            display_df['rank'] = display_df['rank'].astype(str)
        
        # ❗ ВАЖНО: Мы убрали строку с преобразованием actual_end, 
        # так как колонка 'Дата' уже сформирована в process_and_show_bureaucracy_report_v2

        # Формируем список колонок для очистки
        cols_to_clear = ['№ п/п', 'supplier_name']
        if use_ranking:
            cols_to_clear.append('rank')
        
        # Очищаем ячейки для повторов внутри группы поставщика
        display_df.loc[display_df['is_duplicated'] == True, cols_to_clear] = ""

        # 4. Колонки для вывода
        final_cols = ['№ п/п', 'supplier_name']
        if use_ranking:
            final_cols.append('rank')
        final_cols.extend(['Пройденные этапы', 'Дата'])

        rename_map = {
            'supplier_name': 'Наименование поставщика',
            'rank': 'Проработка'
        }
        
        # Динамический расчет высоты
        row_height = 35
        dynamic_height = min(600, (len(display_df) + 1) * row_height + 10)

        st.dataframe(
            display_df[final_cols].rename(columns=rename_map), 
            width='stretch', 
            hide_index=True,
            height=dynamic_height
        )

    # Вызываем render_smart_table
    render_smart_table(df_mandatory, "⭐ Поставщики обязательных наборов (ОНПД)", "#ff4b4b", use_ranking=True)
    render_smart_table(df_others, "📂 Прочие поставщики", "#31333F", use_ranking=False)
    
    st.markdown("---")
    # Кнопка экспорта именно этого отчета
    xlsx_data = export_bureaucracy_to_excel(grouped)
    st.download_button(
        label="📥 Скачать сводный отчёт (Excel)",
        data=xlsx_data,
        file_name=f"bureaucracy_report_{pd.Timestamp.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="btn_dl_report_2"
    )

def export_bureaucracy_to_excel(grouped_df):
    """Сложный экспорт с объединением ячеек и разделителями ПСМ32"""
    buffer = io.BytesIO()
    
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet('Ход выполнения')
        
        # Стили
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        group_fmt = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1, 'align': 'left', 'valign': 'vcenter'})
        cell_fmt = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'vcenter', 'text_wrap': True})
        center_fmt = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True})

        # Шапка (всего 4 колонки, как ты просил)
        headers = ['№ п/п', 'Наименование поставщика', 'Пройденные этапы', 'Дата']
        for col_num, header in enumerate(headers):
            worksheet.write(0, col_num, header, header_fmt)
        
        curr_row = 1
        
        # Логика деления на группы
        groups_logic = [
            ("Поставщики из ПСМ32 (Высокая степень проработки)", grouped_df[(grouped_df['is_mandatory']) & (grouped_df['rank'].str.contains("Высокая"))]),
            ("Поставщики из ПСМ32 (Низкая степень проработки)", grouped_df[(grouped_df['is_mandatory']) & (grouped_df['rank'].str.contains("Низкая"))]),
            ("Поставщики не из ПСМ32", grouped_df[~grouped_df['is_mandatory']])
        ]

        for group_name, sub_df in groups_logic:
            if sub_df.empty: continue
            
            # Вставляем строку-разделитель группы на все 4 колонки (0-3)
            worksheet.merge_range(curr_row, 0, curr_row, 3, group_name, group_fmt)
            curr_row += 1
            
            # Нумерация поставщиков внутри группы
            unique_sups = list(dict.fromkeys(sub_df['supplier_name']))
            
            for i, sup_name in enumerate(unique_sups):
                sup_data = sub_df[sub_df['supplier_name'] == sup_name]
                num_islands = len(sup_data) # Количество сгруппированных этапов
                
                # Объединяем ячейки № п/п и Поставщика, если этапов больше одного
                if num_islands > 1:
                    worksheet.merge_range(curr_row, 0, curr_row + num_islands - 1, 0, i + 1, center_fmt)
                    worksheet.merge_range(curr_row, 1, curr_row + num_islands - 1, 1, sup_name, cell_fmt)
                else:
                    worksheet.write(curr_row, 0, i + 1, center_fmt)
                    worksheet.write(curr_row, 1, sup_name, cell_fmt)
                
                # Записываем сгруппированные этапы и даты
                for _, row in sup_data.iterrows():
                    worksheet.write(curr_row, 2, row['Пройденные этапы'], cell_fmt)
                    # Используем уже готовую строку 'Дата' (которая может быть интервалом)
                    worksheet.write(curr_row, 3, row['Дата'], center_fmt)
                    curr_row += 1

        # Настройка ширины колонок
        worksheet.set_column('A:A', 6)  # № п/п
        worksheet.set_column('B:B', 40) # Поставщик
        worksheet.set_column('C:C', 70) # Этапы (пошире для длинных комментариев)
        worksheet.set_column('D:D', 22) # Дата (шире для интервалов ДД.ММ-ДД.ММ)

    return buffer.getvalue()

def render_provided_data_registry():
    """Отчёт 3: Реестр предоставляемых сведений (с Номерами соглашений)"""
    st.markdown("#### ⚙️ Настройки отчёта")
    
    # 1. Сначала получаем ГЛОБАЛЬНЫЙ порядок всех соглашений для присвоения номеров
    # Это гарантирует, что номер 1/2026 всегда будет у одного и того же поставщика во всех отчетах
    global_numbers_query = """
        SELECT s.supplier_name, ps.actual_end
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE stg.stage_order = 8 AND ms.micro_status_name = 'Выполнено' 
          AND ps.actual_end IS NOT NULL AND p.is_agreement_project = TRUE
        ORDER BY ps.actual_end ASC
    """
    df_numbers = query_db(global_numbers_query)
    
    # Создаем маппинг {Наименование: Номер}
    agreement_map = {}
    if not df_numbers.empty:
        df_numbers['actual_end'] = pd.to_datetime(df_numbers['actual_end'])
        for i, row in df_numbers.iterrows():
            agreement_map[row['supplier_name']] = f"{i+1}/{row['actual_end'].year}"

    # 2. Загружаем основные данные отчета
    query = """
        SELECT DISTINCT
            s.supplier_name, s.is_mandatory,
            it.info_name, pi.provision_right, ps.actual_end as sign_date
        FROM project_items pi
        JOIN projects p ON pi.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN info_types it ON pi.info_id = it.info_id
        JOIN project_stages ps ON p.project_id = ps.project_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE stg.stage_order = 8 AND ms.micro_status_name = 'Выполнено'
          AND ps.actual_end IS NOT NULL AND p.is_agreement_project = TRUE
        ORDER BY ps.actual_end ASC, it.info_name ASC
    """
    df_raw = query_db(query)

    if df_raw.empty:
        st.info("📭 Не найдено сведений по завершенным соглашениям.")
        return

    # 3. Фильтры (те же, что были)
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        all_sups = sorted(df_raw["supplier_name"].unique())
        sel_sups = st.multiselect("🏢 Поставщики:", all_sups, placeholder="Все", key="reg3_sup_filter")
    with c2:
        all_rights = sorted(df_raw["provision_right"].unique())
        sel_rights = st.multiselect("⚖️ Права предоставления:", all_rights, placeholder="Все", key="reg3_right_filter")
    with c3:
        only_mand = st.checkbox("⭐ Только ОНПД", value=False, key="reg3_mand_check")

    # Применение фильтрации
    df_filtered = df_raw.copy()
    if sel_sups:
        df_filtered = df_filtered[df_filtered["supplier_name"].isin(sel_sups)]
    if sel_rights:
        df_filtered = df_filtered[df_filtered["provision_right"].isin(sel_rights)]
    if only_mand:
        df_filtered = df_filtered[df_filtered["is_mandatory"] == True]

    if df_filtered.empty:
        st.warning("По выбранным критериям данных нет.")
        return

    # 4. ПОДГОТОВКА ДЛЯ ВИЗУАЛА
    df_viz = df_filtered.copy()
    df_viz['actual_end'] = pd.to_datetime(df_viz['sign_date'])
    
    # Присваиваем номер соглашения из нашего глобального маппинга
    df_viz['№ Соглашения'] = df_viz['supplier_name'].map(agreement_map)
    
    df_viz['Наименование поставщика'] = df_viz.apply(
        lambda x: f"⭐ {x['supplier_name']}" if x['is_mandatory'] else x['supplier_name'], axis=1
    )
    
    # Маскируем дубликаты для чистой группы
    df_viz['is_dup'] = df_viz.duplicated(subset=['supplier_name'])
    display_df = df_viz.copy()
    display_df.loc[display_df['is_dup'], ['№ Соглашения', 'Наименование поставщика']] = ""

    # Вывод
    cols_show = ["№ Соглашения", "Наименование поставщика", "info_name", "provision_right"]
    rename_map = {"info_name": "Вид сведений", "provision_right": "Право предоставления"}
    
    h = min(600, (len(display_df) + 1) * 35 + 5)
    st.dataframe(display_df[cols_show].rename(columns=rename_map), width="stretch", hide_index=True, height=h)

    # 5. КНОПКА EXCEL
    st.markdown("---")
    # Передаем в экспорт отфильтрованный DF, в который уже добавлен столбец с номерами
    xlsx_data = export_registry_to_excel(df_viz[~df_viz['is_dup'].isna()]) 
    st.download_button(
        label="📥 Скачать реестр (Excel)",
        data=xlsx_data,
        file_name=f"registry_data_{pd.Timestamp.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="btn_dl_reg_3"
    )

def export_registry_to_excel(df):
    """Сложный экспорт Реестра сведений (с Номером соглашения)"""
    buffer = io.BytesIO()
    
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet('Реестр сведений')
        
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#DEEAF6', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
        cell_fmt = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'vcenter', 'text_wrap': True})
        center_fmt = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
        text_num_fmt = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter', 'num_format': '@'}) # Явный текстовый формат
        mand_fmt = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'vcenter', 'text_wrap': True, 'font_color': '#C00000', 'bold': True})

        # Заголовок
        headers = ['Номер соглашения', 'Наименование поставщика', 'Вид сведений', 'Право предоставления']
        for col_num, header in enumerate(headers):
            worksheet.write(0, col_num, header, header_fmt)
        
        curr_row = 1
        # Группируем по поставщику, сохраняя порядок по дате соглашения
        unique_sups = list(dict.fromkeys(df['supplier_name']))
        
        for sup_name in unique_sups:
            sup_data = df[df['supplier_name'] == sup_name]
            num_rows = len(sup_data)
            is_mand = sup_data.iloc[0]['is_mandatory']
            agr_num = sup_data.iloc[0]['№ Соглашения'] # Берем уже вычисленный номер
            
            current_cell_style = mand_fmt if is_mand else cell_fmt
            sup_display_name = f"⭐ {sup_name}" if is_mand else sup_name

            if num_rows > 1:
                # Объединяем ячейки Номера и Поставщика
                worksheet.merge_range(curr_row, 0, curr_row + num_rows - 1, 0, agr_num, text_num_fmt)
                worksheet.merge_range(curr_row, 1, curr_row + num_rows - 1, 1, sup_display_name, current_cell_style)
            else:
                worksheet.write(curr_row, 0, agr_num, text_num_fmt)
                worksheet.write(curr_row, 1, sup_display_name, current_cell_style)
            
            for _, row in sup_data.iterrows():
                worksheet.write(curr_row, 2, row['info_name'], cell_fmt)
                worksheet.write(curr_row, 3, row['provision_right'], cell_fmt)
                curr_row += 1

        worksheet.set_column('A:A', 18)
        worksheet.set_column('B:B', 45)
        worksheet.set_column('C:C', 50)
        worksheet.set_column('D:D', 40)
        worksheet.freeze_panes(1, 0)

    return buffer.getvalue()
    
def render_survey_explorer_report():
    """Отчёт 4: Просмотр технических опросников (Проводник)"""
    st.markdown("#### 🔍 Проводник по техническим опросникам")

    # 1. Загружаем список поставщиков, у которых в принципе есть опросники
    suppliers_with_surveys = query_db("""
        SELECT DISTINCT s.supplier_id, sup.supplier_name 
        FROM surveys s 
        JOIN suppliers sup ON s.supplier_id = sup.supplier_id 
        ORDER BY sup.supplier_name
    """)

    if suppliers_with_surveys.empty:
        st.info("📭 В базе данных пока нет ни одного заполненного опросника.")
        return

    # Создаем маппинг для селектбокса
    sup_map = dict(zip(suppliers_with_surveys["supplier_name"], suppliers_with_surveys["supplier_id"]))
    
    # 2. Выбор поставщика
    sel_sup_name = st.selectbox(
        "🏢 Выберите поставщика:", 
        [""] + list(sup_map.keys()), 
        index=0,
        placeholder="Начните вводить название...",
        key="an_survey_sup_sel"
    )

    if not sel_sup_name:
        st.info("💡 Выберите поставщика для просмотра его опросников...")
        return

    selected_sup_id = sup_map[sel_sup_name]

    # 3. Загружаем опросники выбранного поставщика
    surveys = query_db("""
        SELECT 
            s.survey_id, 
            s.received_date, 
            COALESCE(STRING_AGG(it.info_name, ', '), 'Виды не выбраны') as info_list
        FROM surveys s
        LEFT JOIN survey_info_types sit ON s.survey_id = sit.survey_id
        LEFT JOIN info_types it ON sit.info_id = it.info_id
        WHERE s.supplier_id = :sid
        GROUP BY s.survey_id, s.received_date
        ORDER BY s.received_date DESC
    """, {"sid": int(selected_sup_id)})

    # Формируем список для выбора опросника
    survey_options = {
        f"📅 {r['received_date'].strftime('%d.%m.%Y')} | {r['info_list'][:60]}... (ID: {r['survey_id']})": r['survey_id'] 
        for _, r in surveys.iterrows()
    }

    sel_survey_label = st.selectbox(
        "📝 Выберите опросник:", 
        [""] + list(survey_options.keys()), 
        key="an_survey_item_sel"
    )

    if not sel_survey_label:
        st.info("💡 Выберите опросник из списка для детального просмотра...")
        return

    # 4. Отображение через общий компонент
    selected_sid = survey_options[sel_survey_label]
    
    st.divider()
    # Вызываем общую функцию (session передаем None, так как в аналитике только чтение)
    render_survey_viewer(None, selected_sid, is_readonly=True)
    

# [Сюда нужно вставить ранее написанные функции отчетов: render_agreement_registry_report, render_progress_bureaucracy_report, etc.]
# Они остаются без изменений, просто вызываются внутри render_reports_view.

def render_calendar_view():
    st.markdown("### 📅 Планировщик")

    if "cal_version" not in st.session_state:
        st.session_state["cal_version"] = 0
    
    # --- 1. НАСТРОЙКИ ОТОБРАЖЕНИЯ ---
    c_feat1, _ = st.columns([2, 1])
    with c_feat1:
        show_all = st.checkbox("🔄 Показать все события (включая завершенные)", value=False)
    
    # --- 2. ЗАГРУЗКА ДАННЫХ (с усиленной фильтрацией) ---
    # Логика: если НЕ show_all, берем только те, где нет фактического конца И статус НЕ 'Выполнено'
    status_filter_buro = "" if show_all else """
        AND ps.actual_end IS NULL 
        AND ms.micro_status_name != 'Выполнено'
    """
    status_filter_tech = "" if show_all else """
        AND ist.actual_end IS NULL 
        AND ms.micro_status_name != 'Выполнено'
    """

    query = f"""
        SELECT 
            p.project_name, stg.stage_name, ms.micro_status_name, ps.comments,
            ps.planned_start, ps.planned_end, ps.actual_start, ps.actual_end,
            u.display_name as responsible_name, 'bureaucracy' as category, '—' as info_name
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE ps.planned_start IS NOT NULL {status_filter_buro}
        
        UNION ALL
        
        SELECT 
            p.project_name, stg.stage_name, ms.micro_status_name, ist.comments,
            ist.planned_start, ist.planned_end, ist.actual_start, ist.actual_end,
            u.display_name as responsible_name, 'tech' as category, it.info_name
        FROM item_stages ist
        JOIN project_items pi ON ist.item_id = pi.item_id
        JOIN projects p ON pi.project_id = p.project_id
        JOIN info_types it ON pi.info_id = it.info_id
        JOIN stages stg ON ist.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id
        LEFT JOIN users u ON ist.responsible_id = u.user_id
        WHERE ist.planned_start IS NOT NULL {status_filter_tech}
    """
    df_events = query_db(query)

    # --- 3. ПОДГОТОВКА СОБЫТИЙ ---
    calendar_events = []
    for _, row in df_events.iterrows():
        detail_text = row['info_name'] if row['info_name'] != '—' else row['stage_name']
        short_detail = (detail_text[:47] + '...') if len(detail_text) > 50 else detail_text
        title = f"{row['project_name']} | {short_detail}"
        
        is_done = pd.notna(row['actual_end']) or row['micro_status_name'] == 'Выполнено'
        color = "#9E9E9E" if is_done else ("#1E88E5" if row['category'] == 'bureaucracy' else "#43A047")

        calendar_events.append({
            "title": title,
            "start": row['planned_start'].strftime("%Y-%m-%d"),
            "end": (row['planned_end'] + timedelta(days=1)).strftime("%Y-%m-%d"),
            "color": color,
            "extendedProps": {
                "project": row['project_name'],
                "stage": row['stage_name'],
                "info": row['info_name'],
                "status": row['micro_status_name'],
                "responsible": row['responsible_name'] or "Не назначен",
                "comments": row['comments'] or "Нет",
                "p_start": row['planned_start'].strftime("%d.%m.%Y"),
                "p_end": row['planned_end'].strftime("%d.%m.%Y"),
                "a_start": row['actual_start'].strftime("%d.%m.%Y") if pd.notna(row['actual_start']) else "Ещё не начато",
                "is_done": is_done
            }
        })

    # --- 4. ВЕРСТКА: КАЛЕНДАРЬ + ДЕТАЛИ ---
    st.markdown("<style>iframe[title='streamlit_calendar.calendar'] { min-height: 600px !important; }</style>", unsafe_allow_html=True)

    with st.expander("📅 Календарное планирование", expanded=False):
        col_cal, col_info = st.columns([0.7, 0.3])
        
        with col_cal:
            calendar_options = {
                "initialView": "dayGridMonth",
                "headerToolbar": {"left": "prev,next", "center": "title", "right": "today"},
                "locale": "ru", "firstDay": 1, "height": 600
            }
            state = calendar(events=calendar_events, options=calendar_options, key=f"cal_v{st.session_state['cal_version']}")

        with col_info:
            if state and "eventClick" in state:
                props = state["eventClick"]["event"].get("extendedProps", {})
                st.markdown(f"#### 🎯 Детали задачи")
                st.info(f"**{props.get('project')}**")
                
                # Добавленные по вашему запросу строки:
                st.write(f"📅 **План:** {props.get('p_start')} — {props.get('p_end')}")
                st.write(f"🚦 **Статус:** `{props.get('status')}`")
                st.write(f"⏳ **Факт. начало:** {props.get('a_start')}")
                st.divider()
                
                st.write(f"**Этап:** {props.get('stage')}")
                if props.get('info') != '—':
                    st.write(f"**Вид:** {props.get('info')}")
                st.write(f"**Ответственный:** {props.get('responsible')}")
                st.caption(f"**Комментарий:** {props.get('comments')}")
                
                if props.get('is_done'):
                    st.success("✅ Стадия завершена")

                if st.button("❌ Закрыть детали", width='stretch'):
                    st.session_state["cal_version"] += 1
                    st.rerun()
            else:
                st.info("💡 Кликните на событие в календаре.")

    # --- 3. ПОДГОТОВКА СОБЫТИЙ ---
    # calendar_events = []
    agenda_data = []
    
    for _, row in df_events.iterrows():
        # Логика заголовка: Проект + обрезанный вид сведений/этап
        detail_text = row['info_name'] if row['info_name'] != '—' else row['stage_name']
        short_detail = (detail_text[:47] + '...') if len(detail_text) > 50 else detail_text
        title = f"{row['project_name']} | {short_detail}"
        
        # Данные для сетки
        calendar_events.append({
            "title": title,
            "start": row['planned_start'].strftime("%Y-%m-%d"),
            "end": (row['planned_end'] + timedelta(days=1)).strftime("%Y-%m-%d"),
            "color": "#1E88E5" if row['category'] == 'bureaucracy' else "#43A047",
            "extendedProps": {
                "project": row['project_name'],
                "stage": row['stage_name'],
                "info": row['info_name'],
                "responsible": row['responsible_name'] or "Не назначен",
                "comments": row['comments'] or "Нет"
            }
        })
        
        # Данные для текстовой Агенды
        agenda_data.append({"date": row['planned_start'], "type": "🚀 Старт", "title": title})
        agenda_data.append({"date": row['planned_end'], "type": "🎯 Дедлайн", "title": title})

    # --- 4. CSS ФИКС (Чтобы календарь не пропадал в экспандере) ---
    st.markdown("""
        <style>
            iframe[title="streamlit_calendar.calendar"] { min-height: 650px !important; }
            .stExpander { border: 1px solid #e6e9ef !important; }
        </style>
    """, unsafe_allow_html=True)

    # --- 5. ДЕТАЛЬНЫЙ СПИСОК (AGENDA) ---
    st.subheader("📋 Детальный список ближайших событий")
    if not agenda_data:
        st.info("Нет активных событий.")
    else:
        agenda_df = pd.DataFrame(agenda_data).sort_values('date')
        # Показываем события на ближайшие 14 дней
        today = datetime.now().date()
        future_limit = today + timedelta(days=14)
        filtered_agenda = agenda_df[(agenda_df['date'] >= today) & (agenda_df['date'] <= future_limit)]
        
        if filtered_agenda.empty:
            st.write("На ближайшие 2 недели задач не запланировано.")
        else:
            for ev_date, group in filtered_agenda.groupby('date'):
                with st.expander(f"📅 {ev_date.strftime('%d.%m.%Y (%a)')} — событий: {len(group)}"):
                    for _, item in group.iterrows():
                        st.write(f"**{item['type']}**: {item['title']}")

    st.write("") 

    if not calendar_events:
        st.info("Нет данных для отображения в сетке.")

def render_team_performance_view():
    st.markdown("### 👥 Оперативный контроль и загрузка сотрудников")
    TODAY = pd.Timestamp.today().normalize()

        # ==========================================
    # 6. 👤 Загрузка ответственных сотрудников
    # ==========================================
    with st.expander("👤 Загрузка ответственных сотрудников", expanded=True):
        # 1. Сбор статистики для мультиселекта (фильтра)
        staff_stats = query_db("""
            SELECT u.display_name, COUNT(*) as task_count
            FROM (
                SELECT responsible_id, micro_status FROM project_stages 
                UNION ALL 
                SELECT responsible_id, micro_status FROM item_stages
            ) as tasks
            JOIN users u ON tasks.responsible_id = u.user_id
            JOIN ref_micro_statuses ms ON tasks.micro_status = ms.micro_status_id
            WHERE ms.micro_status_name IN ('В работе', 'Ожидание')
            GROUP BY u.display_name
        """)
        total_active_tasks = staff_stats['task_count'].sum()
        staff_options = [f"{r['display_name']} | {r['task_count']} задач" for _, r in staff_stats.iterrows()]
        
        sel_staff = st.multiselect(
            "Выберите сотрудников для детализации нагрузки:", 
            options=staff_options, 
            placeholder=f"Все сотрудники | {total_active_tasks} задач в работе",
            key="staff_load_multi"
        )

        # 2. Загрузка полных данных для таблицы и карточки
        load_query = """
            SELECT 
                p.project_name as "Проект", 
                u.display_name as "Ответственный",
                stg.stage_name as "Этап", 
                ps.comments as "Комментарий", 
                ps.planned_start as "План. начало", 
                ps.planned_end as "План. завершение", 
                ps.actual_start as "Факт. начало",
                ms.micro_status_name as "Статус"
            FROM project_stages ps 
            JOIN projects p ON ps.project_id = p.project_id 
            JOIN stages stg ON ps.stage_id = stg.stage_id 
            JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id 
            JOIN users u ON ps.responsible_id = u.user_id
            WHERE ms.micro_status_name IN ('В работе', 'Ожидание')
            
            UNION ALL
            
            SELECT 
                p.project_name, 
                u.display_name,
                stg.stage_name, 
                ist.comments, 
                ist.planned_start, 
                ist.planned_end, 
                ist.actual_start,
                ms.micro_status_name
            FROM item_stages ist 
            JOIN project_items pi ON ist.item_id = pi.item_id 
            JOIN projects p ON pi.project_id = p.project_id 
            JOIN stages stg ON ist.stage_id = stg.stage_id 
            JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id 
            JOIN users u ON ist.responsible_id = u.user_id
            WHERE ms.micro_status_name IN ('В работе', 'Ожидание')
        """
        load_df = query_db(load_query)

        # Фильтрация по выбранным в мультиселекте сотрудникам
        if sel_staff:
            selected_names = [s.split(" | ")[0] for s in sel_staff]
            load_df = load_df[load_df["Ответственный"].isin(selected_names)]

        if load_df.empty:
            st.info("Нет активных задач.")
        else:
            # --- РЕАЛИЗАЦИЯ ВЫБОРА (Native Selection) ---
            col_table, col_card = st.columns([0.35, 0.65])

            with col_table:
                # Настройка отображения: скрываем лишнее, оставляем Проект и Ответственного
                # Используем on_select="rerun" для мгновенной реакции
                selection = st.dataframe(
                    load_df,
                    width="stretch",
                    hide_index=True,
                    on_select="rerun", # 👈 Включаем режим выбора
                    selection_mode="single-row", # 👈 Только одна строка за раз
                    column_config={
                        "Проект": st.column_config.TextColumn(width="medium"),
                        "Ответственный": st.column_config.TextColumn(width="medium"), 
                        "Статус": st.column_config.TextColumn(width="medium"),
                        # Скрываем остальные колонки в таблице, но они остаются в данных
                        "Этап": None, "Комментарий": None, "План. начало": None, 
                        "План. завершение": None, "Факт. начало": None
                    }
                )

            with col_card:
                # Проверяем, выбрана ли строка
                selected_rows = selection.get("selection", {}).get("rows", [])
                
                if selected_rows:
                    # Достаем данные выбранной строки по её индексу
                    selected_idx = selected_rows[0]
                    row_data = load_df.iloc[selected_idx]

                    with st.container(border=True):
                        st.markdown(f"#### 🎯 Детали задачи")
                        #st.info(f"**{row_data['Проект']}**")
                        #st.write(f"👤 **Исполнитель:** {row_data['Ответственный']}")
                        st.write(f"**Этап:** {row_data['Этап']}")
                        #st.write(f"🚦 **Статус:** `{row_data['Статус']}`")
                        st.divider()
                        st.write(f"📅 **План:** {row_data['План. начало'].strftime('%d.%m.%Y')} — {row_data['План. завершение'].strftime('%d.%m.%Y')}")
                        f_start = row_data['Факт. начало']
                        st.write(f"⏳ **Факт. начало:** {f_start.strftime('%d.%m.%Y') if pd.notna(f_start) else 'Не начато'}")
                        st.write(f"**Комментарий:** {row_data['Комментарий'] or 'Нет'}")
                else:
                    st.info("💡 Выберите строку в таблице слева, чтобы увидеть подробности здесь.")

    st.markdown("---")
    
    # ==========================================
    # 5. ✅ Статистика выполненных задач
    # ==========================================
    st.markdown("#### ✅ Статистика выполненных задач")
    done_p_choice = st.selectbox("Период фактического завершения:", ["Все время", "Текущая неделя", "Текущий месяц", "Квартал", "Год"], key="done_period_sel")
    
    q_done_base = """
        SELECT p.project_name, stg.stage_name, ps.comments, ps.planned_start, ps.planned_end, ps.actual_start, ps.actual_end, u.display_name as responsible_name
        FROM project_stages ps 
        JOIN projects p ON ps.project_id = p.project_id 
        JOIN stages stg ON ps.stage_id = stg.stage_id 
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id 
        JOIN users u ON ps.responsible_id = u.user_id
        WHERE ms.micro_status_name = 'Выполнено'
        UNION ALL
        SELECT p.project_name, stg.stage_name, ist.comments, ist.planned_start, ist.planned_end, ist.actual_start, ist.actual_end, u.display_name as responsible_name
        FROM item_stages ist 
        JOIN project_items pi ON ist.item_id = pi.item_id 
        JOIN projects p ON pi.project_id = p.project_id 
        JOIN stages stg ON ist.stage_id = stg.stage_id 
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id 
        JOIN users u ON ist.responsible_id = u.user_id
        WHERE ms.micro_status_name = 'Выполнено'
    """
    
    # Обработка фильтров периода и сотрудников для Выполненных задач
    df_done_all = query_db(q_done_base)
    df_done_filtered = pd.DataFrame()

    if not df_done_all.empty:
        df_done_all['actual_end'] = pd.to_datetime(df_done_all['actual_end'])
        df_done_filtered = df_done_all.copy()
        
        if done_p_choice != "Все время":
            if done_p_choice == "Текущая неделя":
                start_date = TODAY - pd.Timedelta(days=TODAY.weekday())
            elif done_p_choice == "Текущий месяц":
                start_date = TODAY.replace(day=1)
            elif done_p_choice == "Квартал":
                start_date = TODAY - pd.offsets.QuarterBegin(startingMonth=1)
            else: # Год
                start_date = TODAY.replace(month=1, day=1)
            df_done_filtered = df_done_filtered[df_done_filtered['actual_end'] >= start_date]

        # Фильтр сотрудников для выполненных
        done_staff_stats = df_done_filtered.groupby("responsible_name").size().reset_index(name="cnt")
        done_staff_opts = [f"{r['responsible_name']} | {r['cnt']} вып." for _, r in done_staff_stats.iterrows()]
        sel_done_staff = st.multiselect("Фильтр по исполнителям (выполненные):", options=done_staff_opts, placeholder="Все сотрудники", key="done_staff_sel")
        
        if sel_done_staff:
            names = [s.split(" | ")[0] for s in sel_done_staff]
            df_done_filtered = df_done_filtered[df_done_filtered["responsible_name"].isin(names)]

    with st.expander("Список выполненных задач", expanded=False):
        if not df_done_filtered.empty:
            df_done_filtered.insert(0, '№ п/п', range(1, len(df_done_filtered)+1))
            st.dataframe(df_done_filtered, width="stretch", hide_index=True)
        else: st.info("Нет выполненных задач за выбранный период.")
    st.markdown("---")

@st.cache_data(ttl=60, show_spinner=False)
def load_heatmap_raw_data():
    """Загружает данные напрямую из таблиц этапов, включая итерации"""
    query = """
        -- 1. Срез Бюрократии
        SELECT 
            s.supplier_name,
            p.project_name, 
            stg.stage_name,
            stg.stage_order,
            stg.track_category,
            ps.planned_end,
            ps.actual_end,
            ps.iteration_count -- 👈 Добавили
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        WHERE ps.planned_end IS NOT NULL

        UNION ALL

        -- 2. Срез Технологии
        SELECT 
            s.supplier_name,
            p.project_name, 
            stg.stage_name,
            stg.stage_order,
            stg.track_category,
            ist.planned_end,
            ist.actual_end,
            ist.iteration_count -- 👈 Добавили
        FROM item_stages ist
        JOIN stages stg ON ist.stage_id = stg.stage_id
        JOIN project_items pi ON ist.item_id = pi.item_id
        JOIN projects p ON pi.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        WHERE ist.planned_end IS NOT NULL
    """
    return query_db(query)

def render_heatmap_view():
    st.markdown("### 🌡️ Матрицы рисков (Дни отклонения от плана)")
    
    # 1. Инструкция (п. 1)
    with st.expander("❓ Как читать эти карты и глоссарий", expanded=False):
        st.write("""
            - **🚦 Светофор**: Сводная панель критических состояний по каждому поставщику.
            - **⚖️ Юридический трек**: Красная шкала задержек. Показывает риски на этапе оформления документов.
            - **⚙️ Технический трек**: Зеленая шкала задержек. Показывает заминки при интеграции данных.
            - **Дни отклонения**: Для активных этапов — просрочка (сегодня минус план). Для завершенных — задержка (факт минус план).
            - **Пустые ячейки**: Отклонений нет (идут в графике или завершены вовремя).
        """)

    df = load_heatmap_raw_data()
    if df.empty:
        st.error("⚠️ Данные по этапам не найдены.")
        return

    df['planned_end'] = pd.to_datetime(df['planned_end'], errors='coerce')
    df['actual_end'] = pd.to_datetime(df['actual_end'], errors='coerce')

    # 2. Фильтрация (п. 2)
    c_filt1, c_filt2 = st.columns([2, 1])
    
    with c_filt2:
        st.write("") # Выравнивание
        only_mandatory = st.checkbox("⭐ Только ОНПД поставщики", value=False, key="hm_mand_filter")
    
    # Сначала фильтруем по ОНПД, если нужно
    if only_mandatory:
        mand_sups = query_db("SELECT supplier_name FROM suppliers WHERE is_mandatory = TRUE")["supplier_name"].tolist()
        df = df[df["supplier_name"].isin(mand_sups)]
    
    with c_filt1:
        all_sups = sorted(df["supplier_name"].unique())
        sel_sups = st.multiselect("🔍 Фильтр по конкретным поставщикам:", all_sups, placeholder="Все доступные", key="hm_sup_filter")

    if sel_sups:
        df = df[df["supplier_name"].isin(sel_sups)]

    st.divider()

    # Переключатель режимов
    modes = ["🚦 Светофор", "⚖️ Юридический трек (Бюрократия)", "⚙️ Технический трек (Технология)"]
    mode = st.radio("Выберите срез анализа:", modes, horizontal=True, key="hm_mode_sel")

    if mode == modes[0]:
        render_traffic_light_view()
    elif mode == modes[1]:
        draw_heatmap_by_track(df, '1. Документарный', "Reds")
    elif mode == modes[2]:
        # 3. Зеленая гамма для Технологии (п. 3)
        draw_heatmap_by_track(df, '2. Технологический', "Greens")

def draw_heatmap_by_track(df, track_name, color_scale_name):
    # 1. Фильтруем трек
    track_data = df[df["track_category"] == track_name].copy()
    if track_data.empty:
        st.warning(f"Нет данных по треку: {track_name}")
        return

    TODAY = pd.Timestamp.today().normalize()
    
    # --- ЛОГИКА ДЛЯ ФИКСИРОВАННОЙ ШКАЛЫ ---
    # Считаем максимальное отклонение ПО ВСЕМУ ТРЕКУ (до фильтрации мультибоксом),
    # чтобы цвета были стабильными. Если в базе пусто, ставим минимум 10.
    def get_raw_dev(row):
        target = row["actual_end"] if pd.notna(row["actual_end"]) else TODAY
        if pd.isna(row["planned_end"]): return 0
        return max(0, (target - row["planned_end"]).days)
    
    temp_dev = track_data.apply(get_raw_dev, axis=1)
    # Группируем по ячейкам, чтобы найти реальный максимум суммы
    global_max = track_data.assign(d=temp_dev).groupby(['supplier_name', 'project_name', 'stage_name'])['d'].sum().max()
    z_max = max(10, global_max) if pd.notna(global_max) else 10

    # 2. Форматирование подписи Поставщик + Проект
    def format_y_label(row):
        sup = str(row['supplier_name'])
        short_sup = (sup[:32] + '...') if len(sup) > 35 else sup
        return f"<b>{short_sup}</b><br><i>{row['project_name']}</i>"

    track_data['y_label'] = track_data.apply(format_y_label, axis=1)
    track_data["deviation"] = temp_dev
    track_data["is_active"] = track_data["actual_end"].isna()

    # 3. АГРЕГАЦИЯ ИТЕРАЦИЙ ( Islands Logic )
    # Группируем по Проекту и Этапу
    grouped = track_data.groupby(['y_label', 'stage_name', 'stage_order']).agg({
        'deviation': 'sum',           # Суммарное отклонение
        'iteration_count': 'count',   # Количество итераций
        'is_active': 'any'            # Если хоть одна итерация активна - ставим молнию
    }).reset_index()

    # 4. Формируем текст и данные для подсказок
    def get_cell_content(row):
        val = int(row['deviation'])
        # Если этап в работе и есть просрочка
        suffix = "⚡" if row['is_active'] and val > 0 else ""
        return f"{val}{suffix}"

    grouped['cell_text'] = grouped.apply(get_cell_content, axis=1)
    
    # Подготовка осей
    order_info = grouped[['stage_name', 'stage_order']].drop_duplicates().sort_values('stage_order')
    sorted_stages = order_info['stage_name'].tolist()

    # Матрицы
    pivot_val = grouped.pivot(index="y_label", columns="stage_name", values="deviation")
    pivot_txt = grouped.pivot(index="y_label", columns="stage_name", values="cell_text")
    pivot_iter = grouped.pivot(index="y_label", columns="stage_name", values="iteration_count")

    # Синхронизация колонок
    cols = [c for c in sorted_stages if c in pivot_val.columns]
    pivot_val = pivot_val.reindex(columns=cols)
    pivot_txt = pivot_txt.reindex(columns=cols).fillna("")
    pivot_iter = pivot_iter.reindex(columns=cols).fillna(0)

    # 5. ОТРИСОВКА
    fig = go.Figure(data=go.Heatmap(
        z=pivot_val.values,
        x=pivot_val.columns,
        y=pivot_val.index,
        text=pivot_txt.values,
        texttemplate="%{text}",
        colorscale=color_scale_name,
        zmin=0,     # Минимум всегда 0 (белый/светлый)
        zmax=z_max, # Максимум зафиксирован по всей базе данных
        xgap=2, ygap=2,
        # Настраиваем кастомные данные для подсказки (передаем итерации)
        customdata=pivot_iter.values,
        hovertemplate=(
            "<b>%{y}</b><br>" +
            "Этап: %{x}<br>" +
            "Суммарное отклонение: <b>%{z} дн.</b><br>" +
            "Количество итераций: %{customdata}<extra></extra>"
        )
    ))

    chart_height = max(500, len(pivot_val.index) * 55 + 150)
    fig.update_layout(
        height=chart_height,
        xaxis_showgrid=False,
        yaxis_autorange='reversed',
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=20, r=20, t=20, b=20),
    )
    fig.update_yaxes(tickfont=dict(size=11))

    st.plotly_chart(fig, width='stretch')

def load_progress_raw_data():
    """
    Загружает все данные для расчета % прогресса.
    Гарантирует наличие всех колонок для Бюрократии и Технологии.
    """
    query = """
        -- 1. Срез Бюрократии
        SELECT 
            p.project_id,
            p.project_name,
            s.supplier_name,
            p.is_agreement_project,
            stg.stage_id,
            stg.stage_name,
            stg.stage_order,
            stg.stage_type,
            COALESCE(stg.duration_days, 0) as norm_days,
            ps.iteration_count,
            ms.micro_status_name as status,
            ps.planned_start, -- 👈 Добавлено
            ps.planned_end,   -- 👈 Добавлено
            ps.actual_start,
            ps.actual_end,
            'bureaucracy' as track,
            '—' as info_name
        FROM projects p
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN project_stages ps ON p.project_id = ps.project_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE ms.micro_status_name != 'Отменено'

        UNION ALL

        -- 2. Срез Технологии
        SELECT 
            p.project_id,
            p.project_name,
            s.supplier_name,
            p.is_agreement_project,
            stg.stage_id,
            stg.stage_name,
            stg.stage_order,
            stg.stage_type,
            COALESCE(stg.duration_days, 0) as norm_days,
            ist.iteration_count,
            ms.micro_status_name as status,
            ist.planned_start, -- 👈 Добавлено
            ist.planned_end,   -- 👈 Добавлено
            ist.actual_start,
            ist.actual_end,
            'tech' as track,
            it.info_name
        FROM projects p
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN project_items pi ON p.project_id = pi.project_id
        JOIN item_stages ist ON pi.item_id = ist.item_id
        JOIN info_types it ON pi.info_id = it.info_id
        JOIN stages stg ON ist.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ist.micro_status = ms.micro_status_id
        WHERE ms.micro_status_name != 'Отменено'
    """
    return query_db(query)
    
def calculate_project_progress(df_project):
    """
    Математический расчет прогресса проекта по двум стекам (50/50).
    """
    TODAY = pd.Timestamp.today().normalize()
    
    def get_track_stats(df_track, track_type):
        pct = 0.0
        current_stage_name = "Не начато"
        in_progress_val = 0.0 
        
        if df_track.empty:
            return pct, current_stage_name, in_progress_val

        # 1. Проверка завершенности (Финишная черта)
        if track_type == 'bureaucracy':
            is_finished = any((df_track['stage_order'] == 8) & (df_track['status'] == 'Выполнено'))
        else:
            is_finished = any((df_track['stage_name'] == 'Публикация набора') & (df_track['status'] == 'Выполнено'))

        if is_finished:
            return 100.0, "Завершено", 0.0

        # 2. Определение сценария Бюрократии
        if track_type == 'bureaucracy':
            # Проверяем, была ли Заявка самым первым этапом (stage_order=1)
            first_stage = df_track.sort_values('stage_order').iloc[0]
            is_placement_scenario = (first_stage['stage_name'] == 'Заявка на размещение НПД')
            
            num_model_stages = 7 if is_placement_scenario else 5
            # Исключаем 'Документ подписан' (8) всегда, а 'Опросный лист' только в сценарии Заявки
            excluded = ['Документ подписан']
            if is_placement_scenario:
                excluded.append('Опросный лист') 
        else:
            # Для технологии всегда 5 этапов
            num_model_stages = 5
            excluded = []

        # Оставляем только те этапы, которые входят в расчетную модель
        active_path = df_track[~df_track['stage_name'].isin(excluded)].copy()
        if active_path.empty: 
            return 0.0, "Инициация", 0.0

        stage_weight = 100.0 / num_model_stages
        unique_orders = sorted(active_path['stage_order'].unique())
        max_order = max(unique_orders)
        
        # 3. Считаем % полностью пройденных этапов (включая пропущенные)
        passed_count = len([o for o in unique_orders if o < max_order])
        pct = passed_count * stage_weight

        # 4. Расчет вклада ТЕКУЩЕГО этапа
        curr_stage_rows = active_path[active_path['stage_order'] == max_order]
        last_iter = curr_stage_rows.sort_values('iteration_count', ascending=False).iloc[0]
        current_stage_name = last_iter['stage_name']
        
        # Считаем вклад только если стадия активна и это "Задача" (не веха)
        if last_iter['status'] in ['В работе', 'Ожидание', 'Планируется']:
            if last_iter['stage_type'] == 'Задача' and pd.notna(last_iter['actual_start']):
                # Сумма дней прошлых итераций этого этапа + текущая
                days_past = (curr_stage_rows['actual_end'] - curr_stage_rows['actual_start']).dt.days.sum()
                days_curr = (TODAY - last_iter['actual_start']).days
                total_days = max(1, (0 if pd.isna(days_past) else days_past) + days_curr)
                
                # Норматив из базы (или 14 дней по умолчанию)
                norm = last_iter['norm_days'] if last_iter['norm_days'] > 0 else 14
                
                # Метод затухающего вклада (насыщение на 90%)
                saturation = 1 - (0.9 / (1 + (total_days / norm)))
                in_progress_val = stage_weight * saturation
                pct += in_progress_val
        
        return pct, current_stage_name, in_progress_val

    # --- СБОРКА ИТОГОВ ---
    # Бюрократия
    b_total, b_name, b_active = get_track_stats(df_project[df_project['track'] == 'bureaucracy'], 'bureaucracy')

    # Технология (среднее по всем видам сведений в проекте)
    tech_data = df_project[df_project['track'] == 'tech']
    t_total, t_active, t_name = 0.0, 0.0, "Не начато"
    
    if not tech_data.empty:
        item_results = [get_track_stats(idf, 'tech') for _, idf in tech_data.groupby('info_name')]
        t_total = sum(r[0] for r in item_results) / len(item_results)
        t_active = sum(r[2] for r in item_results) / len(item_results)
        # Для названия берем первый активный или просто первый
        t_name = next((r[1] for r in item_results if r[1] != "Завершено"), item_results[0][1])

    final_pct = (b_total * 0.5) + (t_total * 0.5)
    final_active = (b_active * 0.5) + (t_active * 0.5)
    
    return {
        "project_name": df_project['project_name'].iloc[0],
        "supplier": df_project['supplier_name'].iloc[0],
        "total": round(final_pct, 2),
        "passed": round(final_pct - final_active, 2),
        "active": round(final_active, 2),
        "details": f"📜 {b_name} | ⚙️ {t_name}"
    }

def render_traffic_light_view():
    st.markdown("### 🚦 Светофор: Прогресс проработки проектов")
    
    df_raw = load_progress_raw_data()
    if df_raw.empty:
        st.info("Нет данных по этапам для расчета прогресса.")
        return

    # Проверка и принудительная конвертация в datetime
    cols_to_fix = ['actual_start', 'actual_end', 'planned_end', 'planned_start']
    for col in cols_to_fix:
        if col in df_raw.columns:
            df_raw[col] = pd.to_datetime(df_raw[col], errors='coerce')
        
    # 1. Расчеты для всех проектов
    results = []
    for pid in df_raw['project_id'].unique():
        proj_results = calculate_project_progress(df_raw[df_raw['project_id'] == pid])
        results.append(proj_results)
    
    res_df = pd.DataFrame(results).sort_values('total', ascending=False)

    # 2. Настройка Plotly
    fig = go.Figure()

    # Сегмент 1: Пройденные этапы (глухой цвет)
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=res_df['passed'],
        name='Завершено',
        orientation='h',
        marker=dict(color='#BDC3C7'), # Спокойный серый
        hoverinfo='skip' # Не кликабельно
    ))

    # Сегмент 2: Текущие этапы (яркий цвет + штриховка)
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=res_df['active'],
        name='В работе',
        orientation='h',
        marker=dict(
            color='#3498DB', # Яркий синий
            pattern_shape="/" # Штриховка
        ),
        customdata=res_df['details'],
        hovertemplate="<b>Текущий статус:</b><br>%{customdata}<br>Общий прогресс: %{x}%<extra></extra>"
    ))

    # Настройка осей и внешнего вида
    fig.update_layout(
        barmode='stack',
        height=max(400, len(res_df) * 60),
        xaxis=dict(title="Процент готовности (%)", range=[0, 100], gridcolor='#eee'),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        plot_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        margin=dict(l=20, r=20, t=20, b=20)
    )

    st.plotly_chart(fig, width='stretch')