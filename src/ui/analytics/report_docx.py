import streamlit as st
import pandas as pd
import io
import json
from datetime import datetime, date, timedelta
from sqlalchemy import text
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from config.cache import query_db, clear_cache

MONTHS_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
    7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}

# 🟢 Новая структура с принудительным порядком (ключи с префиксами)
DEFAULT_SECTIONS = {
    "6.1": {
        "title": "6.1. Отчёт о работах по ведению (эксплуатации) Национального геопортала.",
        "blocks": {
            "01_611_header": {
                "title": "Заголовок 6.1.1 (Администрирование)",
                "active": True,
                "content": "6.1.1. Администрирование Национального геопортала, в том числе:\nприем, рассмотрение заявок на регистрацию и регистрация пользователей на Национальном геопортале:"
            },
            "02_reg_users": {
                "title": "Блок: Регистрация (пользователи)",
                "active": True,
                "content": ""
            },
            "03_cabinets": {
                "title": "Блок: Электронные кабинеты",
                "active": True,
                "content": ""
            },
            "04_total_stats": {
                "title": "Блок: Статистика на конец периода",
                "active": True,
                "content": ""
            },
            "05_provision_nipd": { 
                "title": "Блок: Предоставление НИПД (заявки)", 
                "active": True, 
                "content": "прием, рассмотрение заявок на предоставление в пользование наборов пространственных данных, включенных в НИПД:" 
            }
        }
    },
    "6.3": {
        "title": "6.3. Отчёт о работах по анализу функционирования НИПД.",
        "blocks": {
            "01_agreements": {
                "title": "Блок: Заключение соглашений",
                "active": True,
                "content": ""
            }
        }
    }
}

def pluralize(n, forms):
    """Склонение существительных: [заявка, заявки, заявок]"""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11: return forms[0]
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20): return forms[1]
    else: return forms[2]

def pluralize_verb_fem(n, forms):
    """Склонение глаголов (была/были, выполнена/выполнены)"""
    n = abs(int(n))
    return forms[0] if (n % 10 == 1 and n % 100 != 11) else forms[1]

def pluralize_outcome(n, variant):
    """Склонение категорий исходов: выполнена/выполнены и т.д."""
    n = abs(int(n))
    forms = {
        "done": ["выполнена", "выполнены"],
        "op": ["отклонена Оператором", "отклонены Оператором"],
        "sup": ["отказана Поставщиком", "отказаны Поставщиками"]
    }
    return forms[variant][0] if (n % 10 == 1 and n % 100 != 11) else forms[variant][1]

def get_gkf_material_names(material_ids):
    """Превращает [1, 2] в 'Аэрофотоснимки, Ортофотопланы'"""
    if not material_ids: return "не указаны"
    # Принудительно приводим к списку целых чисел, если пришел JSON
    if isinstance(material_ids, str):
        import json
        try: ids = json.loads(material_ids)
        except: return "ошибка формата"
    else: ids = material_ids
    
    if not ids: return "не указаны"
    
    # Запрашиваем названия материалов
    placeholders = ', '.join([':id' + str(i) for i in range(len(ids))])
    params = {f'id{i}': int(v) for i, v in enumerate(ids)}
    res = query_db(f"SELECT material_name FROM ref_gkf_materials WHERE material_id IN ({placeholders})", params)
    
    return ", ".join(res['material_name'].tolist()) if not res.empty else "не найдены"

def get_report_period_bounds(report_month_date):
    prev = query_db("""
        SELECT fixed_at FROM reports_monthly 
        WHERE report_month < :d AND fixed_at IS NOT NULL 
        ORDER BY report_month DESC LIMIT 1
    """, {"d": report_month_date})
    start_time = prev.iloc[0]['fixed_at'] if not prev.empty else datetime.combine(report_month_date, datetime.min.time())
    return start_time, datetime.now()

def fetch_registration_stats(start_t, end_t):
    new_users = query_db("""
        SELECT r.applicant_type, r.applicant_name, r.org_type,
               (SELECT COUNT(*) FROM reg_request_users WHERE req_id = r.req_id) as u_count
        FROM reg_requests r
        WHERE r.processed_at BETWEEN :s AND :e AND r.status = 'Завершена'
    """, {"s": start_t, "e": end_t})
    total_stats = query_db("""
        SELECT 
            COUNT(*) FILTER (WHERE applicant_type = 'Физическое лицо') as phys,
            COUNT(*) FILTER (WHERE applicant_type = 'Юридическое лицо') as orgs
        FROM reg_requests WHERE processed_at <= :e AND status = 'Завершена'
    """, {"e": end_t}).iloc[0]
    return new_users, total_stats

