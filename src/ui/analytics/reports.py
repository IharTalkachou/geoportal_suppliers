import streamlit as st
import pandas as pd
import io
from datetime import datetime
from config.cache import query_db
from ui.analytics.data_provider import get_analytics_snapshot
from ui.shared_components import render_survey_viewer

def render_reports_tab():
    st.subheader("📋 Формирование регламентных отчётов")
    
    report_type = st.selectbox("Выберите тип отчёта:", [
        "1. Реестр подписанных соглашений", 
        "2. Сводный отчёт о ходе выполнения (Бюрократия)", 
        "3. Реестр предоставляемых сведений", 
        "4. Просмотр технических опросников"
    ], key="report_type_sel")

    if report_type == "1. Реестр подписанных соглашений":
        _render_agreement_registry()
    elif report_type == "2. Сводный отчёт о ходе выполнения (Бюрократия)":
        _render_bureaucracy_progress()
    elif report_type == "3. Реестр предоставляемых сведений":
        _render_provided_data_registry()
    elif report_type == "4. Просмотр технических опросников":
        _render_survey_explorer()

# ==========================================
# 1. РЕЕСТР СОГЛАШЕНИЙ
# ==========================================
def _render_agreement_registry():
    df = get_analytics_snapshot()
    # Фильтруем: Бюрократия, этап 8, статус Выполнено
    mask = (df['track_type'] == 'bureaucracy') & (df['stage_order'] == 8) & (df['status'] == 'Выполнено')
    data = df[mask].copy()

    if data.empty:
        st.info("Подписанные соглашения не найдены.")
        return

    data = data.sort_values('actual_end')
    data['Дата соглашения'] = data['actual_end'].dt.date
    
    # Формируем номер 1/2026
    data = data.reset_index(drop=True)
    data['Номер'] = data.index + 1
    data['№ Соглашения'] = data.apply(lambda x: f"{x['Номер']}/{x['actual_end'].year}", axis=1)

    display_df = data[['№ Соглашения', 'supplier_name', 'Дата соглашения']].rename(columns={'supplier_name': 'Поставщик'})
    
    st.dataframe(display_df, width="stretch", hide_index=True,
                 column_config={"Дата соглашения": st.column_config.DateColumn(format="DD.MM.YYYY")})

    # Excel
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        display_df.to_excel(writer, index=False, sheet_name='Реестр')
    
    st.download_button("📥 Скачать Excel", buffer.getvalue(), "registry.xlsx", "application/vnd.ms-excel")

