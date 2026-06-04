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
            if st.button("🔄 Сбросить", width="stretch", key="an_reset_btn"):
                st.session_state.an_sup_filter = "Все"
                st.session_state.an_proj_filter = "Все"
                st.session_state.an_period_filter = "Все"
                st.rerun()

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
    tabs = st.tabs(["🎯 KPI", "📅 Календарь", "📊 Диаграмма Ганта", "🌡️ Тепловая карта трения"])

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