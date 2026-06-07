import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db

def render_survey_viewer(session, survey_id, is_readonly=True):
    """Детальный просмотр всех полей опросника (общий компонент)"""
    
    # 1. Загрузка данных
    res = query_db("SELECT * FROM surveys WHERE survey_id = :sid", {"sid": survey_id})
    
    if res.empty:
        # Если опросник удален, сбрасываем состояние в зависимости от того, откуда вызван
        for key in ["survey_view_id", "an_survey_view_id"]:
            if key in st.session_state: st.session_state[key] = None
        return

    data = res.iloc[0]
    contacts = query_db("""
        SELECT c.full_name FROM survey_contacts sc 
        JOIN contacts c ON sc.contact_id = c.contact_id WHERE sc.survey_id = :sid
    """, {"sid": survey_id})
    
    links = query_db("SELECT survey_link FROM survey_links WHERE survey_id = :sid", {"sid": survey_id})
    
    int_query = query_db("""
        SELECT ri.interaction_text FROM survey_interactions si
        JOIN ref_interactions ri ON si.interaction_id = ri.interaction_id
        WHERE si.survey_id = :sid
    """, {"sid": int(survey_id)})
    all_ints = int_query["interaction_text"].tolist() if not int_query.empty else ["Не указаны"]

    st.success(f"📄 Опросный лист №{survey_id} от {data['received_date'].strftime('%d.%m.%Y')}")

    # Блок ПРАВО
    with st.expander("⚖️ Правовой статус и доступ", expanded=True):
        st.write(f"**Описание набора:** {data['it_description']}")
        st.write(f"**Назначение:** {data['it_purpose']}")
        st.write(f"**Правовой статус:** {data['it_legal_status']}")
        st.write(f"**НПА и ТНПА:** {data['it_statute']}")
        
        regs = data['it_regulations']
        display_regs = ", ".join(regs) if isinstance(regs, list) else str(regs).strip('{}').replace('"', '')
        st.write(f"**Гриф(ы):** `{display_regs}`")
        st.write(f"**Иные ограничения:** {data['it_other_regulations']}")

    # Блок ТЕХНИКА
    with st.expander("⚙️ Технические характеристики", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**Форма ведения:** {data['it_format']}")
            st.write(f"**Вид данных:** {data['it_type']}")
            st.write(f"**Формат хранения:** {data['it_digital_format']}")
            st.write(f"**Цифровая трансформация:** {'✅ Нужна' if data['it_digital_transform'] else '❌ Не требуется'}")
            st.write(f"**Каталоги метаданных:** {data['it_metadata_base']}")
            st.write(f"**Системы координат:** {data['it_coordinate_system']}")
        with c2:
            st.write(f"**Актуальность:** {data['it_actual_date']}")
            st.write(f"**Обновление:** {data['it_update']}")
            st.write(f"**Территория:** {data['it_spatial_extent']}")
            st.write(f"**Масштаб/Разрешение:** {data['it_spatial_scale']}")
            st.write(f"**Классификатор:** {data['it_classification']}")
            st.write(f"**Условные знаки:** {data['it_conventional_signs']}")
        
        st.divider()
        dets = data['it_coordinate_determining']
        display_dets = ", ".join(dets) if isinstance(dets, list) else str(dets).strip('{}').replace('"', '')
        st.write(f"**Способ(ы) определения координат:** `{display_dets}`")
        st.info(f"**Методика получения координат:**\n\n{data['it_coordinate_determining_text']}")
        st.write(f"**Использование у поставщика:** {data['it_use']}")

    # Блок ВЗАИМОДЕЙСТВИЕ
    with st.expander("🤝 Взаимодействие и публикация", expanded=True):
        st.write(f"**Варианты взаимодействия:**")
        st.info(" • " + "\n • ".join(all_ints))
        st.write(f"**Форматы предоставления:** {data['it_distribution_format']}")
        st.write(f"**Способы предоставления:** {data['it_distribution_method']}")
        st.write(f"**Протоколы обмена:** {data['it_distribution_protocol']}")
        st.write(f"**Базовые сервисы НГ:** {data['it_base_services']}")
        st.write(f"**Публикация в СНГ:** {'✅ Допускается' if data['it_cis_publication'] else '❌ Запрещена'}")
        
        st.write("**👤 Ответственные контакты:**")
        if not contacts.empty: st.info(", ".join(contacts["full_name"].tolist()))
        
        st.write("**🔗 Ссылки:**")
        if not links.empty:
            for l in links["survey_link"]: st.markdown(f"- {l}")

    '''# Кнопка закрытия (с разным поведением для вкладок)
    if st.button("⬅️ Закрыть просмотр", key=f"close_viewer_{survey_id}"):
        if "survey_view_id" in st.session_state: st.session_state["survey_view_id"] = None
        if "an_survey_view_id" in st.session_state: st.session_state["an_survey_view_id"] = None
        st.rerun()'''