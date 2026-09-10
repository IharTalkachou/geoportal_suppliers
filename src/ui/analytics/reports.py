import streamlit as st
import pandas as pd
import io
from datetime import datetime
from sqlalchemy.orm import Session
from config.database import engine
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENT

from config.cache import query_db
from config.settings_handler import load_settings
from ui.analytics.data_provider import get_analytics_snapshot
from ui.shared_components import render_survey_viewer
from ui.analytics.report_docx import render_monthly_report_tab

def render_reports_tab():
    st.subheader("📋 Формирование регламентных отчётов")
    
    report_type = st.selectbox("Выберите тип отчёта:", [
        "1. Реестр подписанных соглашений",
        "2. Отчёт о ходе согласования документов",
        "3. Отчёт о ходе технической работы",
        "4. Реестр предоставляемых сведений",
        "5. Реестр протоколов совещаний",
        "6. Просмотр технических опросников",
        "7. Формирование месячного отчёта НИПД",
        "8. Реестр учётных записей пользователей",
        "9. Сводный отчёт о Поставщиках Национального геопортала"
    ], key="report_type_sel")

    if report_type == "1. Реестр подписанных соглашений":
        _render_agreement_registry()
    elif report_type == "2. Отчёт о ходе согласования документов":
        _render_bureaucracy_progress()
    elif report_type == "3. Отчёт о ходе технической работы":
        _render_technology_progress()
    elif report_type == "4. Реестр предоставляемых сведений":
        _render_provided_data_registry()
    elif report_type == "5. Реестр протоколов совещаний":
        _render_meeting_minutes_registry() # 👈 ВЫЗОВ НОВОЙ ФУНКЦИИ
    elif report_type == "6. Просмотр технических опросников":
        _render_survey_explorer()
    elif report_type == "7. Формирование месячного отчёта НИПД":
        with Session(engine) as sess:
            render_monthly_report_tab(sess)
    elif report_type == "8. Реестр учётных записей пользователей":
        _render_accounts_registry()
    elif report_type == "9. Сводный отчёт о Поставщиках Национального геопортала":
        _render_supplier_projects_summary()

# ==========================================
# 1. РЕЕСТР СОГЛАШЕНИЙ
# ==========================================
def _render_agreement_registry():
    """
    Отчёт 1: Реестр подписанных соглашений (Интерактивный архив).
    Показывает только тех, у кого подписано основное Соглашение, 
    но собирает документы со всех доп. протоколов поставщика.
    """
    st.markdown("#### 📜 Электронный реестр соглашений и протоколов")
    
    # 1. Получаем список "Квалифицированных" поставщиков (у кого есть выполненный этап Соглашения)
    # Используем прямой SQL, так как нам нужны ID для последующей связки
    qualifiers_query = """
        SELECT 
            s.supplier_id, 
            s.supplier_name, 
            ps.actual_end as main_sign_date
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE p.is_agreement_project = TRUE  -- Признак основного соглашения
          AND (stg.stage_name = 'Документ подписан' OR stg.stage_code = 'CONTRACT_SIGNED')
          AND ms.micro_status_name = 'Выполнено'
          AND ps.actual_end IS NOT NULL
        ORDER BY ps.actual_end ASC
    """
    qualifiers = query_db(qualifiers_query)

    if qualifiers.empty:
        st.info("📭 Подписанные соглашения пока не найдены.")
        return

    # 2. Документы всех проектов поставщика: соглашение и протоколы.
    # Раньше ссылки брались из stage_documents, прикреплённых к этапу
    # "Документ подписан", но теперь соглашения и протоколы - самостоятельные
    # сущности (project_documents), и вложений на этапе больше не заводят.
    #
    # Охват показывается рядом со ссылкой: сразу видно, к каким видам сведений
    # относится протокол. Пустой охват = документ покрывает весь проект,
    # поэтому подставляется весь его состав.
    docs_query = """
        SELECT
            pd.doc_id, pd.doc_kind, pd.doc_number, pd.doc_url,
            pd.is_signed, pd.signed_date AS sign_date,
            p.project_name, p.supplier_id, p.is_agreement_project,
            COALESCE(
                (SELECT string_agg(
                            CASE WHEN itp.part_name IS NOT NULL
                                 THEN i.info_name || ' → ' || itp.part_name
                                 ELSE i.info_name END, '; '
                            ORDER BY i.info_name, itp.sort_order NULLS LAST)
                   FROM project_document_items pdi
                   JOIN project_items pi ON pdi.item_id = pi.item_id
                   JOIN info_types i ON pi.info_id = i.info_id
                   LEFT JOIN info_type_parts itp ON pdi.part_id = itp.part_id
                  WHERE pdi.doc_id = pd.doc_id),
                (SELECT string_agg(DISTINCT i.info_name, '; ')
                   FROM project_items pi
                   JOIN info_types i ON pi.info_id = i.info_id
                  WHERE pi.project_id = p.project_id)
            ) AS coverage
        FROM project_documents pd
        JOIN projects p ON pd.project_id = p.project_id
        WHERE pd.doc_url IS NOT NULL AND btrim(pd.doc_url) <> ''
        ORDER BY pd.signed_date ASC NULLS LAST,
                 CASE WHEN pd.doc_kind = 'Соглашение' THEN 0 ELSE 1 END,
                 pd.doc_id
    """
    all_docs = query_db(docs_query)

    # 3. Отрисовка реестра через экспандеры
    st.write(f"Всего в реестре: **{len(qualifiers)}** поставщиков")
    st.markdown("<br>", unsafe_allow_html=True)

    for i, row in qualifiers.iterrows():
        # Формируем номер соглашения (1/2026)
        year = row['main_sign_date'].year
        agr_num = f"{i + 1}/{year}"
        
        # Заголовок экспандера
        expander_title = f"📄 № {agr_num} | {row['supplier_name']} (от {row['main_sign_date'].strftime('%d.%m.%Y')})"
        
        with st.expander(expander_title):
            # Фильтруем документы этого конкретного поставщика
            sup_docs = all_docs[all_docs['supplier_id'] == row['supplier_id']]
            
            if sup_docs.empty:
                st.caption("К записям в базе не прикреплено ни одного файла.")
            else:
                st.markdown("**Прикрепленные документы (Соглашение и Протоколы):**")

                # Выводим документы по одному
                for _, doc in sup_docs.iterrows():
                    col_icon, col_link = st.columns([0.05, 0.95])
                    with col_icon:
                        # Соглашение выделяем иконкой
                        st.write("📜" if doc['doc_kind'] == 'Соглашение' else "📎")
                    with col_link:
                        num = (str(doc['doc_number']).strip()
                               if pd.notna(doc['doc_number']) and str(doc['doc_number']).strip() else "")
                        name = f"{doc['doc_kind']} {num}".strip()
                        date_txt = (doc['sign_date'].strftime('%d.%m.%Y')
                                    if pd.notna(doc['sign_date']) else "без даты")
                        # Подпись: Дата | Документ | к каким видам сведений относится
                        btn_label = f"{date_txt} | {name}"
                        if pd.notna(doc['coverage']) and str(doc['coverage']).strip():
                            btn_label += f" : {doc['coverage']}"
                        st.link_button(btn_label, doc['doc_url'], width='stretch')

    # 4. Кнопка экспорта (оставим стандартную таблицу для Excel)
    st.markdown("---")
    if st.button("📊 Сформировать таблицу для Excel"):
        # Готовим плоский список для выгрузки
        export_df = qualifiers.copy()
        export_df.insert(0, "№ Соглашения", [f"{idx+1}/{d.year}" for idx, d in enumerate(export_df['main_sign_date'])])
        export_df = export_df.rename(columns={'supplier_name': 'Поставщик', 'main_sign_date': 'Дата'})
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            export_df[['№ Соглашения', 'Поставщик', 'Дата']].to_excel(writer, index=False, sheet_name='Реестр')
        
        st.download_button("📥 Скачать таблицу", buffer.getvalue(), "registry_table.xlsx")

