import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

TODAY = pd.Timestamp.today().normalize()

def calculate_project_progress(df_project):
    if df_project.empty: return None

    # --- 1. БЮРОКРАТИЯ (Макс: 50.0) ---
    def get_buro_score(df):
        # Цепочка этапов
        model = ['NEGOTIATIONS', 'PROTOCOL_NEGOTIATIONS', 'SET_APPOINTMENT', 'VERIFICATION', 'DOCUMENT_APPROVAL', 'CONTRACT_SIGNED']
        weight_per_step = 50.0 / len(model) # ~8.33% за шаг
        
        if df.empty: return 0.0, 0.0, "Не начато"
        
        # Находим самый "дальний" заведенный этап (по порядку в модели)
        active_stages = df[df['stage_code'].isin(model)].copy()
        if active_stages.empty: return 0.0, 0.0, "Инициация"

        latest = active_stages.sort_values('stage_order', ascending=False).iloc[0]
        curr_idx = model.index(latest['stage_code'])
        
        passed = 0.0
        active = 0.0
        
        # Считаем вес всех этапов ДО текущего, которые имеют статус 'Выполнено' в базе
        # или просто считаем их пройденными, так как мы на более позднем этапе
        passed = curr_idx * weight_per_step
        
        if latest['status'] == 'Выполнено':
            passed += weight_per_step
        else:
            # Расчет активной части (в работе / ожидании / отложено)
            readiness = 0.05 # Базовый "хвостик" для Планируется/Отложено
            if latest['status'] in ['В работе', 'Ожидание']:
                if pd.notna(latest['actual_start']):
                    days = (TODAY - latest['actual_start']).days
                    norm = latest['norm_days'] if latest['norm_days'] > 0 else 10
                    readiness = min(0.9, max(0.1, days / norm))
                    # Штраф за просрочку
                    if pd.notna(latest['planned_end']) and TODAY > latest['planned_end']:
                        readiness = min(readiness, 0.5)
                else:
                    readiness = 0.1
            active = readiness * weight_per_step
            
        return passed, active, latest['stage_name']

    # --- 2. ТЕХНОЛОГИЯ (Макс: 50.0) ---
    def get_tech_item_score(df_item):
        if df_item.empty: return 0.0, 0.0, "Не начато", 0, 0, 0
        
        # Динамическое распределение весов
        # Проверяем, какие блоки вообще присутствуют в истории этого набора
        has_prep_tasks = df_item['stage_code'].isin(['TESTING', 'TECH_REG_PROC']).any()
        
        # Если подготовки нет в базе, отдаем её 5% в пользу Метаданных и Данных
        if has_prep_tasks:
            w_prep, w_meta, w_data = 5.0, 22.5, 22.5
        else:
            w_prep, w_meta, w_data = 0.0, 25.0, 25.0

        # А. Расчет подготовки (если есть)
        p_passed, p_active = 0.0, 0.0
        if w_prep > 0:
            for code in ['TESTING', 'TECH_REG_PROC']:
                row = df_item[df_item['stage_code'] == code]
                if not row.empty:
                    if row.iloc[0]['status'] == 'Выполнено': p_passed += 2.5
                    else: p_active += 0.05 * 2.5

        # Б. Циклы
        def calc_loop(codes, total_weight):
            loop_df = df_item[df_item['stage_code'].isin(codes)]
            if loop_df.empty: return 0.0, 0.0
            
            # Финальный успех в цикле
            if any((df_item['stage_code'] == codes[-1]) & (df_item['status'] == 'Выполнено')):
                return total_weight, 0.0

            latest = loop_df.sort_values('stage_order', ascending=False).iloc[0]
            idx = codes.index(latest['stage_code'])
            step_w = total_weight / len(codes)
            
            pw = idx * step_w
            ac = 0.0
            
            if latest['status'] == 'Выполнено':
                pw += step_w
            else:
                readiness = 0.05
                if latest['status'] in ['В работе', 'Ожидание']:
                    days = (TODAY - latest['actual_start']).days if pd.notna(latest['actual_start']) else 0
                    readiness = min(0.9, max(0.1, days / (latest['norm_days'] or 10)))
                    if pd.notna(latest['planned_end']) and TODAY > latest['planned_end']:
                        readiness = min(readiness, 0.5)
                ac = readiness * step_w
            return pw, ac

        m_p, m_a = calc_loop(['META_WAIT', 'META_CHECK', 'META_REJECT', 'META_FIX', 'META_PUB'], w_meta)
        d_p, d_a = calc_loop(['DATA_WAIT', 'DATA_CHECK', 'DATA_REJECT', 'DATA_FIX', 'DATA_PUB'], w_data)
        
        item_name = df_item.sort_values('stage_order', ascending=False).iloc[0]['stage_name']
        return (p_passed + m_p + d_p), (p_active + m_a + d_a), item_name, p_passed, m_p, d_p

    # --- СБОРКА ---
    b_p, b_a, b_name = get_buro_score(df_project[df_project['track_type'] == 'bureaucracy'])
    
    t_data = df_project[df_project['track_type'] == 'tech']
    t_p, t_a, t_name = 0.0, 0.0, "Не начато"
    debug_tech = {"prep": 0, "meta": 0, "data": 0}
    
    if not t_data.empty:
        item_groups = t_data.groupby('info_name')
        res = [get_tech_item_score(idf) for _, idf in item_groups]
        t_p = sum(r[0] for r in res) / len(res)
        t_a = sum(r[1] for r in res) / len(res)
        t_name = res[0][2]
        debug_tech = {"prep": sum(r[3] for r in res)/len(res), "meta": sum(r[4] for r in res)/len(res), "data": sum(r[5] for r in res)/len(res)}

    total = b_p + t_p + b_a + t_a
    return {
        "project_name": df_project['project_name'].iloc[0],
        "supplier": df_project['supplier_name'].iloc[0],
        "passed_part": round(b_p + t_p, 2),
        "active_part": round(b_a + t_a, 2),
        "total": round(min(100.0, total), 1),
        "status_text": f"📜 {b_name} | ⚙️ {t_name}",
        "debug_vals": {"buro": b_p, "prep": debug_tech['prep'], "meta": debug_tech['meta'], "data": debug_tech['data'], "buro_active": b_a}
    }

