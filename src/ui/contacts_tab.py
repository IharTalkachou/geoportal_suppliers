import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache

def render_contacts_tab(session):
    st.subheader("📇 Контакты поставщиков")

    # Загрузка данных с новыми полями
    df = query_db("""
        SELECT c.contact_id, c.full_name, c.position, c.email, c.phone, c.notes, s.supplier_name 
        FROM contacts c
        JOIN suppliers s ON c.supplier_id = s.supplier_id
        ORDER BY s.supplier_name, c.full_name
    """)

    if not df.empty:
        st.dataframe(df[["supplier_name", "full_name", "position", "email", "phone", "notes"]], 
                     use_container_width=True, hide_index=True, column_config={
            "supplier_name": "Поставщик",
            "full_name": "ФИО / Контакт",
            "position": "Должность",
            "email": "Email",
            "phone": "Телефон",
            "notes": "Примечание"
        })
    else:
        st.info("📭 В базе пока нет контактов. Добавьте первый ниже.")

    st.markdown("---")
    st.subheader("➕ Добавить контакт")

    with st.form("add_contact_form"):
        col1, col2 = st.columns(2)
        with col1:
            full_name = st.text_input("ФИО / Название контакта *")
            position = st.text_input("Должность")
        with col2:
            email = st.text_input("Email")
            phone = st.text_input("Телефон")
            
        notes = st.text_area("Примечание", height=80)

        suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
        supplier_map = {row["supplier_name"]: row["supplier_id"] for _, row in suppliers.iterrows()}
        selected_supplier = st.selectbox("Поставщик *", list(supplier_map.keys()))

        submitted = st.form_submit_button("💾 Сохранить", type="primary", use_container_width=True)

        if submitted:
            if not full_name.strip():
                st.error("❌ Имя контакта не может быть пустым")
            else:
                try:
                    session.execute(text("""
                        INSERT INTO contacts (full_name, supplier_id, position, email, phone, notes)
                        VALUES (:name, :sid, :pos, :em, :ph, :nt)
                    """), {
                        "name": full_name.strip(),
                        "sid": supplier_map[selected_supplier],
                        "pos": position.strip() if position.strip() else None,
                        "em": email.strip() if email.strip() else None,
                        "ph": phone.strip() if phone.strip() else None,
                        "nt": notes.strip() if notes.strip() else None
                    })
                    session.commit()
                    clear_cache()
                    st.success("✅ Контакт добавлен!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка БД: {e}")
                    session.rollback()