# ==========================================
# 2. ХОД СОГЛАСОВАНИЯ ДОКУМЕНТОВ (БЮРОКРАТИЯ)
# ==========================================
def _fmt_date(d):
    return d.strftime('%d.%m.%Y')

def _fmt_date_range(d_start, d_end):
    if pd.isna(d_start) or d_start == d_end:
        return _fmt_date(d_end)
    return f"{_fmt_date(d_start)}–{_fmt_date(d_end)}"

def clean_comment(raw):
    # Комментарии из БД иногда содержат собственные переносы строк -
    # схлопываем их в пробелы, чтобы не путать со структурными отступами
    # при построении текста острова (заголовок / строки-итерации).
    if pd.isna(raw) or str(raw) == 'Нет':
        return ""
    return " ".join(str(raw).split())

def _render_bureaucracy_progress():
    df_raw = get_analytics_snapshot()
    df = df_raw[(df_raw['track_type'] == 'bureaucracy') &
                (df_raw['is_agreement_project'] == True)].copy()

    if df.empty:
        st.info("Нет данных о пройденных этапах бюрократии.")
        return

    # Защита от рассогласованных данных: факт. дата учитывается только для
    # реально завершённых итераций (статус "Выполнено"). Для прочих статусов
    # actual_end/actual_start игнорируются, даже если в БД что-то проставлено.
    done_mask = df['status'] == 'Выполнено'
    df.loc[~done_mask, ['actual_start', 'actual_end']] = pd.NaT

    # Проект считается завершённым только когда "Документ подписан" реально выполнен
    completed_ids = df[(df['stage_order'] == 8) & done_mask]['project_id'].unique()

    show_done = st.checkbox("Показать завершенные проекты", value=False)
    if not show_done:
        df = df[~df['project_id'].isin(completed_ids)]

    # Для каждого проекта оставляем: все завершённые итерации + (если проект ещё
    # не завершён) один "текущий активный" этап без факт. даты - тот, что имеет
    # наибольший stage_order среди строк без actual_end (может сосуществовать с уже
    # завершёнными итерациями того же названия этапа - см. например project_id=12,
    # где 8 итераций "Согласование документа" выполнены, а последняя ещё "Ожидание")
    finished = df[df['actual_end'].notna()].copy()
    finished['is_open'] = False

    open_rows = df[df['actual_end'].isna() & ~df['project_id'].isin(completed_ids)]
    open_last_idx = (open_rows.sort_values('stage_order')
                               .groupby('project_id')['stage_order']
                               .idxmax())
    current_open = df.loc[open_last_idx].copy()
    current_open['is_open'] = True

    df = pd.concat([finished, current_open], ignore_index=True)
    if df.empty:
        st.info("Нет данных о пройденных этапах бюрократии.")
        return

    # "Начало" для сортировки/отображения: у завершённых итераций - actual_start
    # (или actual_end, если начало не проставлено), у текущей активной - actual_start/planned_start
    df['eff_start'] = df['actual_start']
    df.loc[df['eff_start'].isna() & ~df['is_open'], 'eff_start'] = df['actual_end']
    df.loc[df['is_open'] & df['eff_start'].isna(), 'eff_start'] = df['planned_start']
    df['sort_date'] = df['actual_end'].fillna(df['eff_start'])

    # Островная группировка: подряд идущие строки одного поставщика с одним
    # и тем же названием этапа схлопываются в один "остров". Повторное появление
    # этапа после другого этапа (например, второй заход "Переговоров" после
    # "Согласования документа") сознательно даёт отдельный остров - в реальности
    # это разные по смыслу заходы, разнесённые другим этапом процесса.
    df = df.sort_values(['is_mandatory', 'supplier_name', 'sort_date', 'stage_order'])
    df['new_grp'] = (df['stage_name'] != df['stage_name'].shift()) | (df['supplier_name'] != df['supplier_name'].shift())
    df['grp_id'] = df['new_grp'].cumsum()

    islands = []
    for grp_id, isl in df.groupby('grp_id', sort=False):
        isl = isl.sort_values('sort_date')
        first = isl.iloc[0]
        is_milestone = len(isl) == 1 and not first['is_open'] and first['actual_start'] == first['actual_end']

        if is_milestone or (len(isl) == 1 and first['is_open']):
            row = isl.iloc[0]
            comment = clean_comment(row['comments'])
            if row['is_open']:
                date_txt = f"{_fmt_date(row['eff_start'])} – по настоящее время" if pd.notna(row['eff_start']) else "по настоящее время"
            else:
                date_txt = _fmt_date(row['actual_end'])
            header_line = f"{date_txt}: {row['stage_name']} - {comment}"
            item_lines = []
        else:
            d_min = isl['eff_start'].min()
            d_max_done = isl.loc[~isl['is_open'], 'actual_end']
            d_max = d_max_done.max() if not d_max_done.empty else isl['eff_start'].max()
            has_open = isl['is_open'].any()
            header_end = "по настоящее время" if has_open else _fmt_date(d_max)
            header_line = f"{_fmt_date(d_min)}–{header_end} - {first['stage_name']}:"

            item_lines = []
            for _, row in isl.iterrows():
                comment = clean_comment(row['comments'])
                if row['is_open']:
                    it_date = f"{_fmt_date(row['eff_start'])} – по настоящее время" if pd.notna(row['eff_start']) else "по настоящее время"
                else:
                    it_date = _fmt_date_range(row['actual_start'], row['actual_end'])
                item_lines.append(f"{it_date} - {comment}")

        text = "\n".join([header_line] + [f"    {l}" for l in item_lines])

        islands.append({
            'supplier': first['supplier_name'],
            'is_mand': first['is_mandatory'],
            'sort_date': first['sort_date'],
            'Этап': text,
            'header_line': header_line,
            'item_lines': item_lines,
        })

    grouped = pd.DataFrame(islands).sort_values(['is_mand', 'supplier', 'sort_date'])

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
                # 35px за строку текста (island-текст может занимать несколько строк) + запас
                lines_per_row = disp['Этап'].str.count('\n') + 1
                calculated_h = int((lines_per_row * 35).sum()) + 40
                final_h = min(600, max(100, calculated_h))

                st.dataframe(disp[['Поставщик', 'Этап']],
                             width="stretch", hide_index=True, height=final_h)
            else:
                st.write("Данные отсутствуют")

    st.markdown("<br>", unsafe_allow_html=True)
    col_tbl, col_txt = st.columns(2)
    with col_tbl:
        if st.button("🚀 Сгенерировать (таблица)", type="primary"):
            docx = _export_bureaucracy_islands_docx_table(grouped)
            st.download_button("📥 Скачать файл", docx, f"progress_report_{datetime.now().strftime('%d_%m')}.docx")
    with col_txt:
        if st.button("📝 Сгенерировать (текст)"):
            docx = _export_bureaucracy_islands_docx_text(grouped)
            st.download_button("📥 Скачать файл", docx, f"progress_report_text_{datetime.now().strftime('%d_%m')}.docx")

