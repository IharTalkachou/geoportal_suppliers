import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

TODAY = pd.Timestamp.today().normalize()

def calculate_project_progress(df_project):
    """
    Математическое ядро расчета прогресса.
    """
    if df_project.empty: return None

    def get_track_progress(df_track, track_type):
        # 1. Инициализация дебага (сортируем этапы по старту для наглядности)
        stages_history = []
        if not df_track.empty:
            sorted_history = df_track.sort_values(['actual_start', 'stage_order'], ascending=[True, True])
            stages_history = sorted_history['stage_order'].tolist()

        debug = {
            "stages_in_db": stages_history,
            "max_order": 0,
            "passed_count": 0,
            "current_status": "Нет данных",
            "is_active_visible": False
        }

        if df_track.empty:
            return 0.0, "Не начато", 0.0, 0.0, debug

        # 2. Определение модели (сетки) этапов
        if track_type == 'bureaucracy':
            is_finished = any((df_track['stage_order'] == 8) & (df_track['status'] == 'Выполнено'))
            # Бюрократия: либо 1-7 (если есть заявка), либо 2-7. Этап 8 - финиш, в % не входит.
            has_app = any(df_track['stage_order'] == 1)
            model_orders = [1, 2, 3, 4, 5, 6, 7] if has_app else [2, 3, 4, 5, 6, 7]
        else:
            is_finished = any((df_track['stage_name'] == 'Публикация набора') & (df_track['status'] == 'Выполнено'))
            model_orders = [1, 2, 3, 4, 5]

        if is_finished:
            return 100.0, "Завершено", 100.0, 0.0, debug

        num_stages = len(model_orders)
        stage_weight = 100.0 / num_stages

        # 3. ПОИСК ТЕКУЩЕГО ЭТАПА (Логика: Самый старший НЕ выполненный)
        active_candidates = df_track[df_track['stage_order'].isin(model_orders)]
        if active_candidates.empty:
            return 0.0, "Инициация", 0.0, 0.0, debug

        # Ищем те, что в работе/ожидании/плане
        not_done = active_candidates[active_candidates['status'] != 'Выполнено']
        
        if not not_done.empty:
            # Если есть незавершенные - берем самый старший из них
            current_stage = not_done.sort_values(['stage_order', 'iteration_count'], ascending=[False, False]).iloc[0]
        else:
            # Если все заведенные выполнены - берем самый старший выполненный
            current_stage = active_candidates.sort_values(['stage_order', 'iteration_count'], ascending=[False, False]).iloc[0]

        current_order = current_stage['stage_order']
        debug["max_order"] = current_order
        debug["current_status"] = current_stage['status']

        # 4. РАСЧЕТ ПРОЙДЕННОГО ПУТИ (Абсолютный порядок)
        # Все этапы из модели, которые МЕНЬШЕ текущего — пройдены на 100%
        passed_stages_in_model = [o for o in model_orders if o < current_order]
        debug["passed_count"] = len(passed_stages_in_model)
        total_track_pct = len(passed_stages_in_model) * stage_weight

        # 5. ВКЛАД ТЕКУЩЕГО ЭТАПА
        current_task_readiness = 0.0
        current_task_contribution = 0.0

        if current_stage['status'] == 'Выполнено':
            # Если самый старший этап в БД выполнен - он дает свой вес в общую копилку
            current_task_readiness = 100.0
            current_task_contribution = stage_weight
            total_track_pct += stage_weight
        else:
            # Если этап активен (В работе, Ожидание, Отложено, Планируется)
            debug["is_active_visible"] = True
            
            # Базовая готовность (даже если только начали или отложили)
            # Это гарантирует появление полоски на графике
            current_task_readiness = 10.0 
            
            if current_stage['status'] in ['В работе', 'Ожидание'] and pd.notna(current_stage['actual_start']):
                days_spent = (TODAY - current_stage['actual_start']).days
                norm = current_stage['norm_days'] if current_stage['norm_days'] > 0 else 14
                # Формула насыщения (растет со временем)
                current_task_readiness = (1 - (0.9 / (1 + (max(0, days_spent) / norm)))) * 100
            
            current_task_contribution = (current_task_readiness / 100) * stage_weight
            total_track_pct += current_task_contribution

        return total_track_pct, current_stage['stage_name'], current_task_readiness, current_task_contribution, debug

    # Сбор итогов
    b_total, b_name, b_ready, b_contrib, b_debug = get_track_progress(
        df_project[df_project['track_type'] == 'bureaucracy'], 'bureaucracy'
    )

    tech_data = df_project[df_project['track_type'] == 'tech']
    t_total, t_ready, t_contrib, t_name = 0.0, 0.0, 0.0, "Не начато"
    t_debug_list = []
    
    if not tech_data.empty:
        items = tech_data.groupby('info_name')
        results = [get_track_progress(idf, 'tech') for _, idf in items]
        t_total = sum(r[0] for r in results) / len(results)
        t_ready = sum(r[2] for r in results) / len(results)
        t_contrib = sum(r[3] for r in results) / len(results)
        t_name = next((r[1] for r in results if r[1] != "Завершен"), results[0][1])
        t_debug_list = [r[4] for r in results]

    final_total = (b_total * 0.5) + (t_total * 0.5)
    final_active_part = (b_contrib * 0.5) + (t_contrib * 0.5)
    
    return {
        "project_name": df_project['project_name'].iloc[0],
        "supplier": df_project['supplier_name'].iloc[0],
        "total": round(final_total, 1),
        "passed_part": round(max(0, final_total - final_active_part), 1),
        "active_part": round(final_active_part, 1),
        "active_task_readiness": round((b_ready + t_ready) / 2, 1),
        "status_text": f"📜 {b_name} | ⚙️ {t_name}",
        "debug": {"buro": b_debug, "tech": t_debug_list}
    }

