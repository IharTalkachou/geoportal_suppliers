import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

TODAY = pd.Timestamp.today().normalize()

def calculate_project_progress(df_project):
    """
    Математический расчет прогресса проекта (50/50 Бюрократия/Технология).
    Решает проблему 0% прогресса при отсутствии записей о начальных этапах в БД.
    """
    if df_project.empty:
        return None

    def get_track_progress(df_track, track_type):
        """Расчет для конкретного трека"""
        if df_track.empty: return 0.0, "Не начато", 0.0, 0.0

        # Финишная черта
        if track_type == 'bureaucracy':
            is_finished = any((df_track['stage_order'] == 8) & (df_track['status'] == 'Выполнено'))
        else:
            is_finished = any((df_track['stage_name'] == 'Публикация набора') & (df_track['status'] == 'Выполнено'))
        if is_finished: return 100.0, "Завершено", 100.0, 0.0

        if track_type == 'bureaucracy':
            has_app = any(df_track['stage_order'] == 1)
            model_orders = [1, 2, 3, 4, 5, 6, 7] if has_app else [2, 3, 4, 5, 6, 7]
        else:
            model_orders = [1, 2, 3, 4, 5]

        num_stages = len(model_orders)
        stage_weight = 100.0 / num_stages

        active_in_model = df_track[df_track['stage_order'].isin(model_orders)]
        if active_in_model.empty: return 0.0, "Инициация", 0.0, 0.0

        # Находим самую "дальнюю" стадию
        current_stage = active_in_model.sort_values(['stage_order', 'iteration_count'], ascending=[False, False]).iloc[0]
        current_order = current_stage['stage_order']
        
        # 🟢 ИСПРАВЛЕНИЕ ЛОГИКИ:
        # 1. Все этапы ПЕРЕД текущим — это 100% веса.
        passed_stages_count = len([o for o in model_orders if o < current_order])
        total_track_pct = passed_stages_count * stage_weight

        current_task_readiness = 0.0
        current_task_contribution = 0.0

        # 2. Если ТЕКУЩИЙ (последний в базе) выполнен — добавляем и его вес полностью.
        if current_stage['status'] == 'Выполнено':
            total_track_pct += stage_weight
            current_task_readiness = 100.0
        # 3. Если он в процессе — считаем "затухающий вклад".
        elif current_stage['status'] in ['В работе', 'Ожидание', 'Планируется']:
            if current_stage['stage_type'] == 'Задача' and pd.notna(current_stage['actual_start']):
                # Суммируем дни. Если старт сегодня, days_spent будет 0.
                days_spent = (TODAY - current_stage['actual_start']).days
                norm = current_stage['norm_days'] if current_stage['norm_days'] > 0 else 14
                
                # При days_spent = 0 формула даст готовность 10% (1 - 0.9/1)
                current_task_readiness = (1 - (0.9 / (1 + (days_spent / norm)))) * 100
                current_task_contribution = (current_task_readiness / 100) * stage_weight
                total_track_pct += current_task_contribution

        return total_track_pct, current_stage['stage_name'], current_task_readiness, current_task_contribution

    # Считаем Бюрократию
    b_total, b_name, b_ready, b_contrib = get_track_progress(df_project[df_project['track_type'] == 'bureaucracy'], 'bureaucracy')

    # Считаем Технологию (среднее по всем видам сведений)
    tech_data = df_project[df_project['track_type'] == 'tech']
    t_total, t_ready, t_contrib = 0.0, 0.0, 0.0
    t_name = "Не начато"
    
    if not tech_data.empty:
        items = tech_data.groupby('info_name')
        results = [get_track_progress(idf, 'tech') for _, idf in items]
        t_total = sum(r[0] for r in results) / len(results)
        t_name = next((r[1] for r in results if r[1] != "Завершен"), results[0][1])
        t_ready = sum(r[2] for r in results) / len(results)
        t_contrib = sum(r[3] for r in results) / len(results)

    # Итоговый прогресс проекта (50/50)
    final_total = (b_total * 0.5) + (t_total * 0.5)
    final_contrib = (b_contrib * 0.5) + (t_contrib * 0.5)
    
    return {
        "project_name": df_project['project_name'].iloc[0],
        "supplier": df_project['supplier_name'].iloc[0],
        "total": round(final_total, 1),
        "passed_part": round(final_total - final_contrib, 1),
        "active_part": round(final_contrib, 1),
        "active_task_readiness": round((b_ready + t_ready) / 2, 1), # Средняя готовность текущих задач
        "status_text": f"📜 {b_name} | ⚙️ {t_name}"
    }

def render_traffic_light_chart(df):
    """Отрисовка Светофора с фильтром и исправленными тултипами"""
    st.subheader("🚦 Светофор прогресса")
    
    # --- 🟢 НОВЫЕ ФИЛЬТРЫ ---
    c1, c2 = st.columns([2, 1])
    with c2:
        show_finished = st.checkbox("✅ Показать завершенные проекты", value=False)

    # --- ПРОБЛЕМА №7: ФИЛЬТР ПОСТАВЩИКОВ ---
    all_sups = sorted(df['supplier_name'].unique())
    with c1:
        selected_sups = st.multiselect("🔍 Фильтр по поставщикам:", ["Все"] + all_sups, default="Все")
    
    results = []
    for pid in df['project_id'].unique():
        proj_res = calculate_project_progress(df[df['project_id'] == pid])
        if proj_res:
            # Фильтр завершенных: если не просили показывать 100%, убираем их
            if not show_finished and proj_res['total'] >= 99.9:
                continue

            # Фильтр по поставщикам
            if "Все" in selected_sups or proj_res['supplier'] in selected_sups:
                results.append(proj_res)
            
    if not results:
        st.info("Нет данных для отображения.")
        return

    res_df = pd.DataFrame(results).sort_values('total', ascending=False)

    # Построение диаграммы
    fig = go.Figure()

    # 1. Завершенные этапы
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=res_df['passed_part'],
        name='Пройденный путь',
        orientation='h',
        marker=dict(color='#BDC3C7'),
        hoverinfo='skip'
    ))

    # 2. Активный этап
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=res_df['active_part'],
        name='Текущая стадия',
        orientation='h',
        marker=dict(color='#3498DB', pattern_shape="/"),
        customdata=np.stack((res_df['status_text'], res_df['active_task_readiness'], res_df['total']), axis=-1),
        hovertemplate=(
            "<b>%{y}</b><br>" +
            "Текущий статус: %{customdata[0]}<br>" +
            "Готовность текущей задачи: <b>%{customdata[1]}%</b><br>" +
            "Общий прогресс проекта: <b>%{customdata[2]}%</b><extra></extra>"
        )
    ))

    fig.update_layout(
        barmode='stack',
        height=max(400, len(res_df) * 60),
        xaxis=dict(title="Прогресс (%)", range=[0, 100]),
        yaxis=dict(autorange="reversed"),
        showlegend=False,
        margin=dict(l=20, r=20, t=20, b=20)
    )

    st.plotly_chart(fig, use_container_width=True)