# ==========================================
# 2. ХОД ВЫПОЛНЕНИЯ (БЮРОКРАТИЯ)
# ==========================================
def _render_bureaucracy_progress():
    df_raw = get_analytics_snapshot()
    df = df_raw[(df_raw['track_type'] == 'bureaucracy') & 
                (df_raw['is_agreement_project'] == True) & 
                (df_raw['actual_end'].notna())].copy()

    if df.empty:
        st.info("Нет данных о пройденных этапах бюрократии.")
        return

    show_done = st.checkbox("Показать завершенные проекты", value=False)
    completed_ids = df[df['stage_order'] == 8]['project_id'].unique()
    if not show_done:
        df = df[~df['project_id'].isin(completed_ids)]

    # Агрегация данных
    df = df.sort_values(['is_mandatory', 'supplier_name', 'actual_end', 'stage_order'])
    df['new_grp'] = (df['stage_name'] != df['stage_name'].shift()) | (df['supplier_name'] != df['supplier_name'].shift())
    df['grp_id'] = df['new_grp'].cumsum()

    grouped = df.groupby(['grp_id', 'supplier_name', 'is_mandatory', 'stage_name']).agg({
        'actual_end': ['min', 'max'],
        'comments': lambda x: ". ".join([str(c) for c in x if pd.notna(c) and str(c) != 'Нет'])
    }).reset_index()
    grouped.columns = ['id', 'supplier', 'is_mand', 'stage', 'd_min', 'd_max', 'comms']

    grouped['Дата'] = grouped.apply(lambda x: x['d_min'].strftime('%d.%m.%Y') if x['d_min']==x['d_max'] 
                                    else f"{x['d_min'].strftime('%d.%m.%Y')}–{x['d_max'].strftime('%d.%m.%Y')}", axis=1)
    grouped['Этап'] = grouped.apply(lambda x: f"{x['stage']} | {x['comms']}" if x['comms'] else x['stage'], axis=1)

    # ОТРИСОВКА В ЭКСПАНДЕРАХ С УМНЫМ РАСЧЕТОМ ВЫСОТЫ
    for mand_status, title, exp_key, is_exp in [(True, "⭐ Поставщики ОНПД", "exp_mand", True), 
                                                (False, "📂 Прочие поставщики", "exp_other", False)]:
        sub = grouped[grouped['is_mand'] == mand_status].copy()
        with st.expander(title, expanded=is_exp):
            if not sub.empty:
                disp = sub.copy()
                disp['Поставщик'] = disp['supplier']
                disp.loc[disp.duplicated('supplier'), 'Поставщик'] = ""
                
                # --- УМНЫЙ РАСЧЕТ ВЫСОТЫ ---
                # 35px на строку + 38px на заголовок + 2px запас
                calculated_h = (len(disp) * 35) + 40
                # Ограничиваем: минимум 100 (чтобы не схлопнулось совсем), максимум 600
                final_h = min(600, max(100, calculated_h))
                
                st.dataframe(disp[['Поставщик', 'Этап', 'Дата']], 
                             width="stretch", hide_index=True, height=final_h)
            else:
                st.write("Данные отсутствуют")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚀 Сгенерировать сводный Excel", type="primary"):
        xlsx = _export_bureaucracy_islands(grouped)
        st.download_button("📥 Скачать файл", xlsx, f"progress_report_{datetime.now().strftime('%d_%m')}.xlsx")

def _export_bureaucracy_islands(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        ws = workbook.add_worksheet('Ход выполнения')
        
        # Стили
        fmt_head = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1, 'align': 'center'})
        fmt_cell = workbook.add_format({'border': 1, 'valign': 'vcenter', 'text_wrap': True})
        
        headers = ['№ п/п', 'Поставщик', 'Пройденные этапы', 'Дата']
        for c, h in enumerate(headers): ws.write(0, c, h, fmt_head)

        curr_row = 1
        for i, (name, group) in enumerate(df.groupby('supplier', sort=False)):
            num_rows = len(group)
            # Объединяем ячейки для названия и номера
            if num_rows > 1:
                ws.merge_range(curr_row, 0, curr_row + num_rows - 1, 0, i + 1, fmt_cell)
                ws.merge_range(curr_row, 1, curr_row + num_rows - 1, 1, name, fmt_cell)
            else:
                ws.write(curr_row, 0, i + 1, fmt_cell)
                ws.write(curr_row, 1, name, fmt_cell)
            
            for _, row in group.iterrows():
                ws.write(curr_row, 2, row['Этап'], fmt_cell)
                ws.write(curr_row, 3, row['Дата'], fmt_cell)
                curr_row += 1
        
        ws.set_column('B:B', 30); ws.set_column('C:C', 60); ws.set_column('D:D', 20)
    return output.getvalue()