def render_traffic_light_chart(df):
    """Отрисовка Светофора"""
    st.subheader("🚦 Светофор прогресса")
    
    c1, c2, c3 = st.columns([2, 0.7, 0.7])
    with c2:
        show_finished = st.checkbox("Показать завершенные", value=False)
    with c3:
        do_debug = st.toggle("🔍 Отладка", value=False)
    
    all_sups = sorted(df['supplier_name'].unique())
    with c1:
        selected_sups = st.multiselect("Фильтр по поставщикам:", ["Все"] + all_sups, default="Все")
    
    results = []
    # Важно: учитываем все проекты, даже если по ним еще нет этапов
    for pid in df['project_id'].unique():
        proj_df = df[df['project_id'] == pid]
        proj_res = calculate_project_progress(proj_df)
        
        if proj_res:
            # Фильтрация по статусу 5 (Завершено)
            # В snapshot у нас есть поле p.is_agreement_project, но p.status мы не всегда тянем.
            # Поэтому фильтруем по расчетным 99%+
            if not show_finished and proj_res['total'] >= 99.0:
                continue
            
            if "Все" in selected_sups or proj_res['supplier'] in selected_sups:
                results.append(proj_res)
    
    if not results:
        st.info("Нет данных для отображения.")
        return

    res_df = pd.DataFrame(results).sort_values('total', ascending=False)

    fig = go.Figure()
    # 1. Пройденный путь (серый)
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=res_df['passed_part'], name='Завершено', orientation='h',
        marker=dict(color='#BDC3C7'), hoverinfo='skip'
    ))

    # 2. Текущая стадия (синий со штриховкой)
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=res_df['active_part'], name='В работе', orientation='h',
        marker=dict(color='#3498DB', pattern_shape="/"),
        customdata=np.stack((res_df['status_text'], res_df['active_task_readiness'], res_df['total']), axis=-1),
        hovertemplate="<b>%{y}</b><br>Статус: %{customdata[0]}<br>Готовность задачи: <b>%{customdata[1]}%</b><br>Общий прогресс: <b>%{customdata[2]}%</b><extra></extra>"
    ))

    fig.update_layout(
        barmode='stack', height=max(400, len(res_df) * 60), 
        xaxis=dict(title="Процент готовности (%)", range=[0, 100]), 
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        showlegend=False, margin=dict(l=20, r=20, t=20, b=20),
        plot_bgcolor='rgba(0,0,0,0)'
    )

    st.plotly_chart(fig, width='stretch')

    if do_debug:
        st.write("---")
        st.markdown("#### ⚙️ Аудит расчетов (Бюрократия)")
        debug_list = []
        for r in results:
            d = r['debug']['buro']
            debug_list.append({
                "Проект": r['project_name'], "Общий %": r['total'],
                "Цепочка этапов (по старту)": d['stages_in_db'], 
                "Текущий Order": d['max_order'],
                "Статус текущего": d['current_status'], 
                "Пройдено (модель)": d['passed_count'],
                "Видна полоса?": "Да" if d['is_active_visible'] else "Нет"
            })
        st.table(debug_list)