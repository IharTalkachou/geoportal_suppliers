import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache

# 🔤 Маппинг английских названий колонок БД на русские
RU_LABELS = {
    "supplier_name": "Наименование", "supplier_address": "Адрес",
    "supplier_email": "Email", "supplier_phone": "Телефон",
    "supplier_website": "Сайт", "supplier_manager": "Руководитель",
    "supplier_notes": "Примечание"
}

def render_suppliers_tab(session, user_role="user"):
    st.subheader("📁 Поставщики и контакты")
    is_readonly = (user_role == "user")
    
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
        
        st.markdown(f"### 🏢 {sup_data['supplier_name']}")
        for col in sup_data.index:
            if col in ["supplier_id", "supplier_name"]: continue
            if pd.notna(sup_data[col]):
                label = col.replace("_", " ").capitalize()
                st.metric(f"📌 {label}", sup_data[col])
        
        st.markdown("#### 📇 Контакты")
        contacts_df = query_db("""
            SELECT c.contact_id, c.full_name, c.position, c.email, c.phone, c.notes
            FROM contacts c WHERE c.supplier_id = :sid ORDER BY c.full_name
        """, {"sid": selected_sup_id})
        
        if not contacts_df.empty:
            contact_col_config = {
                "full_name": st.column_config.TextColumn("ФИО / Контакт", required=not is_readonly),
                "position": st.column_config.TextColumn("Должность"),
                "email": st.column_config.TextColumn("Email"),
                "phone": st.column_config.TextColumn("Телефон"),
                "notes": st.column_config.TextColumn("Примечание"),
                "contact_id": st.column_config.NumberColumn("ID", disabled=True)
            }
            
            with st.form("contacts_editor_form"):
                edited_contacts = st.data_editor(
                    contacts_df, key="contacts_editor", hide_index=True, use_container_width=True,
                    num_rows="dynamic" if not is_readonly else "fixed",
                    column_config=contact_col_config, 
                    disabled=["full_name", "position", "email", "phone", "notes", "contact_id"] if is_readonly else ["contact_id"],
                    column_order=["full_name", "position", "email", "phone", "notes"]
                )
                
                # ✅ FIX 1: Кнопка формы рендерится ВСЕГДА, но отключается для user
                btn_label = "💾 Сохранить контакты" if not is_readonly else "👁 Только просмотр"
                if st.form_submit_button(btn_label, type="primary", disabled=is_readonly):
                    if not is_readonly:
                        try:
                            orig_ids = set(contacts_df["contact_id"].dropna().astype(int))
                            curr_ids = set(edited_contacts["contact_id"].dropna().astype(int))
                            deleted_ids = list(orig_ids - curr_ids)
                            
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
        
        if not is_readonly:
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
    st.markdown("### 📚 Наборы и виды сведений в проектах поставщика")
    
    supplier_datasets = query_db("""
        SELECT DISTINCT d.dataset_name AS "Набор данных", i.info_name AS "Вид сведений"
        FROM project_items pi
        JOIN projects p ON pi.project_id = p.project_id
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        WHERE p.supplier_id = :sid
        ORDER BY d.dataset_name, i.info_name
    """, {"sid": selected_sup_id})
    
    if not supplier_datasets.empty:
        st.dataframe(supplier_datasets, use_container_width=True, hide_index=True)
    else:
        st.info("📭 Для этого поставщика пока нет привязанных наборов данных в проектах.")
    
    st.markdown("---")
    
    # ==========================================
    # БЛОК 2: Все поставщики + редактор (ВНИЗУ)
    # ==========================================
    if not is_readonly:  # 🔒 Полностью скрыто для роли 'user'
        st.markdown("### 📋 Все поставщики")
        suppliers_df = query_db("SELECT * FROM suppliers ORDER BY supplier_name")

        visible_cols = [c for c in suppliers_df.columns if c != "supplier_id"]
        col_config = {c: st.column_config.TextColumn(RU_LABELS.get(c, c.replace("_", " ").capitalize()), required=True) for c in visible_cols}

        with st.form("suppliers_editor_form"):
            edited_suppliers = st.data_editor(
                suppliers_df, key="suppliers_editor", hide_index=True, use_container_width=True,
                num_rows="dynamic",
                column_config=col_config, 
                disabled=["supplier_id"],
                column_order=visible_cols
            )
            
            if st.form_submit_button("💾 Сохранить поставщиков", type="primary"):
                try:
                    orig_ids = set(suppliers_df["supplier_id"].dropna().astype(int))
                    curr_ids = set(edited_suppliers["supplier_id"].dropna().astype(int))
                    deleted_ids = list(orig_ids - curr_ids)
                    
                    if deleted_ids:
                        session.execute(text("DELETE FROM suppliers WHERE supplier_id IN :ids"), {"ids": tuple(deleted_ids)})
                    
                    for _, row in edited_suppliers.iterrows():
                        sid = row.get("supplier_id")
                        is_new = pd.isna(sid)
                        if is_new:
                            session.execute(text("INSERT INTO suppliers (supplier_name) VALUES (:name)"), {"name": row["supplier_name"]})
                        else:
                            session.execute(text("UPDATE suppliers SET supplier_name = :name WHERE supplier_id = :id"),
                                            {"name": row["supplier_name"], "id": int(sid)})
                    
                    session.commit()
                    clear_cache()
                    st.success("✅ Поставщики сохранены!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка БД: {e}")
                    session.rollback()

        with st.expander("➕ Добавить нового поставщика"):
            with st.form("add_supplier_form"):
                col1, col2 = st.columns(2)
                with col1:
                    new_sup_name = st.text_input("Наименование поставщика *")
                    new_sup_address = st.text_input("Адрес")
                    new_sup_email = st.text_input("Email")
                    new_sup_phone = st.text_input("Телефон")
                with col2:
                    new_sup_website = st.text_input("Сайт")
                    new_sup_manager = st.text_input("Руководитель / Менеджер")
                    new_sup_notes = st.text_area("Примечание", height=80)

                if st.form_submit_button("💾 Создать поставщика", type="primary"):
                    if not new_sup_name.strip():
                        st.error("❌ Наименование не может быть пустым")
                    else:
                        try:
                            session.execute(text("""
                                INSERT INTO suppliers (supplier_name, supplier_address, supplier_email,
                                                       supplier_phone, supplier_website, supplier_manager, supplier_notes)
                                VALUES (:name, :addr, :email, :phone, :web, :mgr, :notes)
                            """), {
                                "name": new_sup_name.strip(),
                                "addr": new_sup_address.strip() or None,
                                "email": new_sup_email.strip() or None,
                                "phone": new_sup_phone.strip() or None,
                                "web": new_sup_website.strip() or None,
                                "mgr": new_sup_manager.strip() or None,
                                "notes": new_sup_notes.strip() or None
                            })
                            session.commit()
                            clear_cache()
                            st.success("✅ Поставщик добавлен!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ошибка БД: {e}")
                            session.rollback()