def render_traffic_light_chart(df):
    st.subheader("🚦 Светофор прогресса")
    
    c1, c2, c3 = st.columns([2, 0.7, 0.7])
    all_sups = sorted(df['supplier_name'].unique().tolist())
    with c1: selected_sups = st.multiselect("Фильтр по поставщикам:", ["Все"] + all_sups, default="Все", key="tl_sup_filter")
    with c2: show_finished = st.checkbox("Показать 100%", value=False, key="tl_show_fin")
    with c3: do_debug = st.toggle("🔍 Отладка", value=False, key="tl_debug_toggle")
    
    results = []
    for pid in df['project_id'].unique():
        proj_res = calculate_project_progress(df[df['project_id'] == pid])
        if proj_res:
            if not show_finished and proj_res['total'] >= 99.9: continue
            if "Все" in selected_sups or proj_res['supplier'] in selected_sups:
                results.append(proj_res)
    
    if not results:
        st.info("Нет данных."); return

    res_df = pd.DataFrame(results).sort_values('total', ascending=False)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=res_df['passed_part'], name='Пройдено', orientation='h',
        marker=dict(color='#BDC3C7'), hoverinfo='skip'
    ))

    # Штриховка всегда видна (минимум 1.5%), если есть активная часть
    x_active_viz = res_df['active_part'].apply(lambda x: max(x, 1.5) if x > 0 else 0)
    
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=x_active_viz, name='В работе', orientation='h',
        marker=dict(color='#3498DB', pattern_shape="/"),
        customdata=np.stack((res_df['status_text'], res_df['total']), axis=-1),
        hovertemplate="<b>%{y}</b><br>Статус: %{customdata[0]}<br>Прогресс: <b>%{customdata[1]}%</b><extra></extra>"
    ))

    fig.update_layout(
        barmode='stack', height=max(400, len(res_df) * 60),
        xaxis=dict(title="Готовность %", range=[0, 100]),
        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
        showlegend=False, margin=dict(l=20, r=20, t=20, b=20), plot_bgcolor='rgba(0,0,0,0)'
    )

    st.plotly_chart(fig, width='stretch')

    if do_debug:
        st.write("---")
        st.markdown("#### ⚙️ Детализация баллов")
        dbg_data = []
        for r in results:
            v = r['debug_vals']
            dbg_data.append({
                "Проект": r['project_name'],
                "Итого %": r['total'],
                "Бюро (зав)": v['buro'],
                "Бюро (раб)": round(v['buro_active'], 2),
                "Тех-Подг": v['prep'],
                "Метаданные": v['meta'],
                "Данные": v['data']
            })
        st.table(dbg_data)