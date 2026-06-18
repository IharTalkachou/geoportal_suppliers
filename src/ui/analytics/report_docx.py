import streamlit as st
import pandas as pd
from datetime import date
from sqlalchemy import text
import io
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING

from config.cache import query_db, clear_cache
from config.auth import log_action


# Список наших разделов по умолчанию
DEFAULT_SECTIONS = {
    "section_1": {"title": "Регистрация пользователей", "active": True, "content": ""},
    "section_2": {"title": "Создание электронных кабинетов", "active": True, "content": ""},
    "section_3": {"title": "Заключение соглашений", "active": True, "content": ""}
}

def render_monthly_report_tab(session):
    st.subheader("📄 Отчёт НИПД за месяц (.docx)")

    # --- 1. ФИЛЬТР ПЕРИОДА ---
    col_y, col_m, col_btn = st.columns([1, 1, 1])
    
    with col_y:
        years = [y for y in range(2026, 2026+50)]
        selected_year = st.selectbox("Год", years, years.index(date.today().year))
    with col_m:
        months = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август", 
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }
        # По умолчанию ставим текущий месяц
        selected_month_num = st.selectbox("Месяц", list(months.keys()), 
                                          format_func=lambda x: months[x], 
                                          index=date.today().month - 1)

    # Формируем дату как первое число месяца для БД
    report_date = date(selected_year, selected_month_num, 1)

    # --- 2. ПРОВЕРКА НАЛИЧИЯ ОТЧЕТА В БД ---
    report_res = query_db("SELECT * FROM reports_monthly WHERE report_month = :d", {"d": report_date})
    
    if report_res.empty:
        st.info(f"📭 Отчёт за {months[selected_month_num]} {selected_year} г. ещё не создан.")
        if st.button("➕ Создать черновик отчёта", type="primary"):
            try:
                import json
                session.execute(text("""
                    INSERT INTO reports_monthly (report_month, sections_data, created_by)
                    VALUES (:d, :data, :uid)
                """), {
                    "d": report_date, 
                    "data": json.dumps(DEFAULT_SECTIONS, ensure_ascii=False),
                    "uid": st.session_state.auth["user_id"]
                })
                session.commit()
                clear_cache()
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка создания: {e}")
        return

    # Если отчет найден - работаем с ним
    report_id = int(report_res.iloc[0]['report_id'])
    sections = report_res.iloc[0]['sections_data'] # Это уже dict благодаря JSONB

    # --- 3. РЕДАКТОР РАЗДЕЛОВ ---
    st.markdown("---")
    st.write("### 🛠 Редактирование содержания")
    
    updated_sections = {}

    for key, data in sections.items():
        # Каждая секция в отдельной рамке
        with st.container(border=True):
            c_title, c_toggle = st.columns([0.8, 0.2])
            with c_title:
                st.markdown(f"#### {data['title']}")
            with c_toggle:
                # Чекбокс активности раздела
                is_active = st.toggle("Включить", value=data['active'], key=f"tog_{key}_{report_id}")
            
            # Текстовое поле (показываем всегда, но блокируем если раздел выключен)
            content = st.text_area(
                "Текст раздела для Word:", 
                value=data['content'], 
                height=150, 
                key=f"txt_{key}_{report_id}",
                disabled=not is_active,
                placeholder="Введите здесь описание выполнения или ключевые показатели..."
            )
            
            # Сохраняем измененные данные в локальный словарь
            updated_sections[key] = {
                "title": data['title'],
                "active": is_active,
                "content": content
            }

    # --- 4. КНОПКИ ДЕЙСТВИЙ ---
    st.markdown("---")
    cb1, cb2 = st.columns(2)
    
    with cb1:
        if st.button("💾 Сохранить черновик", use_container_width=True, type="primary"):
            try:
                import json
                session.execute(text("""
                    UPDATE reports_monthly 
                    SET sections_data = :data, updated_at = NOW() 
                    WHERE report_id = :id
                """), {
                    "data": json.dumps(updated_sections, ensure_ascii=False),
                    "id": report_id
                })
                session.commit()
                clear_cache()
                st.toast("✅ Изменения сохранены в базе данных")
            except Exception as e:
                st.error(f"Ошибка сохранения: {e}")

    with cb2:
        # Генерируем файл на лету из текущих (даже не сохраненных еще) данных в полях ввода
        docx_buffer = generate_docx_file(report_date, updated_sections, months[selected_month_num])
        
        st.download_button(
            label="📥 Скачать .docx",
            data=docx_buffer,
            file_name=f"Report_NIPD_{selected_year}_{selected_month_num}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )

def generate_docx_file(report_date, sections, month_name):
    """Создает DOCX документ в памяти"""
    doc = Document()
    
    # Заголовок документа
    #title = doc.add_heading(f"Отчёт по НИПД за {month_name} {report_date.year} г.", 0)
    #title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # --- 1. ГЛОБАЛЬНЫЕ НАСТРОЙКИ СТИЛЯ ---
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(14)

    # Настройка полей страницы (Стандарт: Левое 3см, остальное по 1.5-2см)
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(3)
        section.right_margin = Cm(1.5)

    # 2. Перебор разделов
    for key in sorted(sections.keys()):
        data = sections[key]
        if not data.get('active'):
            continue
        
        # Добавляем название раздела
        #doc.add_heading(data['title'], level=1)
        
        # Добавляем содержимое
        content = data.get('content', '')
        if content:
            paragraphs = content.split('\n')
            for p_text in paragraphs:
                if p_text.strip():
                    p = doc.add_paragraph()
                    fmt = p.paragraph_format
                    
                    # Стандартное форматирование абзаца
                    fmt.line_spacing_rule = WD_LINE_SPACING.SINGLE # Интервал одиночный
                    fmt.space_after = Pt(0)                        # Убираем лишние отступы между абзацами
                    fmt.space_before = Pt(0)
                    
                    if p_text.strip().startswith(('-', '*')):
                        # Маркированный список
                        p.style = 'List Bullet'
                        p.text = p_text.strip()[1:].strip()
                    else:
                        # Обычный текст с "красной строкой"
                        p.text = p_text.strip()
                        fmt.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY # По ширине
                        fmt.first_line_indent = Cm(1.25)            # Отступ 1.25 см
        else:
            # Если раздел активен, но пуст - можно либо ничего не писать, 
            # либо оставить пустую строку
            doc.add_paragraph("")

    # Сохраняем в буфер
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer