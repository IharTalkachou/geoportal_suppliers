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

    col_y, col_m = st.columns(2)
    with col_y: s_year = st.selectbox("Год", [2025, 2026, 2027], index=1)
    with col_m: s_month = st.selectbox("Месяц", list(MONTHS_RU.keys()), format_func=lambda x: MONTHS_RU[x], index=datetime.now().month - 1)

    report_date = date(s_year, s_month, 1)
    report_res = query_db("SELECT * FROM reports_monthly WHERE report_month = :d", {"d": report_date})

    if report_res.empty:
        if st.button("➕ Создать структуру черновика"):
            session.execute(text("INSERT INTO reports_monthly (report_month, sections_data, created_by) VALUES (:d, :data, :uid)"),
                            {"d": report_date, "data": json.dumps(DEFAULT_SECTIONS, ensure_ascii=False), "uid": st.session_state.auth["user_id"]})
            session.commit(); clear_cache(); st.rerun()
        return

    rep_data = report_res.iloc[0]
    report_id = int(rep_data['report_id'])
    sections = rep_data['sections_data']
    is_fixed = rep_data['fixed_at'] is not None
    start_p, end_p = get_report_period_bounds(report_date)

    if is_fixed: st.warning(f"🔒 Отчёт зафиксирован {rep_data['fixed_at'].strftime('%d.%m.%Y %H:%M')}")
    
    # 🟢 ЕДИНАЯ КНОПКА СБОРА ДАННЫХ
    if not is_fixed:
        if st.button("✨ Собрать данные для отчёта из базы", width='stretch', type="secondary"):
            new_users, totals = fetch_registration_stats(start_p, end_p)
            
            # Логика для Блока 02 (Регистрация)
            phys = len(new_users[new_users['applicant_type'] == 'Физическое лицо'])
            org_u = new_users[(new_users['applicant_type'] == 'Юридическое лицо') & (new_users['org_type'] == 'Пользователь')]
            if phys > 0 or not org_u.empty:
                p_txt = f"{phys}-х физических лиц" if phys > 1 else f"1-го физического лица" if phys == 1 else ""
                o_txt = f"{len(org_u)}-х юридических лиц" if len(org_u) > 1 else f"1-го юридического лица" if len(org_u) == 1 else ""
                conn = " и " if (p_txt and o_txt) else ""
                det = ", ".join([f"{r['applicant_name']} – {r['u_count']} учётных записей" for _, r in org_u.iterrows()])
                det_str = f" ({det})" if det else ""
                st.session_state[f"tx_6.1_02_reg_users_{report_id}"] = f"\t– обработаны заявки, осуществлена регистрация {p_txt}{conn}{o_txt}{det_str};"
                st.session_state[f"t_6.1_02_reg_users"] = True
            else:
                st.session_state[f"t_6.1_02_reg_users"] = False

            # Логика для Блока 03 (Кабинеты)
            sups = new_users[(new_users['applicant_type'] == 'Юридическое лицо') & (new_users['org_type'] == 'Поставщик')]
            if not sups.empty:
                names = ", ".join(sups['applicant_name'].tolist())
                st.session_state[f"tx_6.1_03_cabinets_{report_id}"] = f"\t– созданы и настроены электронные кабинеты, включая настройку ролей, пользователей и шаблонов метаданных для {len(sups)}{'-го Поставщика' if len(sups) == 1 else '-х Поставщиков'}: {names};"
                st.session_state[f"t_6.1_03_cabinets"] = True
            else:
                st.session_state[f"t_6.1_03_cabinets"] = False

            # Логика для Блока 04 (Статистика)
            st.session_state[f"tx_6.1_04_total_stats_{report_id}"] = f"на конец отчётного периода на Национальном геопортале зарегистрировано:\n\t– {totals['phys']} физических лиц;\n\t– {totals['orgs']} юридических лиц;"
            st.session_state[f"t_6.1_04_total_stats"] = True
            
            st.rerun()

    # --- РЕНДЕР КОНСТРУКТОРА ---
    updated_full_data = {}
    for g_key in sorted(sections.keys()):
        g_data = sections[g_key]
        with st.container(border=True):
            st.markdown(f"**Группа {g_key}**")
            
            updated_blocks = {}
            # Сортируем блоки по ключу (01, 02, 03...)
            for b_key in sorted(g_data['blocks'].keys()):
                b_data = g_data['blocks'][b_key]
                with st.container(border=False):
                    c_tit, c_tog = st.columns([0.8, 0.2])
                    c_tit.markdown(f"_{b_data['title']}_")
                    
                    # Если данных нет, выводим инфо-строку
                    if b_key == "02_reg_users" or b_key == "03_cabinets":
                        new_u, _ = fetch_registration_stats(start_p, end_p)
                        if b_key == "02_reg_users":
                            val = len(new_u[new_u['org_type'] != 'Поставщик'])
                        else:
                            val = len(new_u[new_u['org_type'] == 'Поставщик'])
                        
                        if val == 0:
                            c_tit.caption("⚠️ Данных в базе нет. Рекомендуется исключить блок.")

                    is_act = c_tog.toggle("Вкл.", value=b_data['active'], key=f"t_{g_key}_{b_key}", disabled=is_fixed)
                    
                    text_key = f"tx_{g_key}_{b_key}_{report_id}"
                    if text_key not in st.session_state:
                        st.session_state[text_key] = b_data['content']

                    content = st.text_area("Текст:", key=text_key, disabled=not is_act or is_fixed, height=100)
                    updated_blocks[b_key] = {"title": b_data['title'], "active": is_act, "content": content}
            
            updated_full_data[g_key] = {"title": g_data['title'], "blocks": updated_blocks}

    # --- КНОПКИ ---
    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        if not is_fixed:
            if st.button("💾 Сохранить черновик", width='stretch', type="primary"):
                session.execute(text("UPDATE reports_monthly SET sections_data=:d WHERE report_id=:id"),
                                {"d": json.dumps(updated_full_data, ensure_ascii=False), "id": report_id})
                session.commit(); clear_cache(); st.toast("✅ Сохранено")
    with col2:
        if not is_fixed:
            if st.button("🔒 Зафиксировать", width='stretch'):
                session.execute(text("UPDATE reports_monthly SET fixed_at=NOW(), sections_data=:d WHERE report_id=:id"),
                                {"d": json.dumps(updated_full_data, ensure_ascii=False), "id": report_id})
                session.commit(); clear_cache(); st.rerun()
    with col3:
        buf = generate_docx_file(report_date, updated_full_data, MONTHS_RU[s_month])
        st.download_button("📥 Скачать .docx", buf, f"Report_{s_year}_{s_month}.docx", width='stretch')