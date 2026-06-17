import streamlit as st
import pandas as pd
from datetime import date
from sqlalchemy import text
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
        selected_year = st.selectbox("Год", [2026, 2027, 2028, 2029, 2030], index=1)
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
        st.button("📥 Сгенерировать .docx (Скоро)", use_container_width=True, disabled=True)