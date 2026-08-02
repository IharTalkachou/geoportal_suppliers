import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
from config.cache import query_db

# Глобальные настройки времени
TODAY = pd.Timestamp.today().normalize()

def get_stage_data(df, stage_code):
    """Возвращает строку последней итерации этапа или None"""
    data = df[df['stage_code'] == stage_code]
    if data.empty: 
        return None
    return data.sort_values('iteration_count', ascending=False).iloc[0]

def get_sla_ratio(row):
    """
    Вычисляет SLA-коэффициент (отношение пройденных дней к нормативу).
    Для этапов в статусе "Планируется" или "Отложено" коэффициент фиксируется на 0.2.
    Для активных этапов — строго в диапазоне [0.2, 0.9].
    """
    if row is None or not isinstance(row, pd.Series): 
        return 0.0
    
    if row['status'] == 'Выполнено': 
        return 0.0
        
    # Базовый коэффициент 0.2 для отложенных и запланированных этапов
    if row['status'] in ['Отложено', 'Планируется']:
        return 0.2
    
    actual_start = pd.to_datetime(row['actual_start']) if pd.notna(row['actual_start']) else TODAY
    days = (TODAY - actual_start).days
    norm = row['norm_days'] if 'norm_days' in row and row['norm_days'] > 0 else 10
    
    return min(0.9, max(0.2, days / norm))