# ==========================================
# 3. РЕЕСТР СВЕДЕНИЙ
# ==========================================
def _render_provided_data_registry():
    # 🟢 1. ЗАПРОС С ФОРМАТАМИ И ФИЛЬТРОМ ПРАВ
    query = """
        SELECT s.supplier_name, it.info_name, pi.provision_right, it.format
        FROM project_items pi
        JOIN projects p ON pi.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN info_types it ON pi.info_id = it.info_id
        WHERE pi.provision_right != 'Протокол не заключён'
        ORDER BY s.supplier_name, it.info_name
    """
    df = query_db(query)
    
    if df.empty:
        st.info("Данные не найдены (или у всех статус 'Протокол не заключён').")
        return

    # 🟢 2. ФИЛЬТР ПО ПОСТАВЩИКАМ (МУЛЬТИБОКС)
    all_sups = sorted(df['supplier_name'].unique().tolist())
    sel_sups = st.multiselect("🔍 Выберите поставщиков:", all_sups, placeholder="Все доступные", key="reg3_sup_filter")
    
    display_df = df.copy()
    if sel_sups:
        display_df = display_df[display_df['supplier_name'].isin(sel_sups)]

    if display_df.empty:
        st.warning("Нет данных по выбранным поставщикам.")
        return

    # 🟢 3. ЛОГИКА ПРОПУСКА ДУБЛИКАТОВ (ДЛЯ ЭКРАНА)
    viz_df = display_df.copy()
    viz_df['Поставщик'] = viz_df['supplier_name']
    viz_df.loc[viz_df.duplicated('supplier_name'), 'Поставщик'] = ""
    
    st.markdown(f"**Найдено видов сведений:** {len(display_df)}")
    st.dataframe(
        viz_df[['Поставщик', 'info_name', 'provision_right', 'format']], 
        width="stretch", hide_index=True, height=600,
        column_config={
            "info_name": "Вид сведений",
            "provision_right": "Право предоставления",
            "format": "Форматы данных"
        }
    )

    # 🟢 4. ЭКСПОРТ В EXCEL
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        # Для Excel передаем данные БЕЗ маскировки дублей (библиотека сама объединит ячейки)
        _export_registry_to_excel_internal(display_df, writer)
    
    st.download_button(
        "📥 Скачать реестр сведений (Excel)", 
        buffer.getvalue(), 
        "data_registry.xlsx", 
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def _export_registry_to_excel_internal(df, writer):
    """Внутренняя магия Excel для Реестра сведений"""
    workbook = writer.book
    ws = workbook.add_worksheet('Реестр')
    
    # Стили
    fmt_head = workbook.add_format({'bold': True, 'bg_color': '#DEEAF6', 'border': 1, 'align': 'center'})
    fmt_cell = workbook.add_format({'border': 1, 'valign': 'vcenter', 'text_wrap': True})

    headers = ['Поставщик', 'Вид сведений', 'Право предоставления', 'Форматы']
    for c, h in enumerate(headers): ws.write(0, c, h, fmt_head)

    curr_row = 1
    # Группируем для объединения ячеек поставщика
    for name, group in df.groupby('supplier_name', sort=False):
        num_rows = len(group)
        if num_rows > 1:
            ws.merge_range(curr_row, 0, curr_row + num_rows - 1, 0, name, fmt_cell)
        else:
            ws.write(curr_row, 0, name, fmt_cell)
        
        for _, row in group.iterrows():
            ws.write(curr_row, 1, row['info_name'], fmt_cell)
            ws.write(curr_row, 2, row['provision_right'], fmt_cell)
            ws.write(curr_row, 3, row['format'], fmt_cell)
            curr_row += 1

    ws.set_column('A:A', 30); ws.set_column('B:B', 40); ws.set_column('C:C', 30); ws.set_column('D:D', 20)

# ==========================================
# 4. ПРОВОДНИК ОПРОСНИКОВ
# ==========================================
def _render_survey_explorer():
    st.markdown("#### 🔍 Проводник по опросникам")
    
    # 1. Загружаем только тех, у кого есть опросники
    sups = query_db("""
        SELECT DISTINCT s.supplier_id, sup.supplier_name 
        FROM surveys s JOIN suppliers sup ON s.supplier_id = sup.supplier_id ORDER BY sup.supplier_name
    """)
    
    if sups.empty:
        st.info("Опросники не найдены.")
        return

    sel_sup = st.selectbox("Выберите поставщика:", sups['supplier_name'].tolist(), key="exp_sup")
    sid = int(sups[sups['supplier_name'] == sel_sup]['supplier_id'].iloc[0])

    surveys = query_db("""
        SELECT survey_id, received_date FROM surveys WHERE supplier_id = :sid ORDER BY received_date DESC
    """, {"sid": sid})

    if surveys.empty:
        st.write("У этого поставщика нет опросников.")
    else:
        opts = {f"Опросник от {r['received_date'].strftime('%d.%m.%Y')} (ID: {r['survey_id']})": r['survey_id'] for _, r in surveys.iterrows()}
        sel_srv = st.selectbox("Выберите дату:", list(opts.keys()))
        st.divider()
        render_survey_viewer(None, opts[sel_srv], is_readonly=True)