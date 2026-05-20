import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db
from config.auth import log_action

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
    # БЛОК 1: Карточка + контакты выбранного поставщика (Форменный CRUD)
    # ==========================================
    if selected_sup_id:
        sup_data = query_db("SELECT * FROM suppliers WHERE supplier_id = :sid", {"sid": selected_sup_id}).iloc[0]
        
        st.markdown(f"### 🏢 {sup_data['supplier_name']}")
        for col in sup_data.index:
            if col in ["supplier_id", "supplier_name"]: continue
            if pd.notna(sup_data[col]):
                label = col.replace("_", " ").capitalize()
                st.metric(f"📌 {label}", sup_data[col])
        
        # 🔹 КОНТАКТЫ: Форменный CRUD
        st.markdown("#### 📇 Контакты")
        contacts_df = query_db("""
            SELECT c.contact_id, c.full_name, c.position, c.email, c.phone, c.notes
            FROM contacts c WHERE c.supplier_id = :sid ORDER BY c.full_name
        """, {"sid": selected_sup_id})
        
        if not contacts_df.empty:
            st.dataframe(contacts_df[["full_name", "position", "email", "phone", "notes"]], 
                         use_container_width=True, hide_index=True,
                         column_config={"full_name": "ФИО / Контакт", "position": "Должность", 
                                       "email": "Email", "phone": "Телефон", "notes": "Примечание"})
        else:
            st.info("📭 У этого поставщика пока нет контактов.")
        
        if not is_readonly:
            with st.expander("➕ Добавить / ✏️ Редактировать контакт", expanded=True):
                # 1. Выбор контакта для редактирования
                contact_options = ["(Новый контакт)"] + (contacts_df["full_name"].tolist() if not contacts_df.empty else [])
                sel_contact = st.selectbox("Выберите контакт:", contact_options, key="cont_sel")
                is_editing = sel_contact != "(Новый контакт)"

                # 🔑 Авто-подстановка ТОЛЬКО при смене выбора
                if "cont_sel_prev" not in st.session_state or st.session_state["cont_sel_prev"] != sel_contact:
                    if is_editing:
                        curr = contacts_df[contacts_df["full_name"] == sel_contact].iloc[0]
                        st.session_state["cont_fn_in"] = curr["full_name"]
                        st.session_state["cont_pos_in"] = curr["position"] or ""
                        st.session_state["cont_em_in"] = curr["email"] or ""
                        st.session_state["cont_ph_in"] = curr["phone"] or ""
                        st.session_state["cont_nt_in"] = curr["notes"] or ""
                    else:
                        st.session_state["cont_fn_in"] = ""
                        st.session_state["cont_pos_in"] = ""
                        st.session_state["cont_em_in"] = ""
                        st.session_state["cont_ph_in"] = ""
                        st.session_state["cont_nt_in"] = ""
                    st.session_state["cont_sel_prev"] = sel_contact

                # 2. Поля формы
                col1, col2 = st.columns(2)
                with col1:
                    st.text_input("ФИО / Контакт *", value=st.session_state.get("cont_fn_in", ""), key="cont_fn_in")
                    st.text_input("Должность", value=st.session_state.get("cont_pos_in", ""), key="cont_pos_in")
                with col2:
                    st.text_input("Email", value=st.session_state.get("cont_em_in", ""), key="cont_em_in")
                    st.text_input("Телефон", value=st.session_state.get("cont_ph_in", ""), key="cont_ph_in")
                st.text_area("Примечание", value=st.session_state.get("cont_nt_in", ""), height=60, key="cont_nt_in")

                # 3. Кнопки действий
                col_btn, col_del = st.columns([3, 1])
                with col_btn:
                    if st.button("💾 Сохранить контакт", type="primary", key="cont_save"):
                        fn = st.session_state["cont_fn_in"].strip()
                        if not fn:
                            st.error("❌ Имя контакта не может быть пустым")
                            st.stop()
                        try:
                            if is_editing:
                                curr = contacts_df[contacts_df["full_name"] == sel_contact].iloc[0]
                                cid = int(curr["contact_id"])
                                # 📝 Лог изменения
                                log_action(st.session_state["auth"]["user_id"], "UPDATE_CONTACT", "contacts", cid,
                                           old={"full_name": curr["full_name"], "position": curr["position"]},
                                           new={"full_name": fn, "position": st.session_state["cont_pos_in"].strip()})
                                session.execute(text("""
                                    UPDATE contacts SET full_name=:name, position=:pos, email=:em, phone=:ph, notes=:nt
                                    WHERE contact_id=:id
                                """), {
                                    "name": fn, "pos": st.session_state["cont_pos_in"].strip() or None,
                                    "em": st.session_state["cont_em_in"].strip() or None,
                                    "ph": st.session_state["cont_ph_in"].strip() or None,
                                    "nt": st.session_state["cont_nt_in"].strip() or None,
                                    "id": cid
                                })
                            else:
                                session.execute(text("""
                                    INSERT INTO contacts (full_name, supplier_id, position, email, phone, notes)
                                    VALUES (:name, :sid, :pos, :em, :ph, :nt)
                                """), {
                                    "name": fn, "sid": selected_sup_id,
                                    "pos": st.session_state["cont_pos_in"].strip() or None,
                                    "em": st.session_state["cont_em_in"].strip() or None,
                                    "ph": st.session_state["cont_ph_in"].strip() or None,
                                    "nt": st.session_state["cont_nt_in"].strip() or None
                                })
                                # 📝 Лог создания
                                new_id = session.execute(text("SELECT currval(pg_get_serial_sequence('contacts', 'contact_id'))")).scalar()
                                log_action(st.session_state["auth"]["user_id"], "CREATE_CONTACT", "contacts", int(new_id),
                                           new={"full_name": fn, "position": st.session_state["cont_pos_in"].strip()})

                            session.commit()
                            st.cache_data.clear()
                            st.success("✅ Контакт сохранён!"); st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ошибка БД: {e}"); session.rollback()

                with col_del:
                    if is_editing and st.button("🗑 Удалить", type="secondary", key="cont_del"):
                        try:
                            curr = contacts_df[contacts_df["full_name"] == sel_contact].iloc[0]
                            cid = int(curr["contact_id"])
                            # 📝 Лог удаления
                            log_action(st.session_state["auth"]["user_id"], "DELETE_CONTACT", "contacts", cid,
                                       old={"full_name": curr["full_name"], "position": curr["position"]})
                            session.execute(text("DELETE FROM contacts WHERE contact_id = :id"), {"id": cid})
                            session.commit()
                            st.cache_data.clear()
                            st.success("🗑 Контакт удалён"); st.rerun()
                        except Exception as e:
                            st.error(f"❌ Ошибка: {e}"); session.rollback()

    
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
    # БЛОК 2: Все поставщики (Форменный CRUD)
    # ==========================================
    if not is_readonly:
        st.markdown("### 📋 Все поставщики")
        suppliers_df = query_db("SELECT * FROM suppliers ORDER BY supplier_name")
        st.dataframe(suppliers_df[["supplier_name", "supplier_address", "supplier_email", "supplier_phone", 
                                   "supplier_website", "supplier_manager", "supplier_notes"]], 
                     use_container_width=True, hide_index=True,
                     column_config={c: st.column_config.TextColumn(RU_LABELS.get(c, c.replace("_", " ").capitalize())) 
                                   for c in ["supplier_name", "supplier_address", "supplier_email", "supplier_phone", 
                                            "supplier_website", "supplier_manager", "supplier_notes"]})

        with st.expander("➕ Добавить / ✏️ Редактировать поставщика", expanded=True):
            # 1. Выбор поставщика для редактирования
            sup_options = ["(Новый поставщик)"] + suppliers_df["supplier_name"].tolist()
            sel_sup = st.selectbox("Выберите поставщика:", sup_options, key="sup_edit_sel")
            is_editing = sel_sup != "(Новый поставщик)"

            # 🔑 Авто-подстановка ТОЛЬКО при смене выбора
            if "sup_edit_sel_prev" not in st.session_state or st.session_state["sup_edit_sel_prev"] != sel_sup:
                if is_editing:
                    curr = suppliers_df[suppliers_df["supplier_name"] == sel_sup].iloc[0]
                    for col in suppliers_df.columns:
                        if col != "supplier_id":
                            st.session_state[f"sup_{col}_in"] = curr[col] if pd.notna(curr[col]) else ""
                else:
                    for col in suppliers_df.columns:
                        if col != "supplier_id":
                            st.session_state[f"sup_{col}_in"] = ""
                st.session_state["sup_edit_sel_prev"] = sel_sup

            # 2. Поля формы (2 колонки)
            col1, col2 = st.columns(2)
            with col1:
                st.text_input("Наименование *", value=st.session_state.get("sup_supplier_name_in", ""), key="sup_supplier_name_in")
                st.text_input("Адрес", value=st.session_state.get("sup_supplier_address_in", ""), key="sup_supplier_address_in")
                st.text_input("Email", value=st.session_state.get("sup_supplier_email_in", ""), key="sup_supplier_email_in")
                st.text_input("Телефон", value=st.session_state.get("sup_supplier_phone_in", ""), key="sup_supplier_phone_in")
            with col2:
                st.text_input("Сайт", value=st.session_state.get("sup_supplier_website_in", ""), key="sup_supplier_website_in")
                st.text_input("Руководитель / Менеджер", value=st.session_state.get("sup_supplier_manager_in", ""), key="sup_supplier_manager_in")
                st.text_area("Примечание", value=st.session_state.get("sup_supplier_notes_in", ""), height=80, key="sup_supplier_notes_in")

            # 3. Кнопки действий
            col_btn, col_del = st.columns([3, 1])
            with col_btn:
                if st.button("💾 Сохранить поставщика", type="primary", key="sup_save"):
                    name = st.session_state["sup_supplier_name_in"].strip()
                    if not name:
                        st.error("❌ Наименование не может быть пустым")
                        st.stop()
                    try:
                        if is_editing:
                            curr = suppliers_df[suppliers_df["supplier_name"] == sel_sup].iloc[0]
                            sid = int(curr["supplier_id"])
                            # 📝 Лог изменения
                            log_action(st.session_state["auth"]["user_id"], "UPDATE_SUPPLIER", "suppliers", sid,
                                       old={"name": curr["supplier_name"], "address": curr["supplier_address"]},
                                       new={"name": name, "address": st.session_state["sup_supplier_address_in"].strip()})
                            session.execute(text("""
                                UPDATE suppliers SET supplier_name=:name, supplier_address=:addr, supplier_email=:email,
                                supplier_phone=:phone, supplier_website=:web, supplier_manager=:mgr, supplier_notes=:notes
                                WHERE supplier_id=:id
                            """), {
                                "name": name, "addr": st.session_state["sup_supplier_address_in"].strip() or None,
                                "email": st.session_state["sup_supplier_email_in"].strip() or None,
                                "phone": st.session_state["sup_supplier_phone_in"].strip() or None,
                                "web": st.session_state["sup_supplier_website_in"].strip() or None,
                                "mgr": st.session_state["sup_supplier_manager_in"].strip() or None,
                                "notes": st.session_state["sup_supplier_notes_in"].strip() or None,
                                "id": sid
                            })
                        else:
                            session.execute(text("""
                                INSERT INTO suppliers (supplier_name, supplier_address, supplier_email,
                                                    supplier_phone, supplier_website, supplier_manager, supplier_notes)
                                VALUES (:name, :addr, :email, :phone, :web, :mgr, :notes)
                            """), {
                                "name": name, "addr": st.session_state["sup_supplier_address_in"].strip() or None,
                                "email": st.session_state["sup_supplier_email_in"].strip() or None,
                                "phone": st.session_state["sup_supplier_phone_in"].strip() or None,
                                "web": st.session_state["sup_supplier_website_in"].strip() or None,
                                "mgr": st.session_state["sup_supplier_manager_in"].strip() or None,
                                "notes": st.session_state["sup_supplier_notes_in"].strip() or None
                            })
                            # 📝 Лог создания
                            new_id = session.execute(text("SELECT currval(pg_get_serial_sequence('suppliers', 'supplier_id'))")).scalar()
                            log_action(st.session_state["auth"]["user_id"], "CREATE_SUPPLIER", "suppliers", int(new_id),
                                       new={"name": name, "contact": st.session_state["sup_supplier_manager_in"].strip()})

                        session.commit()
                        st.cache_data.clear()
                        st.success("✅ Поставщик сохранён!"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Ошибка БД: {e}"); session.rollback()

            with col_del:
                if is_editing and sel_sup != "Национальный геопортал" and st.button("🗑 Удалить", type="secondary", key="sup_del"):
                    try:
                        curr = suppliers_df[suppliers_df["supplier_name"] == sel_sup].iloc[0]
                        sid = int(curr["supplier_id"])
                        # 📝 Лог удаления
                        log_action(st.session_state["auth"]["user_id"], "DELETE_SUPPLIER", "suppliers", sid,
                                   old={"name": curr["supplier_name"], "address": curr["supplier_address"]})
                        session.execute(text("DELETE FROM suppliers WHERE supplier_id = :id"), {"id": sid})
                        session.commit()
                        st.cache_data.clear()
                        st.success("🗑 Поставщик удалён"); st.rerun()
                    except Exception as e:
                        st.error(f"❌ Ошибка: {e}"); session.rollback()
                elif is_editing and sel_sup == "Национальный геопортал":
                    st.info("🔒 Системного поставщика нельзя удалить.")