def calculate_buro_progress(df):
    """Сценарии расчета прогресса бюрократического стека (0-100%)"""
    df = df.copy()
    df['stage_code'] = df['stage_code'].astype(str).str.strip()
    codes_in_df = df['stage_code'].unique().tolist()
    
    has_ext = any(c in ['CHANGES_PROTOCOL', 'ADDITIONAL_AGREEMENT'] for c in codes_in_df)
    
    # --- БЛОК Б (Проекты с CHANGES_PROTOCOL или ADDITIONAL_AGREEMENT) ---
    if has_ext:
        # CP (5%) и AA (5%) считаются независимо
        cp_df = df[df['stage_code'] == 'CHANGES_PROTOCOL']
        if not cp_df.empty:
            total_cp = len(cp_df)
            done_cp = len(cp_df[cp_df['status'] == 'Выполнено'])
            latest_cp = cp_df.loc[cp_df['iteration_count'].idxmax()]
            
            if latest_cp['status'] == 'Выполнено':
                passed_cp = 5.0
                active_cp = 0.0
            else:
                passed_cp = 5.0 * (done_cp / total_cp)
                active_cp = 5.0 * (get_sla_ratio(latest_cp) / total_cp)
        else:
            passed_cp = 0.0
            active_cp = 0.0
            
        aa_df = df[df['stage_code'] == 'ADDITIONAL_AGREEMENT']
        if not aa_df.empty:
            total_aa = len(aa_df)
            done_aa = len(aa_df[aa_df['status'] == 'Выполнено'])
            latest_aa = aa_df.loc[aa_df['iteration_count'].idxmax()]
            
            if latest_aa['status'] == 'Выполнено':
                passed_aa = 5.0
                active_aa = 0.0
            else:
                passed_aa = 5.0 * (done_aa / total_aa)
                active_aa = 5.0 * (get_sla_ratio(latest_aa) / total_aa)
        else:
            passed_aa = 0.0
            active_aa = 0.0
            
        progress = 90.0 + passed_cp + active_cp + passed_aa + active_aa
        return min(100.0, progress), (90.0 + passed_cp + passed_aa), (active_cp + active_aa), f"Ext: 90% + CP({passed_cp:.1f}% passed + {active_cp:.1f}% active) + AA({passed_aa:.1f}% passed + {active_aa:.1f}% active)"

    # --- БЛОК А (Проекты без CHANGES_PROTOCOL и ADDITIONAL_AGREEMENT) ---
    
    # А.1. CONTRACT_SIGNED
    if 'CONTRACT_SIGNED' in codes_in_df:
        cs_rows = df[df['stage_code'] == 'CONTRACT_SIGNED']
        if not cs_rows.empty and (cs_rows['status'] == 'Выполнено').any():
            return 100.0, 100.0, 0.0, "Contract Signed: 100%"

    # А.2. DOCUMENT_APPROVAL
    if 'DOCUMENT_APPROVAL' in codes_in_df:
        da_df = df[df['stage_code'] == 'DOCUMENT_APPROVAL']
        if not da_df.empty:
            latest_idx = da_df['iteration_count'].idxmax()
            latest_iter = da_df.loc[latest_idx]
            
            if latest_iter['status'] == 'Выполнено':
                return 100.0, 100.0, 0.0, "Doc Approved: 100%"
            
            total_count = len(da_df)
            done_count = len(da_df[da_df['status'] == 'Выполнено'])
            ratio = get_sla_ratio(latest_iter)
            
            passed = 50.0 + (50.0 * done_count / total_count)
            active = 50.0 * ratio / total_count
            progress = passed + active
            return min(100.0, progress), passed, active, f"DocApp: 50 + 50*({done_count}/{total_count}) + 50*({ratio:.2f}/{total_count})"

    # А.3. SET_APPOINTMENT (Старт с 5-го этапа)
    if 'SET_APPOINTMENT' in codes_in_df:
        verification_df = df[df['stage_code'] == 'VERIFICATION']
        
        if not verification_df.empty:
            total_count = len(verification_df)
            done_count = len(verification_df[verification_df['status'] == 'Выполнено'])
            latest_iter = verification_df.loc[verification_df['iteration_count'].idxmax()]
            
            if latest_iter['status'] == 'Выполнено':
                return 50.0, 50.0, 0.0, "Verification Approved: 50%"
            else:
                ratio = get_sla_ratio(latest_iter)
                passed = 25.0 + 25.0 * (done_count / total_count)
                active = 25.0 * (ratio / total_count)
                progress = passed + active
                return progress, passed, active, f"SetApp: 25% + 25%*({done_count} done + {ratio:.2f} active)/{total_count}"
        else:
            set_app_df = df[df['stage_code'] == 'SET_APPOINTMENT']
            if not set_app_df.empty:
                total_count = len(set_app_df)
                done_count = len(set_app_df[set_app_df['status'] == 'Выполнено'])
                latest_iter = set_app_df.loc[set_app_df['iteration_count'].idxmax()]
                
                if latest_iter['status'] == 'Выполнено':
                    return 25.0, 25.0, 0.0, "SetAppointment Approved: 25%"
                else:
                    ratio = get_sla_ratio(latest_iter)
                    passed = 25.0 * (done_count / total_count)
                    active = 25.0 * (ratio / total_count)
                    progress = passed + active
                    return progress, passed, active, f"SetApp: 25%*({done_count} done + {ratio:.2f} active)/{total_count}"
            return 0.0, 0.0, 0.0, "SetApp: No Data"

    # А.4. Остальные проекты (START_APP и переговоры)
    nego_stages = ['NEGOTIATIONS_REQUEST', 'NEGOTIATIONS']
    present_nego = [s for s in nego_stages if s in codes_in_df]
    
    if present_nego:
        total_count = 0
        done_count = 0
        for s in nego_stages:
            s_df = df[df['stage_code'] == s]
            if not s_df.empty:
                total_count += len(s_df)
                done_count += len(s_df[s_df['status'] == 'Выполнено'])
                
        if total_count == 0: 
            total_count = 1
            
        nego_df = df[df['stage_code'].isin(present_nego)]
        latest_iter = nego_df.loc[nego_df['iteration_count'].idxmax()]
        
        group_w = 45.0 if 'START_APP' in codes_in_df else 50.0
        base_w = 5.0 if 'START_APP' in codes_in_df else 0.0
        
        if latest_iter['status'] == 'Выполнено':
            progress = base_w + group_w
            return min(100.0, progress), progress, 0.0, "Nego: Completed"
        else:
            ratio = get_sla_ratio(latest_iter)
            passed = base_w + group_w * (done_count / total_count)
            active = group_w * (ratio / total_count)
            progress = passed + active
            desc_name = "StartApp" if 'START_APP' in codes_in_df else "Nego"
            return min(100.0, progress), passed, active, f"{desc_name}: {base_w}% + {group_w}%*({done_count} done + {ratio:.2f} active)/{total_count}"
            
    # Если заведен только START_APP
    if 'START_APP' in codes_in_df:
        return 5.0, 5.0, 0.0, "StartApp: 5% (Negotiations not started)"

    return 0.0, 0.0, 0.0, "Инициация: 0%"

