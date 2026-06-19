import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from ui.analytics.data_provider import get_analytics_snapshot

TODAY = pd.Timestamp.today().normalize()

def render_heatmap_tab():
    st.subheader("🌡️ Матрицы рисков (Дни отклонения от плана)")
    
    # 1. Загрузка данных
    df = get_analytics_snapshot()
    if df.empty:
        st.info("Нет данных для построения тепловых карт.")
        return

    # 2. Глобальные фильтры для карт
    with st.expander("🔍 Фильтры тепловых карт", expanded=True):
        c1, c2 = st.columns([2, 1])
        with c1:
            all_sups = sorted(df['supplier_name'].unique())
            sel_sups = st.multiselect("Выберите поставщиков:", ["Все"] + all_sups, default="Все", key="hm_sups")
        with c2:
            st.write("<br>", unsafe_allow_html=True)
            only_mand = st.checkbox("⭐ Только ОНПД", value=False, key="hm_mand")

    # Применение фильтрации
    filtered_df = df.copy()
    if "Все" not in sel_sups and sel_sups:
        filtered_df = filtered_df[filtered_df['supplier_name'].isin(sel_sups)]
    if only_mand:
        filtered_df = filtered_df[filtered_df['is_mandatory'] == True]

    if filtered_df.empty:
        st.warning("Нет данных по выбранным критериям.")
        return

    # 3. Выбор режима отображения
    modes = ["⚖️ Юридический трек (Бюрократия)", "⚙️ Технический трек (Технология)"]
    mode = st.radio("Выберите срез анализа:", modes, horizontal=True, key="hm_mode_radio")

    if mode == modes[0]:
        _draw_heatmap(filtered_df, "bureaucracy", "Reds")
    else:
        _draw_heatmap(filtered_df, "tech", "Greens")

def _draw_heatmap(df, track_type, color_scale):
    """Внутренняя функция отрисовки карты для конкретного трека"""
    # Фильтруем трек и записи с плановыми датами
    data = df[(df['track_type'] == track_type) & (df['planned_end'].notna())].copy()
    
    if data.empty:
        st.info(f"Нет данных по треку {track_type}")
        return

    # Расчет отклонения
    def calc_dev(row):
        # Если завершено - считаем по факту, если нет - по сегодняшней дате
        finish = row['actual_end'] if pd.notna(row['actual_end']) else TODAY
        diff = (finish - row['planned_end']).days
        return max(0, diff)

    data['deviation'] = data.apply(calc_dev, axis=1)
    data['is_active'] = data['actual_end'].isna()
    
    # Формируем подпись для оси Y
    data['y_label'] = data['supplier_name'] + "<br><i>" + data['project_name'] + "</i>"

    # Агрегация итераций ( Islands Logic )
    grouped = data.groupby(['y_label', 'stage_name', 'stage_order']).agg({
        'deviation': 'sum',
        'iteration_count': 'count',
        'is_active': 'any'
    }).reset_index()

    # Текст внутри ячейки
    def get_cell_text(row):
        val = int(row['deviation'])
        if val == 0: return ""
        suffix = "⚡" if row['is_active'] else ""
        return f"{val}{suffix}"

    grouped['cell_text'] = grouped.apply(get_cell_text, axis=1)

    # Подготовка матриц
    stages_order = grouped[['stage_name', 'stage_order']].drop_duplicates().sort_values('stage_order')
    unique_stages = stages_order['stage_name'].tolist()
    
    pivot_val = grouped.pivot(index="y_label", columns="stage_name", values="deviation")
    pivot_txt = grouped.pivot(index="y_label", columns="stage_name", values="cell_text")
    
    # Синхронизация колонок по порядку этапов
    cols = [c for c in unique_stages if c in pivot_val.columns]
    pivot_val = pivot_val.reindex(columns=cols)
    pivot_txt = pivot_txt.reindex(columns=cols).fillna("")

    # Отрисовка Plotly
    fig = go.Figure(data=go.Heatmap(
        z=pivot_val.values,
        x=pivot_val.columns,
        y=pivot_val.index,
        text=pivot_txt.values,
        texttemplate="%{text}",
        colorscale=color_scale,
        zmin=0, 
        zmax=max(15, pivot_val.max().max() if not pivot_val.empty else 15),
        xgap=2, ygap=2,
        hovertemplate="<b>%{y}</b><br>Этап: %{x}<br>Отклонение: %{z} дн.<extra></extra>"
    ))

    # Динамическая высота (чтобы не было сплюснуто)
    h = max(400, len(pivot_val.index) * 50 + 150)
    
    fig.update_layout(
        height=h,
        xaxis_showgrid=False,
        yaxis_autorange='reversed',
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)'
    )
    
    st.plotly_chart(fig, width='stretch')