def _docx_base():
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(12)
    for section in doc.sections:
        section.top_margin, section.bottom_margin = Cm(2), Cm(2)
        section.left_margin, section.right_margin = Cm(2), Cm(1.5)

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p_title.add_run(f"Сводный отчёт о ходе выполнения на {datetime.now().strftime('%d.%m.%Y')}")
    run.bold = True
    return doc

_GROUPS = [(True, "⭐ Поставщики ОНПД"), (False, "📂 Прочие поставщики")]

def _export_bureaucracy_islands_docx_table(df):
    doc = _docx_base()

    for mand_status, title in _GROUPS:
        sub = df[df['is_mand'] == mand_status]
        if sub.empty:
            continue

        h = doc.add_paragraph()
        h_run = h.add_run(title)
        h_run.bold = True
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(6)

        table = doc.add_table(rows=1, cols=3)
        table.style = 'Table Grid'
        hdr = table.rows[0].cells
        hdr[0].text, hdr[1].text, hdr[2].text = '№ п/п', 'Поставщик', 'Этап'

        for i, (name, group) in enumerate(sub.groupby('supplier', sort=False)):
            rows_in_group = list(group.iterrows())
            first_row_idx = None
            for j, (_, row) in enumerate(rows_in_group):
                cells = table.add_row().cells
                if j == 0:
                    cells[0].text = str(i + 1)
                    cells[1].text = name
                    first_row_idx = len(table.rows) - 1
                cells[2].text = row['Этап']
            if len(rows_in_group) > 1:
                last_row_idx = len(table.rows) - 1
                table.cell(first_row_idx, 0).merge(table.cell(last_row_idx, 0))
                table.cell(first_row_idx, 1).merge(table.cell(last_row_idx, 1))

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def _export_bureaucracy_islands_docx_text(df):
    doc = _docx_base()

    for mand_status, title in _GROUPS:
        sub = df[df['is_mand'] == mand_status]
        if sub.empty:
            continue

        h = doc.add_paragraph()
        h_run = h.add_run(title)
        h_run.bold = True
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(6)

        for name, group in sub.groupby('supplier', sort=False):
            p_sup = doc.add_paragraph()
            p_sup_run = p_sup.add_run(name)
            p_sup_run.bold = True
            p_sup.paragraph_format.space_before = Pt(6)
            p_sup.paragraph_format.space_after = Pt(2)

            for _, row in group.iterrows():
                p = doc.add_paragraph(style='List Bullet')
                p.add_run(row['header_line'])
                p.paragraph_format.space_after = Pt(0)
                for line in row['item_lines']:
                    p2 = doc.add_paragraph(style='List Bullet 2')
                    p2.add_run(line)
                    p2.paragraph_format.space_after = Pt(0)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

# ==========================================
# 3. ХОД ТЕХНИЧЕСКОЙ РАБОТЫ (ТЕХНОЛОГИЯ)
# ==========================================
# Финальные шаги воронки TECH_FUNNEL_CODES (progress_math.py) - трек считается
# пройденным для конкретного набора, когда обе публикации (метаданные и данные) выполнены.
_TECH_FINAL_CODES = ('META_PUB', 'DATA_PUB')

