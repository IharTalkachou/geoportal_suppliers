import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache
import plotly.express as px
import io

@st.cache_data(ttl=60, show_spinner=False)
def load_analytics_data():
    """Загружает данные из v_bi_flat_export."""
    return query_db("""
        SELECT 
            supplier_name,
            project_name,
            project_status,
            dataset_name,
            info_name,
            stage_name,
            stage_micro_status,
            planned_start,
            planned_end,
            actual_start,
            actual_end,
            stage_comments,
            document_url
        FROM v_bi_flat_export
        WHERE stage_progress_id IS NOT NULL
    """)

def render_analytics_tab(user_role="user"):
    st.subheader("📊 Аналитика и оперативный контроль")
    
    # 🔍 Фильтры (перенесены из сайдбара в тело вкладки)
    with st.expander("🔍 Фильтры данных", expanded=True):
        cols = st.columns([2, 2, 1])
        
        with cols[0]:
            suppliers = ["Все"] + sorted(load_analytics_data()["supplier_name"].dropna().unique().tolist())
            sel_supplier = st.selectbox("Поставщик", suppliers, key="analytics_sup_filter", index=0)
        
        with cols[1]:
            ref_statuses_df = query_db("SELECT status_name FROM ref_statuses ORDER BY status_id")
            statuses = ["Все"] + ref_statuses_df["status_name"].dropna().unique().tolist()
            sel_status = st.selectbox("Статус проекта", statuses, key="analytics_stat_filter", index=0)
        
        with cols[2]:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 Сбросить", use_container_width=True):
                st.session_state.analytics_sup_filter = "Все"
                st.session_state.analytics_stat_filter = "Все"
                st.rerun()

    with st.spinner("🔄 Загрузка аналитики..."):
        df = load_analytics_data()
    
    if df.empty:
        st.warning("⚠️ База пуста. Добавьте данные через вкладки 'Поставщики' или 'Проекты'.")
        st.stop()

    # Применение фильтров (мгновенно, без кнопки)
    filtered = df.copy()
    if sel_supplier != "Все":
        filtered = filtered[filtered["supplier_name"] == sel_supplier]
    if sel_status != "Все":
        filtered = filtered[filtered["project_status"] == sel_status]

    # 🔑 Приводим даты к datetime64[ns]
    date_cols = ["planned_start", "planned_end", "actual_start", "actual_end"]
    for col in date_cols:
        if col in filtered.columns:
            filtered[col] = pd.to_datetime(filtered[col], errors="coerce")

    TODAY = pd.Timestamp.today()

    # 📈 KPI-карточки
    st.markdown("### 🎯 Ключевые показатели")
    kpi_cols = st.columns(4)
    
    total = len(filtered)
    completed = len(filtered[filtered["stage_micro_status"] == "Выполнено"])
    
    with kpi_cols[0]: st.metric("Всего этапов", total)
    with kpi_cols[1]: st.metric("✅ Завершено", f"{round(completed/total*100) if total else 0}%")
    
    overdue = len(filtered[
        filtered["planned_end"].notna() & 
        (filtered["planned_end"] < TODAY) & 
        (filtered["stage_micro_status"] != "Выполнено")
    ])
    with kpi_cols[2]: st.metric("⚠️ Просрочено", overdue, delta_color="inverse")
    
    soon = len(filtered[
        filtered["planned_end"].notna() &
        (filtered["planned_end"] >= TODAY) &
        (filtered["planned_end"] <= TODAY + pd.Timedelta(days=7)) &
        (filtered["stage_micro_status"] != "Выполнено")
    ])
    with kpi_cols[3]: st.metric("📅 Дедлайн ≤7 дн.", soon)

    # 📋 Оперативная сводка (таблица)
    st.markdown("### 📋 Оперативная сводка")
    display_df = filtered[["supplier_name", "project_name", "dataset_name", "info_name",
                           "stage_name", "stage_micro_status", "planned_start", "planned_end", 
                           "actual_start", "actual_end", "stage_comments", "document_url"]].copy()

    def highlight_overdue(row):
        if (row["stage_micro_status"] != "Выполнено" and 
            pd.notna(row["planned_end"]) and 
            row["planned_end"] < TODAY):
            return ["background-color: #ffebee"] * len(row)
        return [""] * len(row)

    styled_df = display_df.style.apply(highlight_overdue, axis=1)
    styled_df = styled_df.format({
        col: lambda x: x.strftime("%d.%m.%Y") if pd.notna(x) else "" 
        for col in date_cols
    })

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "document_url": st.column_config.LinkColumn("Документ", display_text="📎 Открыть"),
            "stage_comments": st.column_config.TextColumn("Комментарий", width="medium"),
        }
    )
    
    # 📥 Экспорт в Excel
    st.markdown("---")
    with st.expander("📥 Экспорт отчёта в Excel"):
        st.info("💡 Отчёт формируется в памяти и содержит 3 листа: Сводка, Детализация, Данные_Гант")
        
        if st.button("💾 Сформировать и скачать Excel", type="primary"):
            try:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    
                    export_df = filtered.copy()
                    today = pd.Timestamp.today()
                    export_df["is_overdue"] = (
                        export_df["planned_end"].notna() & 
                        (export_df["planned_end"] < today) & 
                        (export_df["stage_micro_status"] != "Выполнено")
                    )

                    # Лист 1: Сводка
                    summary = export_df.groupby(["supplier_name", "project_name"]).agg(
                        total=("stage_name", "count"),
                        completed=("stage_micro_status", lambda x: (x == "Выполнено").sum()),
                        overdue=("is_overdue", "sum")
                    ).reset_index()
                    summary["progress_pct"] = (summary["completed"] / summary["total"] * 100).round(1)
                    summary.to_excel(writer, sheet_name="Сводка", index=False)

                    # Лист 2: Детализация
                    detail = export_df.copy()
                    for col in date_cols:
                        if col in detail.columns:
                            detail[col] = pd.to_datetime(detail[col], errors="coerce").dt.strftime("%d.%m.%Y")
                    detail = detail.drop(columns=["is_overdue"], errors="ignore")
                    detail.to_excel(writer, sheet_name="Детализация", index=False)

                    # Лист 3: Данные для Ганта
                    gantt_data = export_df[["project_name", "stage_name", "planned_start", "planned_end", "stage_micro_status"]].dropna(subset=["planned_start", "planned_end"])
                    gantt_data[["planned_start", "planned_end"]] = gantt_data[["planned_start", "planned_end"]].apply(pd.to_datetime, errors="coerce").apply(lambda x: x.dt.strftime("%d.%m.%Y"))
                    gantt_data.to_excel(writer, sheet_name="Данные_Гант", index=False)

                    # Авто-ширина колонок
                    workbook = writer.book
                    for sheet_name in ["Сводка", "Детализация", "Данные_Гант"]:
                        worksheet = writer.sheets[sheet_name]
                        for i in range(10):  # Примерная ширина
                            worksheet.set_column(i, i, 18)

                buffer.seek(0)
                filename = f"geodata_report_{pd.Timestamp.today().strftime('%Y%m%d_%H%M')}.xlsx"
                st.download_button(
                    label=f"📥 Скачать {filename}",
                    data=buffer.getvalue(),
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                st.success("✅ Отчёт успешно сформирован!")
            except Exception as e:
                st.error(f"❌ Ошибка генерации Excel: {e}")
    
    # 📊 Дополнительные блоки аналитики
    render_process_summary(filtered)
    render_gantt_chart(filtered)
    render_progress_dashboard(filtered)

def render_process_summary(filtered_df):
    st.markdown("---")
    st.subheader("📋 Сводная таблица процессов")
    
    if filtered_df.empty:
        st.info("Нет данных для отображения.")
        return

    df_calc = filtered_df.copy()
    today = pd.Timestamp.today().normalize()
    
    mask_overdue = df_calc["planned_end"].notna() & (df_calc["stage_micro_status"] != "Выполнено")
    df_calc.loc[mask_overdue, "delay_days"] = (today - df_calc.loc[mask_overdue, "planned_end"]).dt.days
    df_calc["delay_days"] = df_calc["delay_days"].fillna(0).clip(lower=0)
    df_calc.loc[df_calc["stage_micro_status"] == "Выполнено", "delay_days"] = 0

    summary_cols = [
        "supplier_name", "project_name", "dataset_name", "info_name", 
        "stage_name", "stage_micro_status", "delay_days", "stage_comments"
    ]
    valid_cols = [c for c in summary_cols if c in df_calc.columns]
    
    summary_df = df_calc[valid_cols].sort_values(by=valid_cols[:-2]).reset_index(drop=True)

    supplier_palette = {}
    colors = ["#e8f5e9", "#e3f2fd", "#fff3e0", "#f3e5f5", "#e0f7fa", "#fce4ec"]
    
    def get_supplier_bg(supplier):
        if supplier not in supplier_palette:
            idx = len(supplier_palette) % len(colors)
            supplier_palette[supplier] = f"background-color: {colors[idx]}"
        return supplier_palette[supplier]

    def highlight_row(row):
        supplier = row["supplier_name"]
        delay = row.get("delay_days", 0)
        status = row.get("stage_micro_status", "")
        
        if delay > 0 and status != "Выполнено":
            return ["background-color: #ffebee"] * len(row)
        return [get_supplier_bg(supplier)] * len(row)

    styled = summary_df.style.apply(highlight_row, axis=1)
    
    styled = styled.format({
        "delay_days": lambda x: f"{int(x)} дн." if x > 0 else "–",
        "stage_comments": lambda x: (str(x)[:60] + "...") if pd.notna(x) and len(str(x)) > 60 else x
    })

    st.dataframe(styled, use_container_width=True, hide_index=True, height=550)
    st.caption("💡 *Красный фон = просроченный этап. Пастельный фон = группировка по поставщику.*")
    
def render_gantt_chart(filtered_df):
    st.markdown("---")
    st.subheader("📅 Гант: Временная шкала проектов")
    
    if filtered_df.empty:
        st.info("Нет данных для отображения.")
        return

    gantt_data = filtered_df[["project_name", "stage_name", "planned_start", "planned_end", "stage_micro_status"]].copy()
    gantt_data = gantt_data.dropna(subset=["planned_start", "planned_end"])
    gantt_data = gantt_data[gantt_data["planned_end"] >= gantt_data["planned_start"]]
    
    if gantt_data.empty:
        st.warning("⚠️ Нет корректных плановых дат для построения графика.")
        return

    color_map = {
        "В работе": "#4CAF50",
        "Планируется": "#2196F3",
        "Ожидание": "#FF9800",
        "Выполнено": "#9E9E9E",
        "Просрочено": "#F44336",
        "Отменено": "#607D8B"
    }

    fig = px.timeline(
        gantt_data,
        x_start="planned_start",
        x_end="planned_end",
        y="project_name", 
        color="stage_micro_status",
        color_discrete_map=color_map,
        hover_data={"stage_name": True, "planned_start": "|%d.%m.%Y", "planned_end": "|%d.%m.%Y"},
        labels={"project_name": "Проект", "stage_micro_status": "Статус этапа"}
    )

    fig.update_yaxes(autorange="reversed") 
    fig.update_layout(
        legend_title_text="Микростатус",
        height=450,
        margin=dict(l=150, r=20, t=30, b=20),
        xaxis_title="Плановые сроки"
    )

    st.plotly_chart(fig, use_container_width=True)
    
def render_progress_dashboard(filtered_df):
    st.markdown("---")
    st.subheader("📊 Прогресс выполнения")
    
    if filtered_df.empty:
        st.info("Нет данных для отображения.")
        return

    st.markdown("### 🎯 Завершённость по уровням")
    cards = st.columns(3)
    
    by_supplier = filtered_df.groupby("supplier_name").apply(
        lambda x: (x["stage_micro_status"] == "Выполнено").sum() / len(x) * 100 if len(x) > 0 else 0
    ).round(1)
    
    with cards[0]:
        avg_supplier = by_supplier.mean()
        st.metric("📁 В среднем по поставщикам", f"{avg_supplier:.1f}%")
        st.progress(avg_supplier / 100)
    
    by_project = filtered_df.groupby("project_name").apply(
        lambda x: (x["stage_micro_status"] == "Выполнено").sum() / len(x) * 100 if len(x) > 0 else 0
    ).round(1)
    
    with cards[1]:
        avg_project = by_project.mean()
        st.metric("📂 В среднем по проектам", f"{avg_project:.1f}%")
        st.progress(avg_project / 100)
    
    by_dataset = filtered_df.groupby("dataset_name").apply(
        lambda x: (x["stage_micro_status"] == "Выполнено").sum() / len(x) * 100 if len(x) > 0 else 0
    ).round(1)
    
    with cards[2]:
        avg_dataset = by_dataset.mean()
        st.metric("🗃️ В среднем по наборам", f"{avg_dataset:.1f}%")
        st.progress(avg_dataset / 100)

    st.markdown("### 📋 Детализация с прогресс-барами")
    
    progress_df = filtered_df.groupby(["supplier_name", "project_name", "dataset_name"]).agg(
        total_stages=("stage_name", "count"),
        completed_stages=("stage_micro_status", lambda x: (x == "Выполнено").sum()),
        info_types=("info_name", lambda x: ", ".join(sorted(x.unique()))[:100])
    ).reset_index()
    
    progress_df["progress_pct"] = (progress_df["completed_stages"] / progress_df["total_stages"] * 100).round(1)
    progress_df["progress_pct"] = progress_df["progress_pct"].clip(0, 100)

    st.dataframe(
        progress_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "supplier_name": st.column_config.TextColumn("Поставщик"),
            "project_name": st.column_config.TextColumn("Проект"),
            "dataset_name": st.column_config.TextColumn("Набор"),
            "total_stages": st.column_config.NumberColumn("Всего этапов", format="%d"),
            "completed_stages": st.column_config.NumberColumn("✅ Завершено", format="%d"),
            "progress_pct": st.column_config.ProgressColumn("Прогресс", min_value=0, max_value=100, format="%.1f%%"),
            "info_types": st.column_config.TextColumn("Виды сведений", width="medium"),
        }
    )

    st.markdown("### 🥧 Загрузка по микро-статусам")
    
    status_counts = filtered_df["stage_micro_status"].value_counts().reset_index()
    status_counts.columns = ["status", "count"]
    
    fig = px.pie(
        status_counts,
        values="count",
        names="status",
        color="status",
        color_discrete_map={
            "В работе": "#4CAF50",
            "Планируется": "#2196F3", 
            "Ожидание": "#FF9800",
            "Выполнено": "#9E9E9E",
            "Просрочено": "#F44336",
            "Отменено": "#607D8B"
        },
        hole=0.4
    )
    
    fig.update_layout(
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
        margin=dict(l=20, r=20, t=30, b=80)
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    st.dataframe(
        status_counts.assign(доля=lambda x: (x["count"] / x["count"].sum() * 100).round(1).astype(str) + "%"),
        hide_index=True,
        use_container_width=True
    )