# Воронка технологического трека — реальный порядок stage_code из справочника stages
# (track_category = '2. Технологический', отсортировано по stage_order).
# NG_CONSULT и TECH_SUPPORT сознательно исключены: это повторяющиеся консультационные
# этапы, не блокирующие и не продвигающие воронку готовности набора.
TECH_FUNNEL_CODES = [
    'WAITING_TEST', 'TESTING', 'TECH_CALL', 'PROTOCOL_APPROVAL',
    'TECH_REG_WAIT', 'TECH_REG_PROC',
    'META_WAIT', 'META_CHECK', 'META_REJECT', 'META_FIX', 'META_PUB',
    'DATA_WAIT', 'DATA_CHECK', 'DATA_REJECT', 'DATA_FIX', 'DATA_PUB',
]

def calculate_tech_progress(df, sid):
    """Сценарии расчета прогресса технологического стека (0-100%)"""
    df = df.copy()
    df['stage_code'] = df['stage_code'].astype(str).str.strip()

    # affected_item_ids разворачивается в SQL через CROSS JOIN LATERAL, из-за чего
    # одна итерация этапа, затрагивающая N наборов, попадает в снапшот N одинаковыми
    # строками. Для расчёта прогресса нужна ровно одна строка на (stage_code, iteration_count).
    df = df.drop_duplicates(subset=['stage_code', 'iteration_count'])

    # 1. Проверка наличия администратора у поставщика (5% бонусом сверху воронки)
    admin_query = """
        SELECT 1
        FROM reg_request_users rru
        JOIN reg_requests rr ON rru.req_id = rr.req_id
        WHERE rru.is_admin = TRUE
          AND rru.is_active = TRUE
          AND rr.result_supplier_id = :sid
        LIMIT 1
    """
    is_admin = not query_db(admin_query, {"sid": sid}).empty

    admin_w = 5.0
    funnel_w = 100.0 - admin_w
    step_w = funnel_w / len(TECH_FUNNEL_CODES)

    tech_passed = 0.0
    tech_active = 0.0

    if is_admin:
        tech_passed += admin_w

    # Равномерный расчёт по всей реальной воронке этапов, с автозачётом пропущенных
    # промежуточных шагов (если этапа нет в базе, но заведён более поздний по воронке —
    # считаем ранний пройденным) и с разносом по итерациям, как раньше.
    step_descs = []
    for i, code in enumerate(TECH_FUNNEL_CODES):
        stage_df = df[df['stage_code'] == code]
        is_row_present = not stage_df.empty

        higher = [c for c in TECH_FUNNEL_CODES[i + 1:] if not df[df['stage_code'] == c].empty]
        is_done_via_higher = (not is_row_present and len(higher) > 0)

        if is_done_via_higher:
            tech_passed += step_w
            continue

        if is_row_present:
            total_count = len(stage_df)
            done_count = len(stage_df[stage_df['status'] == 'Выполнено'])
            latest_iter = stage_df.loc[stage_df['iteration_count'].idxmax()]

            if latest_iter['status'] == 'Выполнено':
                tech_passed += step_w
            else:
                ratio = get_sla_ratio(latest_iter)
                tech_passed += step_w * (done_count / total_count)
                tech_active += step_w * (ratio / total_count)
                step_descs.append(f"{code}: {done_count}/{total_count} done, ratio={ratio:.2f}")

    tech_total = tech_passed + tech_active

    desc_parts = [f"Admin: {'5%' if is_admin else '0%'}"]
    if step_descs:
        desc_parts.append("Active: " + "; ".join(step_descs))

    return tech_total, tech_passed, tech_active, " | ".join(desc_parts)