def _render_technology_progress():
    df_raw = get_analytics_snapshot()
    df = df_raw[df_raw['track_type'] == 'tech'].copy()

    if df.empty:
        st.info("Нет данных о пройденных этапах технической работы.")
        return

    # Защита от рассогласованных данных: факт. дата учитывается только для
    # реально завершённых итераций (статус "Выполнено") - см. аналогичный
    # приём в _render_bureaucracy_progress.
    done_mask = df['status'] == 'Выполнено'
    df.loc[~done_mask, ['actual_start', 'actual_end']] = pd.NaT

    # Остров в технологии привязан к паре (поставщик, набор сведений), т.к. одна
    # итерация этапа может через affected_item_ids затрагивать сразу несколько
    # наборов - в снапшоте это уже развёрнуто в отдельные строки с разным info_name.
    df['track_key'] = df['supplier_name'] + " | " + df['info_name']

    # "Набор считается завершённым", когда по нему выполнены оба финальных шага
    # воронки (публикация метаданных и данных).
    final_done = (df['stage_code'].isin(_TECH_FINAL_CODES) & done_mask)
    done_counts = df[final_done].groupby('track_key')['stage_code'].nunique()
    completed_keys = done_counts[done_counts >= len(_TECH_FINAL_CODES)].index

    show_done = st.checkbox("Показать завершенные наборы", value=False, key="tech_show_done")
    if not show_done:
        df = df[~df['track_key'].isin(completed_keys)]

    # Для каждого набора оставляем: все завершённые итерации + (если набор ещё
    # не завершён) один "текущий активный" этап без факт. даты - тот, что имеет
    # наибольший stage_order среди строк без actual_end.
    finished = df[df['actual_end'].notna()].copy()
    finished['is_open'] = False

    open_rows = df[df['actual_end'].isna() & ~df['track_key'].isin(completed_keys)]
    open_last_idx = (open_rows.sort_values('stage_order')
                               .groupby('track_key')['stage_order']
                               .idxmax())
    current_open = df.loc[open_last_idx].copy()
    current_open['is_open'] = True

    df = pd.concat([finished, current_open], ignore_index=True)
    if df.empty:
        st.info("Нет данных о пройденных этапах технической работы.")
        return

    # "Начало" для сортировки/отображения: у завершённых итераций - actual_start
    # (или actual_end, если начало не проставлено), у текущей активной - actual_start/planned_start
    df['eff_start'] = df['actual_start']
    df.loc[df['eff_start'].isna() & ~df['is_open'], 'eff_start'] = df['actual_end']
    df.loc[df['is_open'] & df['eff_start'].isna(), 'eff_start'] = df['planned_start']
    df['sort_date'] = df['actual_end'].fillna(df['eff_start'])

    # Островная группировка: подряд идущие строки одного набора с одним и тем же
    # названием этапа схлопываются в один "остров" - см. пояснение в
    # _render_bureaucracy_progress про повторное появление этапа как отдельный остров.
    df = df.sort_values(['is_mandatory', 'supplier_name', 'info_name', 'sort_date', 'stage_order'])
    df['new_grp'] = (df['stage_name'] != df['stage_name'].shift()) | (df['track_key'] != df['track_key'].shift())
    df['grp_id'] = df['new_grp'].cumsum()

    islands = []
    for grp_id, isl in df.groupby('grp_id', sort=False):
        isl = isl.sort_values('sort_date')
        first = isl.iloc[0]
        is_milestone = len(isl) == 1 and not first['is_open'] and first['actual_start'] == first['actual_end']

        if is_milestone or (len(isl) == 1 and first['is_open']):
            row = isl.iloc[0]
            comment = clean_comment(row['comments'])
            if row['is_open']:
                date_txt = f"{_fmt_date(row['eff_start'])} – по настоящее время" if pd.notna(row['eff_start']) else "по настоящее время"
            else:
                date_txt = _fmt_date(row['actual_end'])
            header_line = f"{date_txt}: {row['stage_name']} - {comment}"
            item_lines = []
        else:
            d_min = isl['eff_start'].min()
            d_max_done = isl.loc[~isl['is_open'], 'actual_end']
            d_max = d_max_done.max() if not d_max_done.empty else isl['eff_start'].max()
            has_open = isl['is_open'].any()
            header_end = "по настоящее время" if has_open else _fmt_date(d_max)
            header_line = f"{_fmt_date(d_min)}–{header_end} - {first['stage_name']}:"

            item_lines = []
            for _, row in isl.iterrows():
                comment = clean_comment(row['comments'])
                if row['is_open']:
                    it_date = f"{_fmt_date(row['eff_start'])} – по настоящее время" if pd.notna(row['eff_start']) else "по настоящее время"
                else:
                    it_date = _fmt_date_range(row['actual_start'], row['actual_end'])
                item_lines.append(f"{it_date} - {comment}")

        text = "\n".join([header_line] + [f"    {l}" for l in item_lines])

        islands.append({
            'supplier': first['supplier_name'],
            'info_name': first['info_name'],
            'is_mand': first['is_mandatory'],
            'sort_date': first['sort_date'],
            'Этап': text,
            'header_line': header_line,
            'item_lines': item_lines,
        })

    grouped = pd.DataFrame(islands).sort_values(['is_mand', 'supplier', 'info_name', 'sort_date'])

    for mand_status, title, exp_key, is_exp in [(True, "⭐ Поставщики ОНПД", "tech_exp_mand", True),
                                                (False, "📂 Прочие поставщики", "tech_exp_other", False)]:
        sub = grouped[grouped['is_mand'] == mand_status].copy()
        with st.expander(title, expanded=is_exp):
            if not sub.empty:
                disp = sub.copy()
                disp['Поставщик'] = disp['supplier']
                disp.loc[disp.duplicated('supplier'), 'Поставщик'] = ""
                disp['Набор'] = disp['info_name']

                lines_per_row = disp['Этап'].str.count('\n') + 1
                calculated_h = int((lines_per_row * 35).sum()) + 40
                final_h = min(600, max(100, calculated_h))

                st.dataframe(disp[['Поставщик', 'Набор', 'Этап']],
                             width="stretch", hide_index=True, height=final_h)
            else:
                st.write("Данные отсутствуют")

    st.markdown("<br>", unsafe_allow_html=True)
    col_tbl, col_txt = st.columns(2)
    with col_tbl:
        if st.button("🚀 Сгенерировать (таблица)", type="primary", key="tech_gen_table"):
            docx = _export_technology_islands_docx_table(grouped)
            st.download_button("📥 Скачать файл", docx, f"tech_progress_report_{datetime.now().strftime('%d_%m')}.docx", key="tech_dl_table")
    with col_txt:
        if st.button("📝 Сгенерировать (текст)", key="tech_gen_text"):
            docx = _export_technology_islands_docx_text(grouped)
            st.download_button("📥 Скачать файл", docx, f"tech_progress_report_text_{datetime.now().strftime('%d_%m')}.docx", key="tech_dl_text")