def generate_docx_file(report_date, sections_data, month_name):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(14)
    
    for section in doc.sections:
        section.top_margin, section.bottom_margin = Cm(2), Cm(2)
        section.left_margin, section.right_margin = Cm(3), Cm(1.5)

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p_title.add_run(f"Отчёт за {month_name} {report_date.year} г.")
    run.bold = True

    for g_key in sorted(sections_data.keys()):
        group = sections_data[g_key]
        active_blocks = [b for b in group['blocks'].values() if b['active'] and b['content'].strip()]
        if not active_blocks: continue

        # 🟢 Настройка заголовка группы (не жирный, с отступом)
        h = doc.add_paragraph()
        h_run = h.add_run(group['title'])
        h_run.bold = False 
        '''h.paragraph_format.first_line_indent = Cm(1.25)
        h.paragraph_format.line_spacing = 1.0'''
        fmt_h = h.paragraph_format
        fmt_h.first_line_indent = Cm(1.25)
        fmt_h.line_spacing = 1.0
        fmt_h.space_after = Pt(0) 
        fmt_h.space_before = Pt(0)

        for b_key in sorted(group['blocks'].keys()):
            block = group['blocks'][b_key]
            if not block['active'] or not block['content'].strip(): continue
            
            paragraphs = block['content'].split('\n')
            for p_text in paragraphs:
                if p_text.strip():
                    p = doc.add_paragraph()
                    fmt = p.paragraph_format
                    # 🟢 Межстрочный интервал 1.0
                    fmt.line_spacing = 1.0
                    fmt.space_after = Pt(0)
                    
                    if p_text.startswith('\t'):
                        # Реальная табуляция без маркированного списка
                        p.text = p_text.replace('\t', '', 1)
                        fmt.first_line_indent = Pt(36) # Имитация табуляции через отступ
                    elif p_text.strip().startswith(('–', '-', '*')):
                        p.style = 'List Bullet'
                        p.text = p_text.strip()[1:].strip()
                    else:
                        p.text = p_text
                        fmt.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                        fmt.first_line_indent = Cm(1.25)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def render_monthly_report_tab(session):
    st.subheader("📄 Конструктор отчёта НИПД")

    # --- 1. ВЫБОР ПЕРИОДА ---
    col_y, col_m = st.columns(2)
    with col_y: 
        s_year = st.selectbox("Год", [2025, 2026, 2027], index=1)
    with col_m: 
        s_month = st.selectbox("Месяц", list(MONTHS_RU.keys()), format_func=lambda x: MONTHS_RU[x], index=datetime.now().month - 1)

    report_date = date(s_year, s_month, 1)
    report_res = query_db("SELECT * FROM reports_monthly WHERE report_month = :d", {"d": report_date})

    # --- 2. ИНИЦИАЛИЗАЦИЯ ЧЕРНОВИКА ---
    if report_res.empty:
        if st.button("➕ Создать структуру черновика", use_container_width=True):
            session.execute(text("INSERT INTO reports_monthly (report_month, sections_data, created_by) VALUES (:d, :data, :uid)"),
                            {"d": report_date, "data": json.dumps(DEFAULT_SECTIONS, ensure_ascii=False), "uid": st.session_state.auth["user_id"]})
            session.commit(); clear_cache(); st.rerun()
        return

    rep_data = report_res.iloc[0]
    report_id = int(rep_data['report_id'])
    sections = rep_data['sections_data']
    is_fixed = rep_data['fixed_at'] is not None
    start_p, end_p = get_report_period_bounds(report_date)

    if is_fixed: 
        st.warning(f"🔒 Отчёт зафиксирован {rep_data['fixed_at'].strftime('%d.%m.%Y %H:%M')}")
    st.caption(f"Данные собираются за период: {start_p.strftime('%d.%m.%Y %H:%M')} — {end_p.strftime('%d.%m.%Y %H:%M')}")

    # --- 3. СИНХРОНИЗАЦИЯ СТРУКТУРЫ И ПЕРВИЧНАЯ ЗАГРУЗКА В STATE ---
    structure_changed = False
    for g_key, g_val in DEFAULT_SECTIONS.items():
        if g_key not in sections:
            sections[g_key] = g_val
            structure_changed = True
        for b_key, b_val in g_val['blocks'].items():
            if b_key not in sections[g_key]['blocks']:
                sections[g_key]['blocks'][b_key] = b_val
                structure_changed = True
            
            # Инициализируем Session State из базы, если ключей еще нет
            t_key = f"t_{g_key}_{b_key}"
            tx_key = f"tx_{g_key}_{b_key}_{report_id}"
            
            if t_key not in st.session_state:
                st.session_state[t_key] = sections[g_key]['blocks'][b_key]['active']
            if tx_key not in st.session_state:
                st.session_state[tx_key] = sections[g_key]['blocks'][b_key]['content']
    
    if structure_changed:
        session.execute(text("UPDATE reports_monthly SET sections_data = :d WHERE report_id = :id"),
                        {"d": json.dumps(sections, ensure_ascii=False), "id": report_id})
        session.commit()

    # --- 4. ЕДИНАЯ КНОПКА СБОРА ДАННЫХ ---
    if not is_fixed:
        if st.button("✨ Собрать данные для отчёта из базы", use_container_width=True, type="secondary"):
            # А. Получаем данные из базы
            new_users, totals = fetch_registration_stats(start_p, end_p)

            # --- БЛОК 02: РЕГИСТРАЦИЯ ---
            phys = len(new_users[new_users['applicant_type'] == 'Физическое лицо'])
            org_u = new_users[(new_users['applicant_type'] == 'Юридическое лицо') & (new_users['org_type'] == 'Пользователь')]
            if phys > 0 or not org_u.empty:
                p_txt = f"{phys}-х физических лиц" if phys > 1 else f"1-го физического лица" if phys == 1 else ""
                o_txt = f"{len(org_u)}-х юридических лиц" if len(org_u) > 1 else f"1-го юридического лица" if len(org_u) == 1 else ""
                conn = " и " if (p_txt and o_txt) else ""
                det = ", ".join([f"{r['applicant_name']} – {r['u_count']} учётных записей" for _, r in org_u.iterrows()])
                st.session_state[f"tx_6.1_02_reg_users_{report_id}"] = f"\t– обработаны заявки, осуществлена регистрация {p_txt}{conn}{o_txt}{' (' + det + ')' if det else ''};"
                st.session_state[f"t_6.1_02_reg_users"] = True
            else:
                st.session_state[f"t_6.1_02_reg_users"] = False

            # --- БЛОК 03: КАБИНЕТЫ ---
            sups = new_users[(new_users['applicant_type'] == 'Юридическое лицо') & (new_users['org_type'] == 'Поставщик')]
            if not sups.empty:
                names = ", ".join(sups['applicant_name'].tolist())
                st.session_state[f"tx_6.1_03_cabinets_{report_id}"] = f"– созданы и настроены электронные кабинеты, включая настройку ролей, пользователей и шаблонов метаданных для {len(sups)}{'-го Поставщика' if len(sups) == 1 else '-х Поставщиков'}: {names};"
                st.session_state[f"t_6.1_03_cabinets"] = True
            else:
                st.session_state[f"t_6.1_03_cabinets"] = False

            # --- БЛОК 04: СТАТИСТИКА ГП ---
            st.session_state[f"tx_6.1_04_total_stats_{report_id}"] = f"на конец отчётного периода на Национальном геопортале зарегистрировано:\n\t– {totals['phys']} физических лиц;\n\t– {totals['orgs']} юридических лиц;"
            st.session_state[f"t_6.1_04_total_stats"] = True

            # --- БЛОК 05: ПРЕДОСТАВЛЕНИЕ НИПД ---
            stats = fetch_provision_stats(start_p, end_p)

            def get_outcome_category(row):
                code = row['stage_code']
                comm = str(row['last_comment']).lower() if row['last_comment'] else ""
                # Если закрыта, но в комментарии есть слово "отказ" - это отказ
                if code == 'REQ_CLOSE' and ('отказ' in comm or 'возврат' in comm):
                    return "отказана Поставщиком"
                if code in ('REQ_AGREE_COMPL', 'REQ_CLOSE'): return "выполнена"
                if code == 'REQ_REGIS_RETUR' or code == 'REQ_REFUS_SUBMI': return "отклонена Оператором"
                return "отказана Поставщиком"

            def format_passport(row, is_nipd=True):
                applicant = row['applicant_name']
                if is_nipd:
                    details = f"заявитель — {applicant}, набор «{row['dataset_name']}» ({row['info_name']}), поставщик — {row['supplier_name']}"
                else:
                    mats = get_gkf_material_names(row['gkf_material_ids'])
                    details = f"заявитель — {applicant}, материалы: {mats}"
                
                cat = get_outcome_category(row)
                variant = "done" if "выполн" in cat else "op" if "Оператор" in cat else "sup"
                outcome_text = pluralize_outcome(1, variant)
                
                if variant != "done":
                    reason = f", причина: {row['last_comment']}" if row['last_comment'] else ""
                    return f"{outcome_text} ({details}{reason})"
                return f"{outcome_text} ({details})"

            def build_section(data, label, is_nipd=True):
                proc = data['processed']
                work = data['in_work']
                
                if proc.empty and work.empty:
                    return f"– {label} — в отчетном периоде не поступало;"

                count_proc = len(proc)
                v_obrab = pluralize_verb_fem(count_proc, ['полностью обработана', 'полностью обработаны'])
                n_curr = f"{count_proc} {pluralize(count_proc, ['заявка', 'заявки', 'заявок'])}"
                
                if count_proc >= 3:
                    bits = []
                    # Группируем для краткой формы
                    results = [get_outcome_category(r) for _, r in proc.iterrows()]
                    d_n = results.count("выполнена")
                    o_n = results.count("отклонена Оператором")
                    s_n = results.count("отказана Поставщиком")
                    if d_n: bits.append(f"{d_n} — {pluralize_outcome(d_n, 'done')}")
                    if o_n: bits.append(f"{o_n} — {pluralize_outcome(o_n, 'op')}")
                    if s_n: bits.append(f"{s_n} — {pluralize_outcome(s_n, 'sup')}")
                    res_str = f" ({', '.join(bits)})"
                else:
                    res_str = f" ({', '.join([format_passport(r, is_nipd) for _, r in proc.iterrows()])})"

                # Логика "В работе": Скрываем, если пусто
                work_str = ""
                if not work.empty:
                    w_list = []
                    for _, r in work.iterrows():
                        if is_nipd: w_list.append(f"заявитель — {r['applicant_name']}, «{r['dataset_name']}»")
                        else: w_list.append(f"заявитель — {r['applicant_name']}, материалы: {get_gkf_material_names(r['gkf_material_ids'])}")
                    
                    w_desc = f" ({'; '.join(w_list)})" if len(work) < 3 else ""
                    work_str = f", по {len(work)} {pluralize(len(work), ['заявке', 'заявкам', 'заявкам'])}{w_desc} работа продолжается"

                return f"– {label} — {v_obrab} {n_curr}{res_str}{work_str};"

            text_nipd = build_section(stats['NIPD'], "включенных в НИПД", True)
            text_gkf = build_section(stats['GKF'], "материалов Госкартгеофонда", False) # 👈 Одно слово "материалов"
            
            def format_total(count, label_text):
                if count == 0: return f"– {label_text} — не получены"
                return f"– {count} {pluralize(count, ['заявка', 'заявки', 'заявок'])} {label_text}"

            t_nipd = format_total(stats['NIPD']['totals']['total_received'], "на предоставление в пользование наборов пространственных данных, включенных в НИПД")
            t_gkf = format_total(stats['GKF']['totals']['total_received'], "на предоставление в пользование материалов Госкартгеофонда")

            full_content = (
                "прием, рассмотрение заявок на предоставление в пользование наборов пространственных данных:\n"
                f"{text_nipd}\n{text_gkf}\n"
                "на конец отчётного периода обработано:\n"
                f"{t_nipd},\n{t_gkf};"
            )

            st.session_state[f"tx_6.1_05_provision_nipd_{report_id}"] = full_content
            st.session_state[f"t_6.1_05_provision_nipd"] = True

    # --- 5. РЕНДЕР КОНСТРУКТОРА (ЦИКЛ ПО ГРУППАМ) ---
    updated_full_data = {}
    
    # Сортируем группы (6.1, 6.3)
    for g_key in sorted(sections.keys()):
        g_data = sections[g_key]
        with st.container(border=True):
            st.markdown(f"#### Группа {g_key}")
            
            updated_blocks = {}
            # Сортируем блоки внутри группы (01, 02, 03...)
            for b_key in sorted(g_data['blocks'].keys()):
                b_data = g_data['blocks'][b_key]
                t_key = f"t_{g_key}_{b_key}"
                tx_key = f"tx_{g_key}_{b_key}_{report_id}"
                
                with st.container(border=False):
                    c_tit, c_tog = st.columns([0.8, 0.2])
                    c_tit.markdown(f"**{b_data['title']}**")
                    
                    # Переключатель (только key)
                    is_act = c_tog.toggle("Вкл.", key=t_key, disabled=is_fixed)
                    # Текстовое поле (только key)
                    content = st.text_area("Текст:", key=tx_key, disabled=not is_act or is_fixed, height=120)
                    
                    updated_blocks[b_key] = {"title": b_data['title'], "active": is_act, "content": content}
            
            updated_full_data[g_key] = {"title": g_data['title'], "blocks": updated_blocks}

    # --- 6. КНОПКИ СОХРАНЕНИЯ И СКАЧИВАНИЯ ---
    st.divider()
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if not is_fixed:
            if st.button("💾 Сохранить черновик", use_container_width=True, type="primary"):
                session.execute(text("UPDATE reports_monthly SET sections_data=:d, updated_at=NOW() WHERE report_id=:id"),
                                {"d": json.dumps(updated_full_data, ensure_ascii=False), "id": report_id})
                session.commit(); clear_cache(); st.toast("✅ Сохранено в БД")
    
    with col2:
        if not is_fixed:
            if st.button("🔒 Зафиксировать", use_container_width=True, help="Отключает редактирование навсегда"):
                session.execute(text("UPDATE reports_monthly SET fixed_at=NOW(), sections_data=:d WHERE report_id=:id"),
                                {"d": json.dumps(updated_full_data, ensure_ascii=False), "id": report_id})
                session.commit(); clear_cache(); st.rerun()
                
    with col3:
        # Генерация файла происходит на основе текущего состояния updated_full_data
        buf = generate_docx_file(report_date, updated_full_data, MONTHS_RU[s_month])
        st.download_button(
            label="📥 Скачать .docx",
            data=buf,
            file_name=f"Report_NIPD_{s_year}_{s_month}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )

def fetch_provision_stats(start_t, end_t):
    """Сбор статистики с расширенными данными для НИПД и ГКГФ"""
    
    SUCCESS = ('REQ_AGREE_COMPL', 'REQ_CLOSE')
    # Для ГКГФ REQ_CLOSE часто может быть и успехом, и отказом. 
    # Поэтому мы будем смотреть на финальный статус в истории.

    def get_details(req_type):
        # 1. Завершенные (теперь тянем gkf_material_ids)
        query = f"""
            SELECT 
                pr.req_id, pr.applicant_name, pr.request_type, pr.gkf_material_ids,
                it.info_name, ds.dataset_name, sup.supplier_name,
                s.stage_code, h.comments as last_comment,
                (SELECT s2.stage_code FROM provision_request_history h2 
                 JOIN stages s2 ON h2.stage_id = s2.stage_id 
                 WHERE h2.req_id = pr.req_id AND h2.actual_end = h.actual_start 
                 LIMIT 1) as prev_stage_code
            FROM provision_requests pr
            JOIN stages s ON pr.status_id = s.stage_id
            JOIN provision_request_history h ON h.req_id = pr.req_id AND h.stage_id = pr.status_id
            LEFT JOIN info_types it ON pr.nipd_info_id = it.info_id
            LEFT JOIN datasets ds ON it.dataset_id = ds.dataset_id
            LEFT JOIN project_items pi ON it.info_id = pi.info_id
            LEFT JOIN projects p ON pi.project_id = p.project_id
            LEFT JOIN suppliers sup ON p.supplier_id = sup.supplier_id
            WHERE pr.request_type = :rt AND h.actual_start BETWEEN :s AND :e
              AND s.stage_code IN ('REQ_CLOSE', 'REQ_AGREE_COMPL', 'REQ_REGIS_RETUR', 'REQ_REFUS_SUBMI', 'REQ_REFUS_RECEI')
        """
        processed = query_db(query, {"rt": req_type, "s": start_t, "e": end_t})

        # 2. В работе (тянем gkf_material_ids)
        query_work = f"""
            SELECT pr.applicant_name, pr.gkf_material_ids, it.info_name, ds.dataset_name, sup.supplier_name
            FROM provision_requests pr
            JOIN stages s ON pr.status_id = s.stage_id
            LEFT JOIN info_types it ON pr.nipd_info_id = it.info_id
            LEFT JOIN datasets ds ON it.dataset_id = ds.dataset_id
            LEFT JOIN project_items pi ON it.info_id = pi.info_id
            LEFT JOIN projects p ON pi.project_id = p.project_id
            LEFT JOIN suppliers sup ON p.supplier_id = sup.supplier_id
            WHERE pr.request_type = :rt 
              AND s.stage_code NOT IN ('REQ_CLOSE', 'REQ_AGREE_COMPL', 'REQ_REGIS_RETUR', 'REQ_REFUS_SUBMI', 'REQ_REFUS_RECEI')
        """
        in_work = query_db(query_work, {"rt": req_type})

        # 3. Накопительный
        totals = query_db(f"""
            SELECT COUNT(*) as total_received
            FROM provision_requests pr
            WHERE pr.request_type = :rt
        """, {"rt": req_type}).iloc[0]

        return {"processed": processed, "in_work": in_work, "totals": totals}

    return {"NIPD": get_details("НИПД"), "GKF": get_details("Госкартгеофонд")}