import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from ui.analytics.data_provider import get_analytics_snapshot
from ui.analytics.kpi_logic import format_date_ru_local # Используем общий хелпер

TODAY = pd.Timestamp.today().normalize()

# Этапы документарного трека, показываемые в матрице по умолчанию: именно на них
# обычно копятся задержки, остальные добавляются вручную. В технологическом треке
# осмысленного короткого списка нет - там по умолчанию показываются все этапы.
BURO_DEFAULT_STAGES = [
    "Запрос переговоров", "Переговоры",
    "Согласование протокола", "Согласование документов",
]

ALL_STAGES_OPTION = "Все"


def render_heatmap_tab():
    st.subheader("🌡️ Матрица задержек")

    # 1. Загрузка данных
    df = get_analytics_snapshot()
    if df.empty:
        st.info("Нет данных для анализа."); return

    # Добавляем UID для идентификации конкретных записей этапов
    df['uid'] = df.apply(lambda x: f"{x['project_id']}_{x['track_type']}_{x['stage_code']}_{x['iteration_count']}", axis=1)

    st.caption(
        "Строка — проект, столбец — этап. Чем насыщеннее клетка, тем больше дней "
        "этап просрочен: число в клетке — дни сверх плановой даты завершения "
        "(у незакрытых этапов — на сегодня). Пустая клетка — этап в срок или не заведён. "
        "Наведите курсор на клетку, чтобы увидеть детали."
    )

    # 2. Глобальные фильтры (без экспандера: он занимал место, а фильтры нужны всегда)
    c1, c2, c3 = st.columns([1.5, 1, 1])
    with c1:
        all_sups = sorted(df['supplier_name'].unique())
        sel_sups = st.multiselect("Поставщики:", ["Все"] + all_sups, default="Все")
    with c2:
        st.write("")
        only_mand = st.checkbox("⭐ Только ОНПД")
    with c3:
        min_delay = st.number_input("Задержка более (дн.):", min_value=0, value=0)

    # Применение первичных фильтров
    f_df = df.copy()
    if "Все" not in sel_sups and sel_sups:
        f_df = f_df[f_df['supplier_name'].isin(sel_sups)]
    if only_mand:
        f_df = f_df[f_df['is_mandatory'] == True]

    # Выбор трека
    modes = ["⚖️ Юридический трек (📄)", "⚙️ Технический трек (💻)"]
    mode = st.radio("Срез анализа:", modes, horizontal=True)
    track = "bureaucracy" if "Юридический" in mode else "tech"

    # Фильтр этапов - свой для каждого трека, поэтому и ключ виджета свой:
    # иначе выбор, сделанный в одном треке, переезжал бы в другой, где таких
    # этапов нет, и матрица оказывалась бы пустой
    track_stages = sorted(f_df[f_df['track_type'] == track]['stage_name'].dropna().unique())
    default_stages = ([s for s in BURO_DEFAULT_STAGES if s in track_stages]
                      if track == "bureaucracy" else [ALL_STAGES_OPTION])
    if not default_stages:
        default_stages = [ALL_STAGES_OPTION]

    sel_stages = st.multiselect(
        "Этапы в матрице:", [ALL_STAGES_OPTION] + track_stages,
        default=default_stages, key=f"hm_stages_{track}")

    # 3. РАСЧЕТ ОТКЛОНЕНИЙ (Logic 2.0)
    # Фильтруем по треку и наличию плана
    data = f_df[(f_df['track_type'] == track) & (f_df['planned_end'].notna())].copy()

    # Пустой выбор приравниваем к "Все": иначе снятие последней галочки давало бы
    # пустой экран вместо матрицы
    if sel_stages and ALL_STAGES_OPTION not in sel_stages:
        data = data[data['stage_name'].isin(sel_stages)]

    if data.empty:
        st.info("В выбранном срезе нет запланированных этапов."); return

    def calc_deviation(row):
        # Если этап выполнен — считаем задержку на момент финиша
        # Если в работе — считаем задержку на текущий день
        finish_point = row['actual_end'] if pd.notna(row['actual_end']) else TODAY
        diff = (finish_point - row['planned_end']).days
        return max(0, diff)

    data['delay'] = data.apply(calc_deviation, axis=1)
    
    # 4. АГРЕГАЦИЯ (Исключаем искажение от количества наборов)
    # Группируем по UID, чтобы взять максимальное отклонение и собрать инфо
    agg_logic = {
        'delay': 'max',             # Берем худший случай по задержке
        'supplier_name': 'first',
        'project_name': 'first',
        'stage_name': 'first',
        'stage_order': 'first',
        'responsible_name': 'first',
        'comments': 'first',
        'info_name': lambda x: ", ".join([v for v in x.unique() if v != '—']), # Список наборов
        'actual_end': 'first'
    }
    
    grouped = data.groupby('uid').agg(agg_logic).reset_index()

    # Фильтр по минимальной задержке
    if min_delay > 0:
        # Оставляем проекты, у которых ХОТЯ БЫ ОДИН этап превысил порог
        projs_with_risks = grouped[grouped['delay'] >= min_delay]['project_name'].unique()
        grouped = grouped[grouped['project_name'].isin(projs_with_risks)]

    if grouped.empty:
        st.warning(f"Задержек более {min_delay} дней не обнаружено."); return

    # 5. ПОСТРОЕНИЕ МАТРИЦЫ
    # Ось Y: Поставщик + Проект
    grouped['y_axis'] = "<b>" + grouped['supplier_name'] + "</b><br>" + grouped['project_name']
    
    # Сортировка этапов по системному порядку
    stages_order_ref = grouped[['stage_name', 'stage_order']].drop_duplicates().sort_values('stage_order')
    
    # 🟢 ИСПРАВЛЕНИЕ: Используем pivot_table вместо pivot. 
    # Если есть несколько итераций одного этапа, aggfunc='max' возьмет самую большую задержку.
    pivot_delay = pd.pivot_table(
        grouped, 
        index='y_axis', 
        columns='stage_name', 
        values='delay', 
        aggfunc='max'
    )
    
    # Синхронизация колонок по системному порядку (из справочника stages)
    cols_ordered = [c for c in stages_order_ref['stage_name'] if c in pivot_delay.columns]
    pivot_delay = pivot_delay.reindex(columns=cols_ordered)
    
    def format_cell(val, uid_list):
        # В этой упрощенной версии Plotly pivot сложно прокинуть активные статусы в текст ячейки
        # Поэтому просто выводим число, если оно > 0
        return int(val) if val > 0 else ""

    # 6. ОТРИСОВКА PLOTLY
    colorscale = "Reds" if track == "bureaucracy" else "Oranges"
    
    fig = go.Figure(data=go.Heatmap(
        z=pivot_delay.values,
        x=pivot_delay.columns,
        y=pivot_delay.index,
        colorscale=colorscale,
        xgap=3, ygap=3,
        zmin=0, zmax=max(20, pivot_delay.max().max() if not pivot_delay.empty else 20),
        colorbar=dict(title="Дни"),
        hovertemplate=(
            "<b>%{y}</b><br>" +
            "Этап: %{x}<br>" +
            "Задержка: <b>%{z} дн.</b><br>" +
            "<extra></extra>"
        )
    ))

    # Настройка внешнего вида
    h = max(400, len(pivot_delay.index) * 60 + 100)
    fig.update_layout(
        height=h,
        xaxis_showgrid=False,
        yaxis_autorange='reversed',
        margin=dict(l=20, r=10, t=10, b=10),
        plot_bgcolor='white'
    )
    
    fig.update_xaxes(side="top", tickangle=-30)

    st.plotly_chart(fig, width='stretch')

    # 7. СПИСОК «ГОРЯЧИХ» КОММЕНТАРИЕВ
    if not grouped[grouped['delay'] > 0].empty:
        st.markdown("---")
        st.markdown("##### 💬 Причины задержек по текущим этапам")
        risks = grouped[(grouped['delay'] > 0) & (grouped['actual_end'].isna())].sort_values('delay', ascending=False)
        for _, r in risks.head(5).iterrows():
            with st.container(border=True):
                st.markdown(f"**{r['project_name']}** → {r['stage_name']} (🚩 {int(r['delay'])} дн.)")
                if r['info_name']: st.caption(f"📦 Наборы: {r['info_name']}")
                st.write(f"_{r['comments'] or 'Комментарий отсутствует'}_")