def _tech_docx_base():
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(12)
    for section in doc.sections:
        section.top_margin, section.bottom_margin = Cm(2), Cm(2)
        section.left_margin, section.right_margin = Cm(2), Cm(1.5)

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p_title.add_run(f"Отчёт о ходе технической работы на {datetime.now().strftime('%d.%m.%Y')}")
    run.bold = True
    return doc

def _export_technology_islands_docx_table(df):
    doc = _tech_docx_base()

    for mand_status, title in _GROUPS:
        sub = df[df['is_mand'] == mand_status]
        if sub.empty:
            continue

        h = doc.add_paragraph()
        h_run = h.add_run(title)
        h_run.bold = True
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(6)

        table = doc.add_table(rows=1, cols=4)
        table.style = 'Table Grid'
        hdr = table.rows[0].cells
        hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text = '№ п/п', 'Поставщик', 'Набор', 'Этап'

        for i, (name, group) in enumerate(sub.groupby('supplier', sort=False)):
            rows_in_group = list(group.iterrows())
            first_row_idx = None
            for j, (_, row) in enumerate(rows_in_group):
                cells = table.add_row().cells
                if j == 0:
                    cells[0].text = str(i + 1)
                    cells[1].text = name
                    first_row_idx = len(table.rows) - 1
                cells[2].text = row['info_name']
                cells[3].text = row['Этап']
            if len(rows_in_group) > 1:
                last_row_idx = len(table.rows) - 1
                table.cell(first_row_idx, 0).merge(table.cell(last_row_idx, 0))
                table.cell(first_row_idx, 1).merge(table.cell(last_row_idx, 1))

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def _export_technology_islands_docx_text(df):
    doc = _tech_docx_base()

    for mand_status, title in _GROUPS:
        sub = df[df['is_mand'] == mand_status]
        if sub.empty:
            continue

        h = doc.add_paragraph()
        h_run = h.add_run(title)
        h_run.bold = True
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(6)

        for name, group in sub.groupby('supplier', sort=False):
            p_sup = doc.add_paragraph()
            p_sup_run = p_sup.add_run(name)
            p_sup_run.bold = True
            p_sup.paragraph_format.space_before = Pt(6)
            p_sup.paragraph_format.space_after = Pt(2)

            for info_name, info_group in group.groupby('info_name', sort=False):
                p_info = doc.add_paragraph()
                p_info_run = p_info.add_run(info_name)
                p_info_run.italic = True
                p_info.paragraph_format.left_indent = Cm(0.5)
                p_info.paragraph_format.space_after = Pt(2)

                for _, row in info_group.iterrows():
                    p = doc.add_paragraph(style='List Bullet')
                    p.paragraph_format.left_indent = Cm(1)
                    p.add_run(row['header_line'])
                    p.paragraph_format.space_after = Pt(0)
                    for line in row['item_lines']:
                        p2 = doc.add_paragraph(style='List Bullet 2')
                        p2.paragraph_format.left_indent = Cm(1.5)
                        p2.add_run(line)
                        p2.paragraph_format.space_after = Pt(0)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

# ==========================================
# 4. РЕЕСТР СВЕДЕНИЙ
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
# 5. РЕЕСТР ПРОТОКОЛОВ СОВЕЩАНИЙ
# ==========================================

def _render_meeting_minutes_registry():
    """
    Отчёт 4: Реестр протоколов совещаний.
    Собирает все документы с этапов 'Протокол переговоров' всех проектов.
    """
    st.markdown("#### 🤝 Архив протоколов совещаний и переговоров")

    # 1. Получаем список поставщиков, у которых есть хоть один выполненный протокол
    suppliers_query = """
        SELECT DISTINCT s.supplier_id, s.supplier_name
        FROM project_stages ps
        JOIN projects p ON ps.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE (stg.stage_name = 'Протокол переговоров' OR stg.stage_code = 'MEETING_MINUTES')
          AND ms.micro_status_name = 'Выполнено'
        ORDER BY s.supplier_name
    """
    sups = query_db(suppliers_query)

    if sups.empty:
        st.info("📭 Протоколы совещаний в базе данных не найдены.")
        return

    # 2. Получаем все документы, привязанные к этим этапам
    docs_query = """
        SELECT 
            sd.doc_name, 
            sd.doc_url, 
            p.project_name, 
            p.supplier_id,
            ps.actual_end as meeting_date
        FROM stage_documents sd
        JOIN project_stages ps ON sd.project_stage_id = ps.stage_progress_id
        JOIN projects p ON ps.project_id = p.project_id
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE (stg.stage_name = 'Протокол переговоров' OR stg.stage_code = 'MEETING_MINUTES')
          AND ms.micro_status_name = 'Выполнено'
        ORDER BY ps.actual_end DESC
    """
    all_docs = query_db(docs_query)

    st.write(f"Найдено протоколов у **{len(sups)}** поставщиков")

    # 3. Отрисовка через экспандеры
    for _, sup in sups.iterrows():
        # Считаем количество протоколов для заголовка
        sup_docs = all_docs[all_docs['supplier_id'] == sup['supplier_id']]
        doc_count = len(sup_docs)
        
        with st.expander(f"🏢 {sup['supplier_name']} (Протоколов: {doc_count})"):
            if sup_docs.empty:
                st.caption("Записи об этапах есть, но файлы не прикреплены.")
            else:
                for _, doc in sup_docs.iterrows():
                    col_date, col_btn = st.columns([0.2, 0.8])
                    with col_date:
                        st.write(f"📅 **{doc['meeting_date'].strftime('%d.%m.%Y')}**")
                    with col_btn:
                        # На кнопке пишем проект и название файла
                        label = f"{doc['project_name']} — {doc['doc_name']}"
                        st.link_button(label, doc['doc_url'], width='stretch')

