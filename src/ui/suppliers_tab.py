import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache

# 🔤 Маппинг английских названий колонок БД на русские для UI
RU_LABELS = {
    "supplier_name": "Наименование",
    "supplier_address": "Адрес",
    "supplier_email": "Email",
    "supplier_phone": "Телефон",
    "supplier_website": "Сайт",
    "supplier_manager": "Руководитель",
    "supplier_notes": "Примечание"
}

def render_suppliers_tab(session):
    st.subheader("📁 Поставщики и контакты")
    
    # 🔍 Выбор поставщика
    all_suppliers = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
    sup_map = dict(zip(all_suppliers["supplier_name"], all_suppliers["supplier_id"]))
    selected_sup_name = st.selectbox("🏢 Выберите поставщика для просмотра", [""] + list(sup_map.keys()), key="sup_selector")
    selected_sup_id = sup_map.get(selected_sup_name) if selected_sup_name else None
    
    st.markdown("---")
    
    # ==========================================
    # БЛОК 1: Карточка + контакты выбранного поставщика
    # ==========================================
    if selected_sup_id:
        sup_data = query_db("SELECT * FROM suppliers WHERE supplier_id = :sid", {"sid": selected_sup_id}).iloc[0]
        
        # 🏢 Заголовок карточки (имя поставщика)
        st.markdown(f"### 🏢 {sup_data['supplier_name']}")
        
        # 📋 Вертикальные метрики (исключаем ID и дублирующее имя)
        for col in sup_data.index:
            if col in ["supplier_id", "supplier_name"]:
                continue
            if pd.notna(sup_data[col]):
                label = RU_LABELS.get(col, col.replace("_", " ").capitalize())
                st.metric(f"📌 {label}", sup_data[col])
        
        # 📇 Контакты с редактором
        st.markdown("#### 📇 Контакты")
        contacts_df = query_db("""
            SELECT c.contact_id, c.full_name, c.position, c.email, c.phone, c.notes
            FROM contacts c WHERE c.supplier_id = :sid ORDER BY c.full_name
        """, {"sid": selected_sup_id})
        
        if not contacts_df.empty:
            contact_col_config = {
                "full_name": st.column_config.TextColumn("ФИО / Контакт", required=True),
                "position": st.column_config.TextColumn("Должность"),
                "email": st.column_config.TextColumn("Email"),
                "phone": st.column_config.TextColumn("Телефон"),
                "notes": st.column_config.TextColumn("Примечание"),
                "contact_id": st.column_config.NumberColumn("ID", disabled=True)
            }
            
            with st.form("contacts_editor_form"):
                edited_contacts = st.data_editor(
                    contacts_df, key="contacts_editor", hide_index=True, use_container_width=True,
                    num_rows="dynamic", column_config=contact_col_config, 
                    disabled=["contact_id"],
                    column_order=["full_name", "position", "email", "phone", "notes"]
                )
                
                orig_ids = set(contacts_df["contact_id"].dropna().astype(int))
                curr_ids = set(edited_contacts["contact_id"].dropna().astype(int))
                deleted_ids = list(orig_ids - curr_ids)
                
                if st.form_submit_button("💾 Сохранить контакты", type="primary"):
                    try:
                        if deleted_ids:
                            session.execute(text("DELETE FROM contacts WHERE contact_id IN :ids"), {"ids": tuple(deleted_ids)})
                        
                        for _, row in edited_contacts.iterrows():
                            cid = row.get("contact_id")
                            is_new = pd.isna(cid)
                            if is_new:
                                session.execute(text("""
                                    INSERT INTO contacts (full_name, supplier_id, position, email, phone, notes)
                                    VALUES (:name, :sid, :pos, :em, :ph, :nt)
                                """), {
                                    "name": row["full_name"], "sid": selected_sup_id,
                                    "pos": row.get("position"), "em": row.get("email"),
                                    "ph": row.get("phone"), "nt": row.get("notes")
                                })
                            else:
                                session.execute(text("""
                                    UPDATE contacts SET full_name=:name, position=:pos, email=:em, phone=:ph, notes=:nt
                                    WHERE contact_id=:id
                                """), {
                                    "name": row["full_name"], "pos": row.get("position"),
                                    "em": row.get("email"), "ph": row.get("phone"),
                                    "nt": row.get("notes"), "id": int(cid)
                                })
                        
                        session.commit()
                        clear_cache()
                        st.success("✅ Контакты сохранены!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Ошибка БД: {e}")
                        session.rollback()
        else:
            st.info("📭 У этого поставщика пока нет контактов.")
        
        # ➕ Добавить контакт
        with st.expander("➕ Добавить контакт для этого поставщика"):
            with st.form("add_contact_form"):
                col1, col2 = st.columns(2)
                with col1:
                    full_name = st.text_input("ФИО / Название контакта *")
                    position = st.text_input("Должность")
                with col2:
                    email = st.text_input("Email")
                    phone = st.text_input("Телефон")
                notes = st.text_area("Примечание", height=60)
                
                if st.form_submit_button("💾 Создать контакт", type="primary"):
                    if not full_name.strip():
                        st.error("❌ Имя контакта не может быть пустым")
                    else:
                        try:
                            session.execute(text("""
                                INSERT INTO contacts (full_name, supplier_id, position, email, phone, notes)
                                VALUES (:name, :sid, :pos, :em, :ph, :nt)
                            """), {
                                "name": full_name.strip(), "sid": selected_sup_id,
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
    
    else:
        st.info("👆 Выберите поставщика выше для просмотра карточки и контактов.")
    
    st.markdown("---")
    
    # ==========================================
    # БЛОК 2: Все поставщики + редактор (ВНИЗУ)
    # ==========================================
    st.markdown("### 📋 Все поставщики (редактирование)")
    suppliers_df = query_db("SELECT * FROM suppliers ORDER BY supplier_name")
    
    # Динамически формируем конфиг для всех колонок БД
    visible_cols = [c for c in suppliers_df.columns if c != "supplier_id"]
    col_config = {}
    for c in visible_cols:
        if c == "supplier_name":
            col_config[c] = st.column_config.TextColumn(RU_LABELS[c], required=True)
        else:
            col_config[c] = st.column_config.TextColumn(RU_LABELS.get(c, c.replace("_", " ").capitalize()))

    with st.form("suppliers_editor_form"):
        edited_suppliers = st.data_editor(
            suppliers_df, key="suppliers_editor", hide_index=True, use_container_width=True,
            num_rows="dynamic", column_config=col_config, 
            disabled=["supplier_id"],
            column_order=visible_cols  # 🔹 ID скрыт из UI
        )
        
        orig_ids = set(suppliers_df["supplier_id"].dropna().astype(int))
        curr_ids = set(edited_suppliers["supplier_id"].dropna().astype(int))
        deleted_ids = list(orig_ids - curr_ids)
        
        if st.form_submit_button("💾 Сохранить поставщиков", type="primary"):
            try:
                if deleted_ids:
                    session.execute(text("DELETE FROM suppliers WHERE supplier_id IN :ids"), {"ids": tuple(deleted_ids)})
                
                # Поля для обновления (исключаем PK и имя, так как имя обрабатывается отдельно)
                update_fields = [c for c in visible_cols if c not in ["supplier_name", "supplier_id"]]
                
                for _, row in edited_suppliers.iterrows():
                    sid = row.get("supplier_id")
                    is_new = pd.isna(sid)
                    
                    params = {"name": row["supplier_name"]}
                    for field in update_fields:
                        params[field] = row.get(field)
                    params["id"] = int(sid) if not is_new else None

                    if is_new:
                        fields_str = ", ".join(["supplier_name"] + update_fields)
                        vals_str = ", ".join([":name"] + [f":{f}" for f in update_fields])
                        session.execute(text(f"INSERT INTO suppliers ({fields_str}) VALUES ({vals_str})"), params)
                    else:
                        set_str = ", ".join([f"{f} = :{f}" for f in update_fields])
                        session.execute(text(f"UPDATE suppliers SET supplier_name = :name, {set_str} WHERE supplier_id = :id"), params)
                
                session.commit()
                clear_cache()
                st.success("✅ Поставщики сохранены!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка БД: {e}")
                session.rollback()
    
    # ➕ Добавить поставщика
    with st.expander("➕ Добавить нового поставщика"):
        with st.form("add_supplier_form"):
            new_sup_name = st.text_input("Наименование поставщика *")
            if st.form_submit_button("💾 Создать поставщика", type="primary"):
                if new_sup_name.strip():
                    try:
                        session.execute(text("INSERT INTO suppliers (supplier_name) VALUES (:name)"), {"name": new_sup_name.strip()})
                        session.commit()
                        clear_cache()
                        st.success("✅ Поставщик добавлен!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Ошибка: {e}")
                        session.rollback()
                else:
                    st.error("❌ Наименование не может быть пустым")