def calculate_project_progress(df_project):
    """Математическое ядро расчета общего прогресса проекта"""
    if df_project.empty: 
        return None
    
    sid = int(df_project['supplier_id'].iloc[0])
    
    # 1. Рассчитываем БЮРОКРАТИЮ (50% проекта)
    b_df = df_project[df_project['track_type'] == 'bureaucracy']
    buro_total, buro_passed, buro_active, buro_desc = calculate_buro_progress(b_df)
    
    # 2. Рассчитываем ТЕХНОЛОГИЮ (50% проекта)
    t_df = df_project[df_project['track_type'] == 'tech']
    tech_total, tech_passed, tech_active, tech_desc = calculate_tech_progress(t_df, sid)
    
    # Сбор весов и деление пополам
    sum_passed = (buro_passed * 0.5) + (tech_passed * 0.5)
    sum_active = (buro_active * 0.5) + (tech_active * 0.5)
    total = sum_passed + sum_active
    
    if total > 99.0: 
        total = 100.0 
        
    # Рассчитываем готовность текущей активной задачи
    active_rows = df_project[df_project['status'].isin(['В работе', 'Ожидание', 'Отложено', 'Планируется'])]
    if not active_rows.empty:
        max_ratio = max([get_sla_ratio(row) for _, row in active_rows.iterrows()])
        active_task_readiness = max_ratio * 100.0
    else:
        active_task_readiness = 100.0 if total >= 100.0 else 0.0
        
    # ПУНКТ 2: Формируем структурированный HTML-текст попапа для активных этапов
    popup_parts = []
    if not active_rows.empty:
        for _, row in active_rows.iterrows():
            stage_name = row['stage_name']
            comments = row['comments'] if pd.notna(row['comments']) and str(row['comments']).strip() != "" else "Нет комментариев"
            
            # Логика определения даты фактического или планового начала
            if pd.notna(row['actual_start']):
                date_str = pd.to_datetime(row['actual_start']).strftime('%d.%m.%Y')
                work_text = f"Работа с {date_str}"
            elif pd.notna(row['planned_start']):
                date_str = pd.to_datetime(row['planned_start']).strftime('%d.%m.%Y')
                work_text = f"Планируется с {date_str}"
            else:
                work_text = "Дата старта не определена"
                
            popup_parts.append(f"<b>{stage_name}</b><br>{comments}<br>{work_text}")
        popup_html = "<br><br>".join(popup_parts)
    else:
        popup_html = "Все этапы проекта успешно завершены"

    audit = {
        "BUREAUCRACY": {"weight": 50.0, "readiness": buro_total / 100.0, "status": "Done" if buro_total >= 100.0 else "Active"},
        "TECHNOLOGY": {"weight": 50.0, "readiness": tech_total / 100.0, "status": "Done" if tech_total >= 100.0 else "Active"}
    }
    
    return {
        "project_name": df_project['project_name'].iloc[0],
        "supplier": df_project['supplier_name'].iloc[0],
        "total": round(total, 1),
        "passed_part": round(sum_passed, 1),
        "active_part": round(sum_active, 1),
        "active_task_readiness": round(active_task_readiness, 1),
        "status_text": f"📜 {buro_desc.split(' (')[0]} | ⚙️ {tech_desc.split(' | ')[0]}",
        "audit": audit,
        "popup_html": popup_html
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
    for pid in df['project_id'].unique():
        proj_df = df[df['project_id'] == pid]
        proj_res = calculate_project_progress(proj_df)
        
        if proj_res:
            if not show_finished and proj_res['total'] >= 99.0:
                continue
            
            if "Все" in selected_sups or proj_res['supplier'] in selected_sups:
                results.append(proj_res)

    if not results:
        st.info("Нет данных для отображения.")
        return

    res_df = pd.DataFrame(results).sort_values('total', ascending=False)

    # ПУНКТ 1: Формируем текстовые метки процента для отображения на столбцах диаграммы
    # Если active_part > 0, цифру total рисуем на штрихованном баре. Если active_part == 0, рисуем её на сером баре.
    completed_labels = [f"<b>{t:.1f}%</b>" if p > 0 else "" for t, p in zip(res_df['total'], res_df['passed_part'])]
    #active_labels = [f"<b>{t:.1f}%</b>" if a > 0 else "" for t, a in zip(res_df['total'], res_df['active_part'])]

    fig = go.Figure()
    
    # 1. Пройденный путь (серый) — теперь метка ВСЕГДА центрируется внутри него
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=res_df['passed_part'], name='Завершено', orientation='h',
        marker=dict(color='#BDC3C7'), hoverinfo='skip',
        text=completed_labels, 
        textposition='inside',  # Центрирует текст ровно посередине серого столбика
        textfont=dict(color='white', size=11)
    ))

    # 2. Текущая стадия (синий со штриховкой) — убираем отсюда текст, чтобы исключить наслоение на полосы
    fig.add_trace(go.Bar(
        y=res_df['supplier'] + "<br><sup>" + res_df['project_name'] + "</sup>",
        x=res_df['active_part'], name='В работе', orientation='h',
        marker=dict(color='#3498DB', pattern_shape="/"),
        customdata=np.stack((res_df['active_task_readiness'], res_df['total'], res_df['popup_html']), axis=-1),
        hovertemplate=(
            "<b>%{y}</b><br><br>"
            "Общий прогресс проекта: <b>%{customdata[1]}%</b><br>"
            "Текущая задача выполнена на: <b>%{customdata[0]}%</b><br><br>"
            "%{customdata[2]}<extra></extra>"
        )
    ))

    fig.update_layout(
        barmode='stack', height=max(400, len(res_df) * 60), 
        xaxis=dict(title="Процент готовности (%)", range=[0, 100]), 
        yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
        showlegend=False, margin=dict(l=20, r=20, t=20, b=20),
        plot_bgcolor='rgba(0,0,0,0)'
    )

    st.plotly_chart(fig, width='stretch')

    # Детальный аудит весов в режиме отладки
    if do_debug:
        st.write("---")
        st.markdown("#### ⚙️ Сводный аудит весов и прогресса")
        debug_list = []
        
        for r in results:
            buro_vals = r['audit']['BUREAUCRACY']
            tech_vals = r['audit']['TECHNOLOGY']
            
            debug_list.append({
                "Проект": r['project_name'],
                "Общий прогресс (%)": f"{r['total']}%",
                "Бюрократия (Прогресс стека, %)": f"{buro_vals['readiness'] * 100.0:.1f}%",
                "Технология (Прогресс стека, %)": f"{tech_vals['readiness'] * 100.0:.1f}%",
                "Пройденная часть (серый, %)": f"{r['passed_part']}%",
                "В работе (штриховка, %)": f"{r['active_part']}%"
            })
            
        if debug_list:
            st.table(pd.DataFrame(debug_list))

