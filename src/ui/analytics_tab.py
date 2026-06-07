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