# ==========================================
# 6. ПРОВОДНИК ОПРОСНИКОВ
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

# ==========================================
# 8. РЕЕСТР УЧЁТНЫХ ЗАПИСЕЙ ПОЛЬЗОВАТЕЛЕЙ
# ==========================================
OPERATOR_NAME = 'Государственное предприятие "Белгеодезия"'

def _render_accounts_registry():
    """
    Отчёт 7: Реестр учётных записей пользователей.
    X (общее число) вводится вручную в Админ-панели (app_settings.total_registered_accounts) —
    уже включает учётную запись(и) Оператора (ГП "Белгеодезия"), т.к. вводится по данным Keycloak.
    Y (физ. лица) и А (уникальные юр. лица) считаются из reg_requests (status = 'Завершена').
    Оператор в реестре заявок не фигурирует, поэтому добавляется к А (+1) и к списку
    поставщиков (первой строкой) вручную — он не участвует в Z, т.к. Z = X - Y и X уже его учитывает.
    """
    st.markdown("#### 👤 Реестр учётных записей пользователей")

    total_accounts = int(load_settings().get("total_registered_accounts", 0))

    df = query_db("""
        SELECT applicant_type, applicant_name, org_type
        FROM reg_requests
        WHERE status = 'Завершена'
        ORDER BY applicant_name
    """)

    phys_df = df[df['applicant_type'] == 'Физическое лицо']
    org_df = df[df['applicant_type'] == 'Юридическое лицо']

    y_individuals = len(phys_df)
    z_org_accounts = total_accounts - y_individuals

    # Группировка юр. лиц по имени — приоритет "Поставщик": если хотя бы одна
    # завершённая заявка организации имеет org_type = 'Поставщик', она попадает
    # в список поставщиков, иначе — в список пользователей портала.
    org_types_by_name = org_df.groupby('applicant_name')['org_type'].apply(set)
    supplier_names = sorted(n for n, types in org_types_by_name.items() if 'Поставщик' in types)
    user_org_names = sorted(n for n, types in org_types_by_name.items() if 'Поставщик' not in types)
    supplier_names = [OPERATOR_NAME] + supplier_names
    a_legal_entities = len(supplier_names) + len(user_org_names)

    individual_names = sorted(phys_df['applicant_name'].tolist())

    today_str = datetime.now().strftime('%d.%m.%Y')

    if total_accounts <= 0:
        st.warning("⚠️ Общее число учётных записей (X) не задано. Укажите его в Админ-панели → ⚙️ Настройки.")

    # --- Текстовое представление отчёта ---
    lines = [
        f"По состоянию на {today_str} на Национальном геопортале заведено {total_accounts} учётных записей, в частности:",
        "",
        f"{z_org_accounts} учётных записей для {a_legal_entities} юридических лиц:",
        "     - юридические лица - Поставщики пространственных данных:",
    ]
    lines += [f"          {name}" for name in supplier_names]
    lines.append("     - юридические лица - пользователи Национального геопортала:")
    lines += [f"          {name}" for name in user_org_names] if user_org_names else ["          (нет данных)"]
    lines.append("")
    lines.append(f"{y_individuals} учётных записей пользователей - физических лиц:")
    lines += [f"     {name}" for name in individual_names] if individual_names else ["     (нет данных)"]

    report_text = "\n".join(lines)

    st.text_area("Текст отчёта", value=report_text, height=450, key="accounts_registry_text")

    docx_buffer = _build_accounts_registry_docx(today_str, total_accounts, z_org_accounts, a_legal_entities,
                                                 supplier_names, user_org_names, y_individuals, individual_names)

    st.download_button(
        "📥 Скачать реестр (Word)",
        docx_buffer.getvalue(),
        f"accounts_registry_{datetime.now().strftime('%d_%m_%Y')}.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

def _build_accounts_registry_docx(today_str, total_accounts, z_org_accounts, a_legal_entities,
                                   supplier_names, user_org_names, y_individuals, individual_names):
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(12)

    doc.add_paragraph(
        f"По состоянию на {today_str} на Национальном геопортале заведено {total_accounts} "
        f"учётных записей, в частности:"
    )
    doc.add_paragraph(f"{z_org_accounts} учётных записей для {a_legal_entities} юридических лиц:")
    doc.add_paragraph("- юридические лица - Поставщики пространственных данных:")
    for name in supplier_names:
        doc.add_paragraph(name, style='List Bullet')
    doc.add_paragraph("- юридические лица - пользователи Национального геопортала:")
    if user_org_names:
        for name in user_org_names:
            doc.add_paragraph(name, style='List Bullet')
    else:
        doc.add_paragraph("(нет данных)", style='List Bullet')
    doc.add_paragraph(f"{y_individuals} учётных записей пользователей - физических лиц:")
    if individual_names:
        for name in individual_names:
            doc.add_paragraph(name, style='List Bullet')
    else:
        doc.add_paragraph("(нет данных)", style='List Bullet')

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# ==========================================
# 9. СВОДНЫЙ ОТЧЁТ О ПОСТАВЩИКАХ НАЦИОНАЛЬНОГО ГЕОПОРТАЛА
# ==========================================
# Форма отчёта: строка = вид сведений (а при разбиении - его часть), а не проект.
#
# "Соглашение" - у поставщика есть подписанный документ project_documents
# с doc_kind = 'Соглашение' (по любому его проекту).
# "Протокол"   - вид сведений (или его часть) покрыт подписанным документом
# с doc_kind = 'Протокол'. Документ с ПУСТЫМ охватом покрывает весь проект -
# это обычный случай; охват заполняется только когда виды сведений одного набора
# разнесены по разным протоколам (напр. УИВП Минобороны).
#
# "Данные/Метаданные получены" = этапы DATA_WAIT/META_WAIT ("Размещение наборов" /
# "Размещение метаданных Поставщиком", см. комментарий в technology_tab.py) выполнены -
# т.е. поставщик передал материал. "...опубликованы" = финальные DATA_PUB/META_PUB.
# Эти флаги берутся ПО НАБОРУ (через affected_item_ids), а не по проекту целиком.
_SUMMARY_GREEN = RGBColor(0x27, 0xAE, 0x60)
_SUMMARY_RED = RGBColor(0xE7, 0x4C, 0x3C)

_SUMMARY_HEADERS = [
    '№ п/п', 'Поставщик', 'Соглашение', 'Набор', 'Обязательный', 'Вид сведений',
    'Протокол', 'Данные получены', 'Данные опубликованы',
    'Метаданные получены', 'Метаданные опубликованы', 'Примечание',
]


def _fetch_summary_rows():
    """Собирает плоскую таблицу отчёта: одна строка на вид сведений (или его часть)."""

    # Состав всех проектов: набор -> вид сведений, с разворотом на части.
    # Разворот идёт через project_item_part_details, а НЕ через справочник частей:
    # части есть у вида сведений всегда, но разбитым он считается только у того
    # поставщика, который завёл параметры передачи по частям. У остальных
    # остаётся одна строка с part_id = NULL, как было до появления частей.
    items_df = query_db("""
        SELECT s.supplier_id, s.supplier_name, s.is_mandatory AS supplier_mandatory,
               p.project_id, p.project_name, p.notes AS project_notes,
               pi.item_id, d.dataset_name, d.is_mandatory AS dataset_mandatory,
               i.info_name,
               pd.part_id, itp.part_name,
               -- Условия передачи: часть -> проект -> справочник вида сведений
               COALESCE(pd.provision_right, pi.provision_right)        AS provision_right,
               COALESCE(pd.format, pi.format, i.format)                AS format,
               COALESCE(pd.update_period, pi.update_period, i."update") AS update_period,
               COALESCE(pd.meta_method, pi.meta_method)                AS meta_method,
               COALESCE(pd.data_method, pi.data_method)                AS data_method
        FROM project_items pi
        JOIN projects p ON pi.project_id = p.project_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        LEFT JOIN project_item_part_details pd ON pd.item_id = pi.item_id
        LEFT JOIN info_type_parts itp ON itp.part_id = pd.part_id
        ORDER BY s.is_mandatory DESC, s.supplier_name, d.dataset_name,
                 i.info_name, itp.sort_order NULLS LAST, itp.part_id
    """)

    # Поставщики с подписанным соглашением
    agreement_ids = set(query_db("""
        SELECT DISTINCT p.supplier_id
        FROM project_documents pd
        JOIN projects p ON pd.project_id = p.project_id
        WHERE pd.doc_kind = 'Соглашение' AND pd.is_signed
    """)['supplier_id'].tolist())

    # Подписанные протоколы: проекты, где протокол покрывает ВЕСЬ проект (пустой охват)
    proto_whole_projects = set(query_db("""
        SELECT DISTINCT pd.project_id
        FROM project_documents pd
        WHERE pd.doc_kind = 'Протокол' AND pd.is_signed
          AND NOT EXISTS (SELECT 1 FROM project_document_items pdi WHERE pdi.doc_id = pd.doc_id)
    """)['project_id'].tolist())

    # Подписанные протоколы с явным охватом: пары (item_id, part_id)
    proto_cov = query_db("""
        SELECT DISTINCT pdi.item_id, pdi.part_id
        FROM project_document_items pdi
        JOIN project_documents pd ON pdi.doc_id = pd.doc_id
        WHERE pd.doc_kind = 'Протокол' AND pd.is_signed
    """)
    # Охват на весь вид сведений (part_id IS NULL) покрывает и все его части
    proto_items_whole = set(proto_cov[proto_cov['part_id'].isna()]['item_id'].tolist())
    proto_parts = {(int(r['item_id']), int(r['part_id']))
                   for _, r in proto_cov[proto_cov['part_id'].notna()].iterrows()}

    # Технологические флаги ПО НАБОРУ: разворачиваем affected_item_ids
    # (массив объектов {item_id, part_id}).
    # DISTINCT обязателен - один этап на N наборов даёт N строк.
    tech_df = query_db("""
        SELECT DISTINCT (aff ->> 'item_id')::int AS item_id,
               (aff ->> 'part_id')::int AS part_id,
               stg.stage_code
        FROM project_stages ps
        CROSS JOIN LATERAL jsonb_array_elements(ps.affected_item_ids) AS aff
        JOIN stages stg ON ps.stage_id = stg.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        WHERE stg.stage_code IN ('DATA_WAIT', 'DATA_PUB', 'META_WAIT', 'META_PUB')
          AND ms.micro_status_name = 'Выполнено'
    """)
    # Этап с part_id = NULL закрывает вид сведений целиком (все его части),
    # этап с конкретной частью - только её
    tech_whole = set()
    tech_by_part = set()
    if not tech_df.empty:
        for _, t in tech_df.iterrows():
            key_item = (int(t['item_id']), t['stage_code'])
            if pd.isna(t['part_id']):
                tech_whole.add(key_item)
            else:
                tech_by_part.add((int(t['item_id']), int(t['part_id']), t['stage_code']))

    def tech_done(item_id, part_id, code):
        if (item_id, code) in tech_whole:
            return True
        return part_id is not None and (item_id, part_id, code) in tech_by_part

    # Примечание: projects.notes как основа + свежие комментарии незакрытых этапов
    notes_df = query_db("""
        SELECT ps.project_id, ps.comments,
               COALESCE(ps.actual_start, ps.planned_start) AS ref_date
        FROM project_stages ps
        WHERE ps.micro_status <> 4
          AND ps.comments IS NOT NULL AND btrim(ps.comments) <> ''
        ORDER BY ps.project_id, COALESCE(ps.actual_start, ps.planned_start) DESC NULLS LAST
    """)

    notes_by_project = {}
    for pid, group in notes_df.groupby('project_id'):
        lines = []
        for _, r in group.iterrows():
            prefix = f"{r['ref_date'].strftime('%d.%m.%Y')}: " if pd.notna(r['ref_date']) else ""
            lines.append(f"{prefix}{r['comments'].strip()}")
        notes_by_project[pid] = lines

    rows = []
    for _, r in items_df.iterrows():
        item_id = int(r['item_id'])
        pid = int(r['project_id'])
        has_part = pd.notna(r['part_id'])
        part_id = int(r['part_id']) if has_part else None

        if has_part:
            protocol_ok = (pid in proto_whole_projects
                           or item_id in proto_items_whole
                           or (item_id, part_id) in proto_parts)
            info_label = f"{r['info_name']} — {r['part_name']}"
        else:
            protocol_ok = (pid in proto_whole_projects or item_id in proto_items_whole)
            info_label = r['info_name']

        note_parts = []
        if pd.notna(r['project_notes']) and str(r['project_notes']).strip():
            note_parts.append(str(r['project_notes']).strip())
        note_parts.extend(notes_by_project.get(pid, []))

        rows.append({
            'supplier_id': int(r['supplier_id']),
            'supplier_name': r['supplier_name'],
            'agreement_signed': int(r['supplier_id']) in agreement_ids,
            'dataset_name': r['dataset_name'],
            'dataset_mandatory': bool(r['dataset_mandatory']),
            'info_label': info_label,
            'protocol_signed': protocol_ok,
            'data_received': tech_done(item_id, part_id, 'DATA_WAIT'),
            'data_published': tech_done(item_id, part_id, 'DATA_PUB'),
            'meta_received': tech_done(item_id, part_id, 'META_WAIT'),
            'meta_published': tech_done(item_id, part_id, 'META_PUB'),
            'note': "\n".join(note_parts),
        })

    return pd.DataFrame(rows)


def _render_supplier_projects_summary():
    st.markdown("#### 📊 Сводный отчёт о Поставщиках Национального геопортала")

    df = _fetch_summary_rows()
    if df.empty:
        st.info("Нет данных: ни в одном проекте не заведён состав наборов.")
        return

    def yn(v):
        return "Да" if v else "Нет"

    disp = pd.DataFrame()
    disp['№ п/п'] = range(1, len(df) + 1)
    disp['Поставщик'] = df['supplier_name']
    disp['Соглашение'] = df['agreement_signed'].apply(yn)
    disp['Набор'] = df['dataset_name']
    disp['Обязательный'] = df['dataset_mandatory'].apply(yn)
    disp['Вид сведений'] = df['info_label']
    disp['Протокол'] = df['protocol_signed'].apply(yn)
    disp['Данные получены'] = df['data_received'].apply(yn)
    disp['Данные опубликованы'] = df['data_published'].apply(yn)
    disp['Метаданные получены'] = df['meta_received'].apply(yn)
    disp['Метаданные опубликованы'] = df['meta_published'].apply(yn)
    disp['Примечание'] = df['note']

    # Повторяющиеся значения гасим - в форме отчёта они объединены в одну ячейку
    dup_sup = df.duplicated('supplier_id')
    disp.loc[dup_sup, ['Поставщик', 'Соглашение']] = ""
    dup_ds = df.duplicated(['supplier_id', 'dataset_name'])
    disp.loc[dup_ds, ['Набор', 'Обязательный']] = ""

    calc_h = (len(disp) * 35) + 45
    st.dataframe(disp, width="stretch", hide_index=True, height=min(700, max(150, calc_h)))

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚀 Сгенерировать (Word)", type="primary", key="summary_gen_docx"):
        docx = _export_supplier_projects_summary_docx(df)
        st.download_button("📥 Скачать файл", docx,
                           f"suppliers_summary_{datetime.now().strftime('%d_%m_%Y')}.docx",
                           key="summary_dl_docx")


def _write_summary_flag_cell(cell, value):
    """Пишет в ячейку зелёное «Да» / красное «Нет» (или '—', если неприменимо)."""
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if value is None:
        p.add_run("—")
        return
    run = p.add_run("Да" if value else "Нет")
    run.font.color.rgb = _SUMMARY_GREEN if value else _SUMMARY_RED


def _merge_column_runs(table, col_idx, start_row, keys):
    """Объединяет вертикально соседние ячейки колонки с одинаковым ключом.

    keys - список ключей по строкам данных (той же длины, что и строки таблицы
    начиная со start_row). Возвращать ничего не нужно - таблица меняется на месте.
    """
    run_start = 0
    for i in range(1, len(keys) + 1):
        if i == len(keys) or keys[i] != keys[run_start]:
            if i - run_start > 1:
                table.cell(start_row + run_start, col_idx).merge(
                    table.cell(start_row + i - 1, col_idx))
            run_start = i


def _export_supplier_projects_summary_docx(df):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(9)

    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    section.top_margin = section.bottom_margin = Cm(1.5)
    section.left_margin = section.right_margin = Cm(1.5)

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p_title.add_run("Сводный отчет о Поставщиках Национального геопортала")
    run.bold = True

    table = doc.add_table(rows=1, cols=len(_SUMMARY_HEADERS))
    table.style = 'Table Grid'
    for i, h in enumerate(_SUMMARY_HEADERS):
        cell = table.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        hrun = p.add_run(h)
        hrun.bold = True

    for n, (_, row) in enumerate(df.iterrows(), 1):
        cells = table.add_row().cells
        cells[0].text = str(n)
        cells[1].text = row['supplier_name']
        _write_summary_flag_cell(cells[2], row['agreement_signed'])
        cells[3].text = row['dataset_name']
        _write_summary_flag_cell(cells[4], row['dataset_mandatory'])
        cells[5].text = row['info_label']
        _write_summary_flag_cell(cells[6], row['protocol_signed'])
        _write_summary_flag_cell(cells[7], row['data_received'])
        _write_summary_flag_cell(cells[8], row['data_published'])
        _write_summary_flag_cell(cells[9], row['meta_received'])
        _write_summary_flag_cell(cells[10], row['meta_published'])
        cells[11].text = row['note'] or ""

    # Объединение ячеек: поставщик/соглашение - по поставщику,
    # набор/обязательный - по набору внутри поставщика (как в форме отчёта)
    sup_keys = df['supplier_id'].tolist()
    ds_keys = list(zip(df['supplier_id'], df['dataset_name']))
    for col in (1, 2):
        _merge_column_runs(table, col, 1, sup_keys)
    for col in (3, 4):
        _merge_column_runs(table, col, 1, ds_keys)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