def render_bureaucracy_audit_table(df):
    """Аудит бюрократических этапов"""
    st.subheader("📋 Аудит бюрократических этапов")
    
    b_df = df[df['track_type'] == 'bureaucracy']
    
    all_stages = ['START_APP', 'NEGOTIATIONS_REQUEST', 'NEGOTIATIONS', 'PROTOCOL_NEGOTIATIONS', 
                  'SET_APPOINTMENT', 'VERIFICATION', 'DOCUMENT_APPROVAL', 'CONTRACT_SIGNED', 
                  'CHANGES_PROTOCOL', 'ADDITIONAL_AGREEMENT']
    
    audit_data = []
    
    for pid in b_df['project_id'].unique():
        proj_b = b_df[b_df['project_id'] == pid]
        pct, passed, active, desc = calculate_buro_progress(proj_b)
        
        row_dict = {
            "Проект": proj_b['project_name'].iloc[0],
            "Расчёт прогресса": f"{pct:.1f}% | {desc}"
        }
        
        for stage in all_stages:
            stage_rows = proj_b[proj_b['stage_code'] == stage]
            if not stage_rows.empty:
                total_iter = stage_rows['iteration_count'].max()
                active_iter = stage_rows[stage_rows['status'].isin(['В работе', 'Ожидание', 'Отложено', 'Планируется'])].shape[0]
                row_dict[stage] = f"{total_iter} / {active_iter}"
            else:
                row_dict[stage] = "-"
        
        audit_data.append(row_dict)
    
    audit_df = pd.DataFrame(audit_data)
    st.dataframe(audit_df, width='stretch')

def render_project_progress_audit_table(df):
    """
    Отрисовывает детальную таблицу сквозного аудита всех расчетов проекта,
    включая формулы с префиксом итогового процента по каждому стеку,
    деление на слои графика (серый/штрихованный) и текст попапа.
    """
    st.subheader("📋 Комплексный аудит прогресса и формул расчетов")
    
    audit_data = []
    
    for pid in df['project_id'].unique():
        proj_df = df[df['project_id'] == pid]
        if proj_df.empty:
            continue
            
        sid = int(proj_df['supplier_id'].iloc[0])
        
        # 1. Бюрократия
        proj_b = proj_df[proj_df['track_type'] == 'bureaucracy']
        buro_pct, _, _, buro_formula = calculate_buro_progress(proj_b)
        
        # 2. Технология
        proj_t = proj_df[proj_df['track_type'] == 'tech']
        tech_pct, _, _, tech_formula = calculate_tech_progress(proj_t, sid)
        
        # 3. Общая сборка
        res = calculate_project_progress(proj_df)
        if not res:
            continue
            
        # Форматируем красивый текстовый попап для отображения внутри Pandas Dataframe
        clean_popup_text = res['popup_html'].replace('<br>', '\n').replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')
        
        formatted_buro = f"{buro_pct:.1f}% | {buro_formula}"
        formatted_tech = f"{tech_pct:.1f}% | {tech_formula}"
        
        audit_data.append({
            "Проект": res['project_name'],
            "Формула расчета Бюрократии": formatted_buro,
            "Формула расчета Технологии": formatted_tech,
            "Общий прогресс": f"{res['total']}%",
            "Пройденная часть (серый)": f"{res['passed_part']}%",
            "В работе (штриховка)": f"{res['active_part']}%",
            "Текст попапа при наведении": clean_popup_text
        })
        
    audit_df = pd.DataFrame(audit_data)
    st.dataframe(audit_df, width='stretch')

def render_tech_audit_table(df):
    """Аудит технологических этапов"""
    st.subheader("📋 Аудит технологических этапов")
    
    t_df = df[df['track_type'] == 'tech']

    all_stages = TECH_FUNNEL_CODES + ['NG_CONSULT', 'TECH_SUPPORT']
    
    audit_data = []
    
    for pid in df['project_id'].unique():
        proj_df = df[df['project_id'] == pid]
        proj_t = proj_df[proj_df['track_type'] == 'tech']
        
        sid = int(proj_df['supplier_id'].iloc[0])
        total, passed, active, desc = calculate_tech_progress(proj_t, sid)
        
        row_dict = {
            "Проект": proj_df['project_name'].iloc[0],
            "Расчёт прогресса": f"{total:.1f}% | {desc}"
        }
        
        admin_query = """
            SELECT 1 
            FROM reg_request_users rru
            JOIN reg_requests rr ON rru.req_id = rr.req_id
            WHERE rru.is_admin = TRUE 
              AND rru.is_active = TRUE 
              AND rr.result_supplier_id = :sid
            LIMIT 1
        """
        is_admin = not query_db(admin_query, {"sid": sid}).empty
        row_dict['ADMIN'] = "Зарегистрирован" if is_admin else "—"
        
        for stage in all_stages:
            stage_rows = proj_t[proj_t['stage_code'] == stage]
            if not stage_rows.empty:
                total_iter = stage_rows['iteration_count'].max()
                active_iter = stage_rows[stage_rows['status'].isin(['В работе', 'Ожидание', 'Отложено', 'Планируется'])].shape[0]
                row_dict[stage] = f"{total_iter} / {active_iter}"
            else:
                row_dict[stage] = "-"
        
        audit_data.append(row_dict)
        
    audit_df = pd.DataFrame(audit_data)
    st.dataframe(audit_df, width='stretch')