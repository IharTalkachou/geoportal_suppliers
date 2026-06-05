import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache
import plotly.express as px
import plotly.graph_objects as go
import io

@st.cache_data(ttl=60, show_spinner=False)
def load_analytics_data():
    """
    Загружает плоский срез данных из v_bi_flat_export, обогащая его 
    информацией о типе трека (Бюрократия/Технология) и итерациях.
    """
    return query_db("""
        SELECT 
            v.supplier_name,
            v.project_name,
            v.project_status,
            v.dataset_name,
            v.info_name,
            v.stage_name,
            v.stage_micro_status,
            v.planned_start,
            v.planned_end,
            v.actual_start,
            v.actual_end,
            v.stage_comments,
            v.document_url,
            s.track_category,
            s.stage_type,
            COALESCE(v.iteration_count, 1) as iteration_count
        FROM v_bi_flat_export v
        LEFT JOIN stages s ON v.stage_name = s.stage_name
        WHERE v.stage_progress_id IS NOT NULL
    """)

def render_analytics_tab(user_role="user"):
    """Отрисовка вкладки 'Аналитика'"""
    # --- ФУНКЦИЯ СБРОСА (Callback) ---
    def reset_analytics_filters():
        # Вместо присвоения "Все", мы просто удаляем ключи. 
        # Тогда виджеты при следующей отрисовке возьмут значения по умолчанию (index=0).
        for key in ["an_sup_filter", "an_proj_filter", "an_period_filter"]:
            if key in st.session_state:
                del st.session_state[key]
    
    st.subheader("📊 Аналитика и операционный контроль")
    
    # Загружаем мастер-данные
    with st.spinner("🔄 Загрузка аналитики..."):
        df_raw = load_analytics_data()
    
    if df_raw.empty:
        st.warning("⚠️ База пуста. Добавьте данные через вкладки 'Поставщики' или 'Проекты'.")
        st.stop()

    # Приводим даты к datetime64
    date_cols = ["planned_start", "planned_end", "actual_start", "actual_end"]
    for col in date_cols:
        if col in df_raw.columns:
            df_raw[col] = pd.to_datetime(df_raw[col], errors="coerce")

    # ==========================================
    # 🔍 ГЛОБАЛЬНЫЕ ФИЛЬТРЫ (Вверху вкладки)
    # ==========================================
    with st.expander("🔍 Глобальные фильтры данных", expanded=True):
        cols = st.columns([2, 2, 2, 1])
        
        with cols[0]:
            suppliers = ["Все"] + sorted(df_raw["supplier_name"].dropna().unique().tolist())
            sel_supplier = st.selectbox("Поставщик", suppliers, key="an_sup_filter", index=0)
        
        with cols[1]:
            # Зависимый фильтр проектов
            if sel_supplier == "Все":
                available_projects = sorted(df_raw["project_name"].dropna().unique().tolist())
            else:
                available_projects = sorted(df_raw[df_raw["supplier_name"] == sel_supplier]["project_name"].dropna().unique().tolist())
            projects = ["Все"] + available_projects
            sel_project = st.selectbox("Проект", projects, key="an_proj_filter", index=0)
            
        with cols[2]:
            periods = ["Все", "Текущая неделя", "Текущий месяц", "Текущий квартал", "Текущий год"]
            sel_period = st.selectbox("Отчётный период", periods, key="an_period_filter", index=0)
        
        with cols[3]:
            st.markdown("<br>", unsafe_allow_html=True)
            st.button(
                "🔄 Сбросить", 
                width='stretch', 
                key="an_reset_btn", 
                on_click=reset_analytics_filters
            )

    # Применение фильтров
    filtered = df_raw.copy()
    if sel_supplier != "Все":
        filtered = filtered[filtered["supplier_name"] == sel_supplier]
    if sel_project != "Все":
        filtered = filtered[filtered["project_name"] == sel_project]
        
    TODAY = pd.Timestamp.today().normalize()

    # Применение фильтра по периоду (попадание в плановые сроки)
    if sel_period != "Все":
        if sel_period == "Текущая неделя":
            start_p = TODAY - pd.Timedelta(days=TODAY.weekday())
            end_p = start_p + pd.Timedelta(days=6)
        elif sel_period == "Текущий месяц":
            start_p = TODAY.replace(day=1)
            next_m = (start_p + pd.Timedelta(days=32)).replace(day=1)
            end_p = next_m - pd.Timedelta(days=1)
        elif sel_period == "Текущий квартал":
            quarter = (TODAY.month - 1) // 3 + 1
            start_p = pd.Timestamp(year=TODAY.year, month=(quarter - 1) * 3 + 1, day=1)
            next_q_month = start_p.month + 3
            if next_q_month > 12:
                end_p = pd.Timestamp(year=TODAY.year, month=12, day=31)
            else:
                end_p = pd.Timestamp(year=TODAY.year, month=next_q_month, day=1) - pd.Timedelta(days=1)
        elif sel_period == "Текущий год":
            start_p = pd.Timestamp(year=TODAY.year, month=1, day=1)
            end_p = pd.Timestamp(year=TODAY.year, month=12, day=31)

        filtered = filtered[
            ((filtered["planned_start"] >= start_p) & (filtered["planned_start"] <= end_p)) |
            ((filtered["planned_end"] >= start_p) & (filtered["planned_end"] <= end_p))
        ]

    # ==========================================
    # 🗂️ ТЕХНИЧЕСКИЕ ПОДВКЛАДКИ СТРИМЛИТ
    # ==========================================
    tabs = st.tabs(["🎯 KPI", "📅 Календарь", "📊 Диаграмма Ганта", "🌡️ Тепловая карта трения", "📄 Отчёты"])

    # ------------------------------------------
    # Подвкладка 1: KPI и Загрузка
    # ------------------------------------------
    with tabs[0]:
        st.markdown("### 🎯 Ключевые управленческие показатели")
        
        # Считаем показатели по типам процессов
        # Соглашения (Проекты) - Бюрократический трек
        active_agreements = filtered[
            (filtered["track_category"] == "1. Документарный") & 
            (filtered["stage_micro_status"] != "Выполнено")
        ]["project_name"].nunique()

        # Протоколы (Наборы) - Технологический трек
        active_protocols = filtered[
            (filtered["track_category"] == "2. Технологический") & 
            (filtered["stage_micro_status"] != "Выполнено")
        ].groupby(["project_name", "dataset_name", "info_name"]).ngroups

        # Просрочки по всем трекам
        overdue_stages = len(filtered[
            filtered["planned_end"].notna() & 
            (filtered["planned_end"] < TODAY) & 
            (filtered["stage_micro_status"] != "Выполнено")
        ])

        # Ближайшие дедлайны
        upcoming_deadlines = len(filtered[
            filtered["planned_end"].notna() & 
            (filtered["planned_end"] >= TODAY) & 
            (filtered["planned_end"] <= TODAY + pd.Timedelta(days=7)) & 
            (filtered["stage_micro_status"] != "Выполнено")
        ])

        kpi_cols = st.columns(4)
        with kpi_cols[0]: st.metric("📜 Соглашений в работе", active_agreements)
        with kpi_cols[1]: st.metric("⚙️ Протоколов в работе", active_protocols)
        with kpi_cols[2]: st.metric("🚨 Просрочено этапов", overdue_stages, delta_color="inverse")
        with kpi_cols[3]: st.metric("📅 Дедлайны ≤7 дней", upcoming_deadlines)

        st.markdown("---")
        col_pie, col_bar = st.columns(2)

        with col_pie:
            st.markdown("##### 🥧 Доли этапов по микростатусам")
            status_counts = filtered["stage_micro_status"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]
            color_map = {
                "В работе": "#4CAF50", "Планируется": "#2196F3", "Ожидание": "#FF9800",
                "Выполнено": "#9E9E9E", "Просрочено": "#F44336", "Отменено": "#607D8B"
            }
            fig_pie = px.pie(status_counts, values="count", names="status", color="status",
                             color_discrete_map=color_map, hole=0.4)
            fig_pie.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_pie, width="stretch")

        with col_bar:
            st.markdown("##### 📊 Распределение активных задач по этапам")
            active_tasks = filtered[filtered["stage_micro_status"] != "Выполнено"]
            if not active_tasks.empty:
                # Группируем по этапам и категории трека
                workload = active_tasks.groupby(["stage_name", "track_category"]).size().reset_index(name="tasks_count")
                fig_bar = px.bar(workload, x="tasks_count", y="stage_name", color="track_category",
                                 orientation="h",
                                 labels={"tasks_count": "Количество активных задач", "stage_name": "Этап", "track_category": "Трек"},
                                 color_discrete_map={"1. Документарный": "#2196F3", "2. Технологический": "#4CAF50"})
                fig_bar.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_bar, width="stretch")
            else:
                st.info("Нет активных задач в выбранном диапазоне.")

    # ------------------------------------------
    # Подвкладка 2: Календарь-Agenda
    # ------------------------------------------
    with tabs[1]:
        st.markdown("### 📅 Интерактивное расписание и планировщик")
        st.caption("Отображаются плановые даты старта и дедлайнов по всем активным процессам.")

        events = []
        for _, row in filtered.iterrows():
            p_start = row["planned_start"]
            p_end = row["planned_end"]
            status = row["stage_micro_status"]
            track = "📜 Бюрократия" if row["track_category"] == "1. Документарный" else "⚙️ Технология"
            label_details = f"{row['dataset_name']} → {row['info_name']}" if pd.notna(row['dataset_name']) else "Соглашение"

            if pd.notna(p_start):
                events.append({
                    "date": p_start.date(),
                    "type": "🚀 Старт этапа",
                    "track": track,
                    "project": row["project_name"],
                    "stage": row["stage_name"],
                    "details": label_details,
                    "status": status
                })
            if pd.notna(p_end):
                is_overdue = p_end < TODAY and status != "Выполнено"
                icon = "🚨 Нарушен дедлайн" if is_overdue else "🎯 Плановый дедлайн"
                events.append({
                    "date": p_end.date(),
                    "type": icon,
                    "track": track,
                    "project": row["project_name"],
                    "stage": row["stage_name"],
                    "details": label_details,
                    "status": status
                })

        if not events:
            st.info("📭 Нет запланированных событий на выбранный период.")
        else:
            events_df = pd.DataFrame(events).sort_values(by="date")
            grouped_events = events_df.groupby("date")
            
            for ev_date, group in grouped_events:
                # Красивое форматирование даты
                date_str = ev_date.strftime("%d.%m.%Y (%A)")
                if ev_date == TODAY.date():
                    date_str = f"🔥 СЕГОДНЯ — {date_str}"
                
                # Показываем красивый спойлер с количеством задач на этот день
                with st.expander(f"📅 {date_str}  —  Событий: {len(group)}"):
                    for _, ev in group.iterrows():
                        color_emoji = "🔴" if "Нарушен" in ev["type"] else ("🟢" if "Старт" in ev["type"] else "🟡")
                        st.markdown(
                            f"{color_emoji} **{ev['type']}** | {ev['track']} | **{ev['project']}** — "
                            f"*{ev['stage']}* | `{ev['details']}` | Статус: `{ev['status']}`"
                        )

    # ------------------------------------------
    # Подвкладка 3: Диаграмма Ганта (Два трека каскадом)
    # ------------------------------------------
    with tabs[2]:
        st.markdown("### 📊 Каскадный Гант-план")
        st.caption("Каскадный график наглядно показывает переход от Бюрократии (синий цвет) к Технологии (зеленый).")

        gantt_data = filtered.dropna(subset=["planned_start", "planned_end"]).copy()
        gantt_data = gantt_data[gantt_data["planned_end"] >= gantt_data["planned_start"]]

        if gantt_data.empty:
            st.warning("⚠️ Нет корректных плановых дат для построения графика.")
        else:
            gantt_mode = st.radio("Режим отображения Ганта", ["По проектам (Общий)", "По наборам данных (Детально)"], horizontal=True, key="an_gantt_mode")
            
            if gantt_mode == "По проектам (Общий)":
                gantt_data["y_axis"] = gantt_data["project_name"]
            else:
                gantt_data["y_axis"] = gantt_data["project_name"] + " | " + gantt_data["dataset_name"].fillna("Бюрократия")

            fig_gantt = px.timeline(
                gantt_data,
                x_start="planned_start",
                x_end="planned_end",
                y="y_axis",
                color="track_category",
                color_discrete_map={"1. Документарный": "#1E88E5", "2. Технологический": "#43A047"},
                hover_data={"stage_name": True, "planned_start": "|%d.%m.%Y", "planned_end": "|%d.%m.%Y", "stage_micro_status": True},
                labels={"y_axis": "Процесс", "track_category": "Трек"}
            )
            fig_gantt.update_yaxes(autorange="reversed")
            fig_gantt.update_layout(height=450, margin=dict(l=150, r=20, t=30, b=20), xaxis_title="Плановые временные рамки")
            st.plotly_chart(fig_gantt, width="stretch")

    # ------------------------------------------
    # Подвкладка 4: Тепловая карта трения
    # ------------------------------------------
    with tabs[3]:
        st.markdown("### 🌡️ Матрицы рисков и технологического трения")
        
        heatmap_mode = st.radio("Анализировать:", ["Юридические задержки (Бюрократия)", "Проблемные итерации (Технология)"], horizontal=True, key="an_heat_mode")

        if heatmap_mode == "Юридические задержки (Бюрократия)":
            st.caption("Показывает среднее количество дней задержки дедлайна по каждому Поставщику и документарному этапу.")
            buro_data = filtered[filtered["track_category"] == "1. Документарный"].copy()
            
            if buro_data.empty:
                st.info("Нет данных для построения карты.")
            else:
                # Вычисляем задержку в днях
                buro_data["delay"] = 0
                mask = buro_data["actual_end"].isna() & (buro_data["planned_end"] < TODAY)
                buro_data.loc[mask, "delay"] = (TODAY - buro_data.loc[mask, "planned_end"]).dt.days
                mask_act = buro_data["actual_end"].notna() & (buro_data["actual_end"] > buro_data["planned_end"])
                buro_data.loc[mask_act, "delay"] = (buro_data.loc[mask_act, "actual_end"] - buro_data.loc[mask_act, "planned_end"]).dt.days
                buro_data["delay"] = buro_data["delay"].clip(lower=0)

                # Строим пивот
                pivot = buro_data.pivot_table(index="supplier_name", columns="stage_name", values="delay", aggfunc="mean").round(1)
                
                fig_heat = px.imshow(pivot, labels=dict(x="Этап Бюрократии", y="Поставщик", color="Задержка (дн.)"),
                                     color_continuous_scale="Reds", aspect="auto")
                fig_heat.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig_heat, width="stretch")

        else:
            st.caption("Показывает среднее количество кругов проверок (итераций) по каждому Набору данных и техническому этапу.")
            tech_data = filtered[filtered["track_category"] == "2. Технологический"].copy()
            
            if tech_data.empty:
                st.info("Нет данных для построения карты.")
            else:
                # Строим пивот
                pivot = tech_data.pivot_table(index="dataset_name", columns="stage_name", values="iteration_count", aggfunc="mean").round(1)
                
                fig_heat = px.imshow(pivot, labels=dict(x="Этап Технологии", y="Набор данных", color="Итерации (среднее)"),
                                     color_continuous_scale="Purples", aspect="auto")
                fig_heat.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig_heat, width="stretch")

    # ------------------------------------------
    # Подвкладка 5: Отчёты
    # ------------------------------------------
    with tabs[4]:
        st.markdown("### 📋 Формирование регламентных отчётов")
        
        report_type = st.selectbox(
            "Выберите тип отчёта для формирования:",
            [
                "1. Реестр подписанных соглашений",
                "2. Сводный отчёт о ходе выполнения (Бюрократия)"
            ],
            index=0
        )
        st.divider()

        if report_type == "1. Реестр подписанных соглашений":
            render_agreement_registry_report(sel_supplier, sel_period)
        else:
            render_progress_bureaucracy_report(sel_supplier, sel_period)

    # 📥 Сохраняем блок экспорта отчета в Excel (в самом низу вкладки)
    st.markdown("---")
    with st.expander("📥 Экспорт сводного отчета в Excel"):
        if st.button("💾 Сформировать и скачать Excel", type="primary", key="an_excel_download"):
            try:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    # Лист 1: Сводка
                    summary = filtered.groupby(["supplier_name", "project_name"]).agg(
                        total=("stage_name", "count"),
                        completed=("stage_micro_status", lambda x: (x == "Выполнено").sum())
                    ).reset_index()
                    summary.to_excel(writer, sheet_name="Сводка", index=False)

                    # Лист 2: Детализация
                    detail = filtered.copy()
                    for col in date_cols:
                        if col in detail.columns:
                            detail[col] = pd.to_datetime(detail[col], errors="coerce").dt.strftime("%d.%m.%Y")
                    detail.to_excel(writer, sheet_name="Детализация", index=False)

                buffer.seek(0)
                filename = f"geodata_report_{pd.Timestamp.today().strftime('%Y%m%d_%H%M')}.xlsx"
                st.download_button(
                    label=f"📥 Скачать {filename}", data=buffer.getvalue(),
                    file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                st.success("✅ Отчёт успешно сформирован!")
            except Exception as e:
                st.error(f"❌ Ошибка генерации Excel: {e}")

# Функции создания отчётов (тест)
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
    
    st.dataframe(
        display_df.style.format({"Дата соглашения": lambda x: x.strftime('%d.%m.%Y')}),
        width='stretch',
        hide_index=True
    )
    
    # Экспорт в XLSX (с защитой формата)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        display_df.to_excel(writer, sheet_name='Реестр', index=False)
        
        workbook  = writer.book
        worksheet = writer.sheets['Реестр']
        
        # Устанавливаем текстовый формат для первой колонки (A), чтобы 1/2026 не стал датой
        text_format = workbook.add_format({'num_format': '@'}) 
        # Формат для даты (ДД.ММ.ГГГГ)
        date_format = workbook.add_format({'num_format': 'dd.mm.yyyy'})

        worksheet.set_column('A:A', 20, text_format)
        worksheet.set_column('B:B', 85)
        worksheet.set_column('C:C', 15, date_format)

    st.download_button(
        label="📥 Скачать реестр (Excel)",
        data=buffer.getvalue(),
        file_name=f"registry_{pd.Timestamp.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def render_progress_bureaucracy_report(sel_supplier, sel_period):
    '''Сводный отчёт по остальным поставщикам'''
    st.markdown("#### ⚙️ Настройки отчёта")
    # Чекбокс фильтрации (пункт 2 твоего запроса)
    hide_completed = st.checkbox("🚫 Скрыть поставщиков с уже подписанными соглашениями", value=False)

    # SQL запрос: теперь тянем и stage_order
    query = """
        WITH last_iterations AS (
            SELECT 
                s.supplier_id,
                s.supplier_name,
                s.is_mandatory,
                stg.stage_name,
                stg.stage_order,
                ps.comments,
                ps.actual_end,
                ROW_NUMBER() OVER(
                    PARTITION BY s.supplier_id, stg.stage_id 
                    ORDER BY ps.iteration_count DESC
                ) as rn
            FROM project_stages ps
            JOIN projects p ON ps.project_id = p.project_id
            JOIN suppliers s ON p.supplier_id = s.supplier_id
            JOIN stages stg ON ps.stage_id = stg.stage_id
            WHERE stg.track_category = '1. Документарный'
              AND p.is_agreement_project = TRUE
              AND ps.actual_end IS NOT NULL
        ),
        completed_suppliers AS (
            -- Находим тех, у кого этап 'Документ подписан' (order=8) уже выполнен
            SELECT DISTINCT supplier_id FROM last_iterations WHERE stage_order = 8
        )
        SELECT 
            li.supplier_id,
            li.supplier_name,
            li.is_mandatory,
            li.stage_name,
            li.stage_order,
            li.comments,
            li.actual_end
        FROM last_iterations li
        WHERE li.rn = 1
    """
    
    if hide_completed:
        query += " AND li.supplier_id NOT IN (SELECT supplier_id FROM completed_suppliers)"

    params = {}
    if sel_supplier != "Все":
        query += " AND li.supplier_name = :sup"
        params["sup"] = sel_supplier

    # Сортировка для корректной работы группировки: Поставщик -> Порядок этапа
    query += " ORDER BY li.supplier_name, li.stage_order ASC"
    
    df = query_db(query, params)

    if df.empty:
        st.info("📭 Данные не найдены.")
        return

    # Переходим к обработке (Шаг 2)
    process_and_show_bureaucracy_report_v2(df)

def process_and_show_bureaucracy_report_v2(df):
    '''формирование и отрисовка для отчёта по остальным поставщикам'''
    df['actual_end'] = pd.to_datetime(df['actual_end'])
    
    # 1. Рассчитываем степень проработки для каждого поставщика (пункт 3 запроса)
    # Находим максимальный stage_order для каждого supplier_id
    max_stages = df.groupby('supplier_name')['stage_order'].max().reset_index()
    
    def define_rank(order):
        return "Высокая (этапы 7-8)" if order >= 7 else "Низкая (этапы 1-6)"
    
    max_stages['rank'] = max_stages['stage_order'].apply(define_rank)
    
    # Мерджим ранг обратно в основной DF
    df = df.merge(max_stages[['supplier_name', 'rank']], on='supplier_name')

    # Формируем строку этапа
    df['Пройденные этапы'] = df.apply(
        lambda x: f"{x['stage_name']} | {x['comments']}" if pd.notna(x['comments']) and x['comments'] != 'Нет' 
        else x['stage_name'], axis=1
    )

    df_mandatory = df[df['is_mandatory'] == True].copy()
    df_others = df[df['is_mandatory'] == False].copy()

    def render_smart_table(sub_df, title, color, use_ranking=False):
        if sub_df.empty: return
        
        st.markdown(f"<h4 style='color: {color};'>{title}</h4>", unsafe_allow_html=True)
        
        # 1. Формируем список колонок и направлений сортировки динамически
        if use_ranking:
            sort_cols = ['rank', 'supplier_name', 'stage_order']
            # В алфавите "В" (Высокая) идет раньше "Н" (Низкая), поэтому True поставит "Высокую" вверх
            asc_logic = [True, True, True] 
        else:
            sort_cols = ['supplier_name', 'stage_order']
            asc_logic = [True, True]

        # Применяем сортировку
        sub_df = sub_df.sort_values(by=sort_cols, ascending=asc_logic)
        
        # 2. Присваиваем № п/п каждому уникальному поставщику в текущем наборе
        # Используем dict.fromkeys, чтобы сохранить порядок появления после сортировки
        unique_sups = list(dict.fromkeys(sub_df['supplier_name']))
        sup_to_no = {name: i+1 for i, name in enumerate(unique_sups)}
        sub_df['№ п/п'] = sub_df['supplier_name'].map(sup_to_no)

        # 3. МЕТОД ЧИСТОЙ ГРУППЫ
        # Отмечаем строки, которые НЕ являются первыми в группе поставщика
        sub_df['is_duplicated'] = sub_df.duplicated(subset=['supplier_name'])
        
        display_df = sub_df.copy()
        
        # ИСПРАВЛЕНИЕ: Принудительно переводим колонки в строковый тип ПЕРЕД занулением
        # Это предотвратит конфликт типов int64 и string
        display_df['№ п/п'] = display_df['№ п/п'].astype(str)
        display_df['supplier_name'] = display_df['supplier_name'].astype(str)
        if use_ranking:
            display_df['rank'] = display_df['rank'].astype(str)

        display_df['Дата'] = display_df['actual_end'].dt.strftime('%d.%m.%Y')
        
        # Зануляем (очищаем) ячейки для всех строк, кроме первой в группе
        display_df.loc[display_df['is_duplicated'] == True, ['№ п/п', 'supplier_name', 'rank' if use_ranking else 'supplier_name']] = ""

        # Выбираем колонки для показа
        final_cols = ['№ п/п', 'supplier_name']
        if use_ranking:
            final_cols.append('rank')
        final_cols.extend(['Пройденные этапы', 'Дата'])

        # Переименовываем заголовки для красоты
        rename_map = {
            'supplier_name': 'Наименование поставщика',
            'rank': 'Проработка'
        }
        # Расчет высоты: заголовок (~35px) + (кол-во строк * высота строки ~35px) + запас
        # Ограничиваем сверху 600 пикселями
        dynamic_height = min(600, (len(display_df) + 1) * 35 + 3)
        
        st.dataframe(
            display_df[final_cols].rename(columns=rename_map), 
            width='stretch', 
            hide_index=True,
            height=dynamic_height
        )

    # Вывод
    render_smart_table(df_mandatory, "⭐ Поставщики обязательных наборов (ОНПД)", "#ff4b4b", use_ranking=True)
    render_smart_table(df_others, "📂 Прочие поставщики", "#31333F", use_ranking=False)