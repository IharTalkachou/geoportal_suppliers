import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime, time
import time as time_module
import re
import folium
from streamlit_folium import st_folium

from config.cache import query_db, clear_cache
from config.auth import log_action
from utils.date_utils import add_business_days

def render_requests_tab(session, user_role="user"):
    st.subheader("📩 Управление входящими заявками")
    is_readonly = (user_role == "user")
    
    # 🟢 ОБНОВЛЕННАЯ НАВИГАЦИЯ
    choice = st.segmented_control(
        "Навигация",
        options=["➕ Новая заявка", "📋 Реестр (Регистрация)", "📦 Реестр (Предоставление)"],
        default="➕ Новая заявка",
        key="req_main_nav",
        label_visibility="collapsed"
    )
    st.markdown("---")

    if choice == "➕ Новая заявка":
        if is_readonly: 
            st.warning("Недостаточно прав."); return
            
        # 🟢 ВЫБОР ТИПА ЗАЯВКИ
        req_type = st.radio(
            "Выберите тип оформляемой заявки:",
            ["Заявка на регистрацию", "Заявка на предоставление набора"],
            horizontal=True,
            key="new_req_type_toggle"
        )
        st.markdown("---")

        if req_type == "Заявка на регистрацию":
            render_registration_form(session)
        else:
            render_provision_form(session)
            
    elif choice == "📋 Реестр (Регистрация)":
        render_requests_registry(session, user_role)
        
    elif choice == "📦 Реестр (Предоставление)":
        render_provision_registry(session, user_role)

def render_registration_form(session):
    st.markdown("### 📝 Оформление новой заявки")
    
    with st.container(border=True):
        # --- БЛОК 1: ТИП И КОНТАКТЫ ---
        col_type, col_dates = st.columns([1, 1])
        with col_type:
            app_type = st.radio("Вид заявителя", ["Физическое лицо", "Юридическое лицо"], horizontal=True, key="f_app_type")
            applicant_phone = st.text_input("📞 Контактный номер телефона *", placeholder="+375...")
        
        with col_dates:
            st.write("📅 **Дата и время поступления**")
            cd1, cd2 = st.columns(2)
            with cd1: d_in = st.date_input("Число", value=datetime.now().date(), key="req_d_widget")
            with cd2: t_in = st.time_input("Время", value=datetime.now().time(), key="req_t_widget")
            created_dt = datetime.combine(d_in, t_in)

        st.divider()

        # --- БЛОК 2: ДАННЫЕ ЗАЯВИТЕЛЯ ---
        user_list = []
        linked_supplier_id = None # Для связи с существующим поставщиком
        
        if app_type == "Физическое лицо":
            st.markdown("##### 👤 Данные физического лица")
            f_name = st.text_input("ФИО заявителя полностью *")
            f_email = st.text_input("Email для уведомлений *")
            f_login = st.text_input("Желаемый логин *")
            user_list.append({"fio": f_name, "email": f_email, "login": f_login, "is_admin": False})
            main_applicant_name = f_name
            org_target, scan_link = None, None
        
        else:
            st.markdown("##### 🏢 Данные организации")
            # 🟢 1. ТИП ОРГАНИЗАЦИИ ТЕПЕРЬ ПЕРВЫМ
            org_target = st.selectbox("Тип организации", ["Пользователь", "Поставщик"], key="f_org_type")
            
            c1, c2 = st.columns(2)
            with c1:
                # 🟢 2. ВЫБОР ИЛИ ВВОД ИМЕНИ
                if org_target == "Поставщик":
                    # Подтягиваем список существующих
                    sups_df = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
                    sup_map_local = dict(zip(sups_df["supplier_name"], sups_df["supplier_id"]))
                    selected_sup_name = st.selectbox("Выберите организацию из реестра *", sups_df["supplier_name"].tolist())
                    main_applicant_name = selected_sup_name
                    linked_supplier_id = int(sup_map_local[selected_sup_name])
                else:
                    main_applicant_name = st.text_input("Название организации *")
                    linked_supplier_id = None
            
            with c2:
                scan_link = st.text_input("🔗 Ссылка на скан заявки")
            
            num_accs = st.number_input("Количество учётных записей", min_value=1, max_value=20, value=1)
            
            st.markdown("---")
            for i in range(int(num_accs)):
                with st.expander(f"Пользователь №{i+1}", expanded=True):
                    u1, u2, u3 = st.columns(3)
                    with u1: ufio = st.text_input(f"ФИО *", key=f"ufio_{i}")
                    with u2: umail = st.text_input(f"Email *", key=f"umail_{i}")
                    with u3: ulog = st.text_input(f"Логин *", key=f"ulog_{i}")
                    user_list.append({"fio": ufio, "email": umail, "login": ulog, "is_admin": False})

            admin_fio = None
            if org_target == "Поставщик":
                st.markdown("##### 🔑 Администратор пользователей")
                valid_names = [u['fio'] for u in user_list if u['fio'].strip()]
                if valid_names:
                    admin_fio = st.selectbox("Выберите администратора", valid_names)
                    for u in user_list:
                        if u['fio'] == admin_fio: u['is_admin'] = True

        st.divider()
        if st.button("🚀 Создать заявку", type="primary", width='stretch'):
            if not main_applicant_name: st.error("Заполните имя заявителя"); st.stop()
            try:
                res = session.execute(text("""
                    INSERT INTO reg_requests (created_at, applicant_type, applicant_name, applicant_phone, scan_url, org_type, status, result_supplier_id)
                    VALUES (:ca, CAST(:at AS applicant_category), :an, :ph, :su, CAST(:ot AS org_target_type), 'Новая', :rsid) 
                    RETURNING req_id
                """), {"ca": created_dt, "at": app_type, "an": main_applicant_name, "ph": applicant_phone, "su": scan_link, "ot": org_target, "rsid": linked_supplier_id})
                new_id = res.scalar()

                for u in user_list:
                    session.execute(text("""
                        INSERT INTO reg_request_users (req_id, full_name, email, login, is_admin)
                        VALUES (:rid, :fn, :em, :lg, :adm)
                    """), {"rid": new_id, "fn": u["fio"], "em": u["email"], "lg": u["login"], "adm": u["is_admin"]})

                session.commit(); clear_cache()
                log_action(st.session_state.auth["user_id"], "CREATE_REG_REQUEST", "reg_requests", int(new_id))
                st.toast(f"Заявка №{new_id} сохранена!")
                st.success(f"🎉 Заявка №{new_id} зарегистрирована."); time_module.sleep(1); st.rerun()
            except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

def render_requests_registry(session, user_role):
    st.markdown("### 📋 Реестр заявок")
    reqs = query_db("SELECT * FROM reg_requests ORDER BY req_id DESC")
    
    if reqs.empty: 
        st.info("Заявок в базе данных пока нет.")
        return

    # Подготовка таблицы для отображения
    df_viz = reqs.copy()
    df_viz['created_at_str'] = df_viz['created_at'].dt.strftime('%d.%m.%Y %H:%M')
    
    # УМНЫЙ РАСЧЕТ ВЫСОТЫ ТАБЛИЦЫ
    # 35px на строку + 45px на заголовок. Ограничиваем от 150 до 600 пикселей.
    calc_h = (len(df_viz) * 35) + 45
    final_h = min(600, max(150, calc_h))

    # 🟢 3. РЕЕСТР В ЭКСПАНДЕРЕ
    with st.expander("🔍 Показать/скрыть таблицу реестра", expanded=False):
        st.dataframe(
            df_viz[["req_id", "created_at_str", "applicant_name", "applicant_type", "status", "org_type"]], 
            width="stretch", 
            hide_index=True,
            height=final_h, # Применяем расчетную высоту
            column_config={
                "req_id": "№", 
                "created_at_str": "Дата поступления", 
                "applicant_name": "Заявитель", 
                "applicant_type": "Категория",
                "status": "Статус", 
                "org_type": "Тип организации"
            }
        )

    st.divider()
    
    # Формируем список для выбора
    req_options = {
        f"№{r['req_id']} | {r['created_at'].strftime('%d.%m.%Y %H:%M')} | {r['applicant_name']}": r['req_id'] 
        for _, r in reqs.iterrows()
    }
    
    sel_label = st.selectbox("🎯 Выберите заявку для просмотра и обработки:", [""] + list(req_options.keys()))
    
    if sel_label:
        sel_id = req_options[sel_label]
        # Берем данные конкретной заявки
        det = reqs[reqs["req_id"] == sel_id].iloc[0]
        users = query_db("SELECT * FROM reg_request_users WHERE req_id = :id", {"id": int(sel_id)})
        
        with st.container(border=True):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"#### Заявка №{sel_id}")
                st.write(f"🚦 **Статус:** `{det['status']}`")
                st.write(f"👤 **Заявитель:** {det['applicant_name']} ({det['applicant_type']})")
                st.write(f"📞 **Телефон:** {det['applicant_phone'] or 'не указан'}")
                
                # 🟢 ИСПРАВЛЕНИЕ ОШИБКИ NaN: Проверяем наличие ID перед кнопкой перехода
                if pd.notna(det['result_supplier_id']):
                    def go_to_sup_cb(sid):
                        st.session_state["main_nav"] = "📁 Поставщики"
                        st.session_state["filter_supplier_id"] = int(sid)

                    st.button("🔎 Перейти к карточке поставщика", 
                              on_click=go_to_sup_cb, 
                              args=(det['result_supplier_id'],), 
                              type="secondary",
                              width='stretch')
            
            with c2:
                # 🟢 ИСПРАВЛЕНИЕ: Индикация скана
                if det['applicant_type'] == "Юридическое лицо":
                    if det['scan_url'] and str(det['scan_url']).strip() != "":
                        st.link_button("📄 Открыть скан заявки", det['scan_url'], width='stretch')
                    else:
                        st.warning("⚠️ Заявка не приложена (ссылка отсутствует)")
                
                # Механизм повышения для организаций-пользователей
                if det['org_type'] == "Пользователь" and pd.isna(det['result_supplier_id']):
                    st.info("💡 Эту организацию можно внести в реестр Поставщиков")
                    if st.button("🏗 Создать запись Поставщика", type="primary", width='stretch'):
                        try:
                            new_sup = session.execute(text("""
                                INSERT INTO suppliers (supplier_name, supplier_phone, supplier_notes) 
                                VALUES (:n, :p, :notes) RETURNING supplier_id
                            """), {"n": det['applicant_name'], "p": det['applicant_phone'], "notes": f"Создан на базе заявки №{sel_id}"}).scalar()
                            
                            session.execute(text("UPDATE reg_requests SET result_supplier_id = :sid WHERE req_id = :rid"),
                                            {"sid": int(new_sup), "rid": int(sel_id)})
                            
                            session.commit(); clear_cache()
                            log_action(st.session_state.auth["user_id"], "PROMOTE_REQUEST_TO_SUPPLIER", "suppliers", int(new_sup))
                            st.success("Организация добавлена в реестр!"); st.rerun()
                        except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

                # Блок завершения обработки
                if not det['processed_at'] or pd.isna(det['processed_at']):
                    st.write("🛠 **Завершение обработки**")
                    cp1, cp2 = st.columns(2)
                    with cp1: d_proc = st.date_input("Дата", value=datetime.now().date(), key=f"dp_{sel_id}")
                    with cp2: t_proc = st.time_input("Время", value=datetime.now().time(), key=f"tp_{sel_id}")
                    if st.button("✅ Завершить заявку", width='stretch', key=f"btn_finish_{sel_id}"):
                        proc_dt = datetime.combine(d_proc, t_proc)
                        session.execute(text("UPDATE reg_requests SET processed_at=:p, status='Завершена' WHERE req_id=:id"),
                                        {"p": proc_dt, "id": int(sel_id)})
                        session.commit(); clear_cache(); st.toast("Заявка завершена"); st.rerun()
                else:
                    st.success(f"✅ Обработана: {det['processed_at'].strftime('%d.%m.%Y %H:%M')}")

            st.markdown("---")
            st.write("**👤 Список пользователей по заявке:**")
            # Безопасное маскирование админа
            users_disp = users.copy()
            users_disp['is_admin'] = users_disp['is_admin'].apply(lambda x: "🔑 Да" if x else "—")
            st.table(users_disp[["full_name", "email", "login", "is_admin"]].rename(columns={"full_name": "ФИО", "is_admin": "Админ"}))

def render_provision_form(session):
    # 1. Инициализация состояния, если его нет
    if "prov_submitted" not in st.session_state:
        st.session_state.prov_submitted = False
    if "last_prov_id" not in st.session_state:
        st.session_state.last_prov_id = None

    # 2. Логика переключения экранов
    if st.session_state.prov_submitted:
        # ЭКРАН УСПЕХА
        st.success(f"🎉 Поступление заявки успешно зафиксировано!")
        st.balloons()
        
        with st.container(border=True):
            st.markdown(f"""
                ### Заявка зарегистрирована
                Системный номер в базе: **{st.session_state.last_prov_id}**
                
                Теперь вы можете найти её в разделе **"Реестр (Предоставление)"** для дальнейшей обработки.
            """)
            
            if st.button("➕ Создать еще одну заявку", type="primary", width="stretch"):
                st.session_state.prov_submitted = False
                st.session_state.last_prov_id = None
                st.rerun()
    else:
        # СТАНДАРТНЫЙ ЭКРАН ФОРМЫ
        st.markdown("### 📦 Новая заявка на предоставление набора")
        
        with st.container(border=True):
            # --- 1. ОБЩИЕ ДАННЫЕ ЗАЯВИТЕЛЯ ---
            st.markdown("##### 👤 Информация о заявителе")
            c1, c2, c3 = st.columns([1, 1, 1])
            with c1:
                app_cat = st.selectbox("Тип лица", ["Физическое лицо", "Представитель", "Гос. орган", "Иная организация"], key="prov_app_cat")
            with c2:
                app_name = st.text_input("Наименование (ФИО или Организация) *")
                contact_fio = st.text_input("Контактное лицо (ФИО) *")
            with c3:
                contact_phone = st.text_input("Телефон *")
                contact_email = st.text_input("Email *")

            c4, c5, c6 = st.columns(3)
            with c4:
                channel = st.selectbox("Канал поступления", ["Национальный геопортал", "Почта", "Личное обращение"])
            with c5:
                reg_date = st.date_input("Дата поступления", value=datetime.now().date())
            with c6:
                pref_method = st.selectbox("Способ связи", ["Email", "Почта", "Лично"])

            st.divider()

            # --- 2. ПРЕДМЕТ ЗАЯВКИ ---
            st.markdown("##### 🔍 Предмет заявки")
            req_type = st.radio("Тип запрашиваемых данных", ["НИПД", "Госкартгеофонд"], horizontal=True, key="prov_req_type")
            
            selected_nipd_id = None
            selected_gkf_ids = []
            gkf_extra_note = ""

            if req_type == "НИПД":
                dss = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
                sel_ds = st.selectbox("Выберите набор данных", [""] + dss["dataset_name"].tolist())
                if sel_ds:
                    ds_id = dss[dss["dataset_name"] == sel_ds]["dataset_id"].iloc[0]
                    infos = query_db("""
                        SELECT it.info_id, it.info_name, it.format, it.update, s.supplier_name, pi.provision_right
                        FROM info_types it
                        JOIN project_items pi ON it.info_id = pi.info_id
                        JOIN projects p ON pi.project_id = p.project_id
                        JOIN suppliers s ON p.supplier_id = s.supplier_id
                        WHERE it.dataset_id = :did
                    """, {"did": int(ds_id)})
                    sel_info = st.selectbox("Выберите вид сведений", [""] + infos["info_name"].tolist())
                    if sel_info:
                        info_row = infos[infos["info_name"] == sel_info].iloc[0]
                        selected_nipd_id = int(info_row["info_id"])
                        st.info(f"**Справочно:** Поставщик: {info_row['supplier_name']} | Формат: {info_row['format']} | Право предоставления: {info_row['provision_right']}")
            else:
                g_types = query_db("SELECT * FROM ref_gkf_types")
                sel_g_type = st.selectbox("Тип материала ГКГФ", [""] + g_types["type_name"].tolist())
                
                # Вспомогательные переменные для сохранения
                selected_gkf_ids = []
                gkf_extra_note = ""

                if sel_g_type:
                    tid = int(g_types[g_types["type_name"] == sel_g_type]["type_id"].iloc[0])
                    
                    # 1. Материалы аэрофотосъёмки (ID 1)
                    if tid == 1:
                        sub_opt = st.selectbox("Вид материалов аэрофотосъёмки", ["Аэрофотоснимки", "Ортофотопланы"])
                        # Ищем ID в базе по названию
                        mat_res = query_db("SELECT material_id FROM ref_gkf_materials WHERE material_name = :n", {"n": sub_opt})
                        if not mat_res.empty: selected_gkf_ids = [int(mat_res.iloc[0]['material_id'])]
                        
                        if sub_opt == "Ортофотопланы":
                            gkf_extra_note = st.text_area("Номенклатуры листов или наименование территории")

                    # 2. Материалы ЗИС (ID 2)
                    elif tid == 2:
                        zis_list = [
                            "Административно-территориальные единицы", "Земельные участки",
                            "Земельные участки, предоставленные гражданам", "Виды земель",
                            "Мелиоративное состояние земель", "Ограничения (обременения) прав на земельные участки",
                            "Коммуникации", "Внемасштабные объекты и символы"
                        ]
                        sel_mats = st.multiselect("Выберите слои ЗИС", zis_list)
                        if sel_mats:
                            # В данной логике ЗИС - это набор материалов. 
                            # Если их нет в ref_gkf_materials, их нужно туда добавить или хранить текстом.
                            # Пока ищем те, что есть:
                            mat_res = query_db("SELECT material_id FROM ref_gkf_materials WHERE material_name IN :l", {"l": tuple(sel_mats)})
                            if not mat_res.empty: selected_gkf_ids = mat_res['material_id'].tolist()

                    # 3. Топографические карты (ID 3)
                    elif tid == 3:
                        sub_opt = st.selectbox("Вид (Топокарты)", ["совмещённый", "контур", "гидрография", "рельеф", "растительность", "дорожная сеть, огнестойкие кварталы", "другое"])
                        gkf_extra_note = st.text_area("Номенклатуры листов или наименование территории")
                        # Для карт/планов часто ID один (общий тип), детали в ноте
                        mat_res = query_db("SELECT material_id FROM ref_gkf_materials WHERE type_id = 3 LIMIT 1")
                        if not mat_res.empty: selected_gkf_ids = [int(mat_res.iloc[0]['material_id'])]

                    # 4. Топографические планы (ID 4)
                    elif tid == 4:
                        sub_opt = st.selectbox("Вид (Топопланы)", ["совмещённый", "контур", "гидрография", "рельеф", "растительность", "дорожная сеть, огнестойкие кварталы", "другое"])
                        gkf_extra_note = st.text_input("Название топографического плана")
                        mat_res = query_db("SELECT material_id FROM ref_gkf_materials WHERE type_id = 4 LIMIT 1")
                        if not mat_res.empty: selected_gkf_ids = [int(mat_res.iloc[0]['material_id'])]

                    # 5. Тематические карты... (ID 5)
                    elif tid == 5:
                        sub_opt = st.selectbox("Вид (Тематика)", ["обзорно-топографические", "политико-административные", "дорожные", "туристические", "исторические", "экологические", "астрономические", "учебные", "другие"])
                        gkf_extra_note = st.text_input("Название тематической карты, плана, атласа")
                        mat_res = query_db("SELECT material_id FROM ref_gkf_materials WHERE type_id = 5 LIMIT 1")
                        if not mat_res.empty: selected_gkf_ids = [int(mat_res.iloc[0]['material_id'])]

                    # 6. ПВО (ID 6)
                    elif tid == 6:
                        sub_opt = st.selectbox("Вид (ПВО)", ["координаты", "отметки высот", "кроки"])
                        mat_res = query_db("SELECT material_id FROM ref_gkf_materials WHERE material_name = :n", {"n": sub_opt.capitalize()})
                        if not mat_res.empty: selected_gkf_ids = [int(mat_res.iloc[0]['material_id'])]

                    # 7. ЦМР (ID 7)
                    elif tid == 7:
                        st.info("Выбрана Цифровая модель рельефа")
                        mat_res = query_db("SELECT material_id FROM ref_gkf_materials WHERE type_id = 7 LIMIT 1")
                        if not mat_res.empty: selected_gkf_ids = [int(mat_res.iloc[0]['material_id'])]

            scan_url = st.text_input("🔗 Ссылка на скан заявки (если есть)")

            st.divider()
            
            # --- 4. СОХРАНЕНИЕ ---
            if st.button("🚀 Зарегистрировать поступление", type="primary", width='stretch'):
                if not app_name or not contact_fio:
                    st.error("Заполните обязательные поля"); st.stop()
                
                try:
                    # ВАЖНО: Переменная gkf_extra_note должна быть доступна здесь.
                    # Если это НИПД, она будет пустой.
                    final_note = gkf_extra_note if req_type == "Госкартгеофонд" else ""

                    res = session.execute(text("""
                        INSERT INTO provision_requests (
                            created_at, applicant_category, applicant_name, 
                            contact_person, phone, email, channel, preferred_contact_method, 
                            request_type, scan_url, nipd_info_id, gkf_material_ids, status_id, note
                        ) VALUES (
                            :ca, :ac, :an, :cp, :ph, :em, :ch, :pm, :rt, :su, :ni, :gi, 
                            (SELECT stage_id FROM stages WHERE stage_code = 'REQ_OPENE' LIMIT 1), :nt
                        ) RETURNING req_id
                    """), {
                        "ca": reg_date, "ac": app_cat, "an": app_name,
                        "cp": contact_fio, "ph": contact_phone, "em": contact_email,
                        "ch": channel, "pm": pref_method, "rt": req_type, "su": scan_url,
                        "ni": selected_nipd_id, "gi": selected_gkf_ids,
                        "nt": final_note  # 👈 Новая переменная здесь
                    })
                    new_req_id = res.scalar()

                    session.execute(text("""
                        INSERT INTO provision_request_history (req_id, stage_id, actual_start, comments)
                        VALUES (:rid, (SELECT stage_id FROM stages WHERE stage_code = 'REQ_OPENE' LIMIT 1), :now, 'Заявка поступила в систему')
                    """), {"rid": new_req_id, "now": datetime.now()})

                    session.commit(); clear_cache()
                    
                    st.session_state.prov_submitted = True
                    st.session_state.last_prov_id = new_req_id
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Ошибка БД: {e}"); session.rollback()

# ==========================================
# 🗺️ ГЕО-ПОМОЩНИК
# ==========================================
def parse_area_coords(raw_text):
    if not raw_text: return None
    pattern = r"(\d+\.\d+)\s*,\s*(\d+\.\d+)"
    matches = re.findall(pattern, raw_text)
    if not matches: return None
    return [[float(m[0]), float(m[1])] for m in matches]

def render_preview_map(coords):
    if not coords: return
    # Используем альтернативный сервер плиток (CartoDB), он надежнее в корп. сетях
    m = folium.Map(
        location=coords[0], 
        zoom_start=9, 
        tiles='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    )
    folium.Polygon(
        locations=coords, color="#3498DB", fill=True, fill_opacity=0.4, weight=3
    ).add_to(m)
    
    # Вместо Маркеров (иконок) используем Круги (рисуются вектором)
    for i, p in enumerate(coords):
        folium.CircleMarker(
            location=p, radius=5, color="red", fill=True, 
            popup=f"Точка {i+1}"
        ).add_to(m)
    
    st_folium(m, height=400, width='stretch', key="prov_map_render")

# ==========================================
# 📋 РЕЕСТР ЗАЯВОК НА ПРЕДОСТАВЛЕНИЕ
# ==========================================
def render_provision_registry(session, user_role):
    st.markdown("### 📦 Реестр заявок на предоставление")
    
    # 1. Загрузка расширенных данных
    reqs = query_db("""
        SELECT pr.*, s.stage_name, s.stage_code, s.stage_color,
               it.info_name, ds.dataset_name, 
               sup.supplier_name, it.format, pi.provision_right
        FROM provision_requests pr
        JOIN stages s ON pr.status_id = s.stage_id
        LEFT JOIN info_types it ON pr.nipd_info_id = it.info_id
        LEFT JOIN datasets ds ON it.dataset_id = ds.dataset_id
        LEFT JOIN project_items pi ON it.info_id = pi.info_id 
        LEFT JOIN projects p ON pi.project_id = p.project_id
        LEFT JOIN suppliers sup ON p.supplier_id = sup.supplier_id
        ORDER BY pr.req_id DESC
    """)
    
    if reqs.empty:
        st.info("Заявок пока нет."); return

    # --- СТАБИЛЬНЫЙ ВЫБОР ЧЕРЕЗ SESSION STATE ---
    if "sel_prov_id" not in st.session_state:
        st.session_state.sel_prov_id = None

    # Формируем список опций
    req_opts = {f"ID {r['req_id']} | {r['reg_number'] or 'Без №'} | {r['applicant_name']}": r['req_id'] for _, r in reqs.iterrows()}
    
    # Ищем индекс текущего выбранного ID, чтобы селектбокс не сбрасывался
    current_index = 0
    if st.session_state.sel_prov_id:
        ids_list = [r['req_id'] for _, r in reqs.iterrows()]
        if st.session_state.sel_prov_id in ids_list:
            current_index = ids_list.index(st.session_state.sel_prov_id) + 1 # +1 так как первая опция пустая

    sel_label = st.selectbox(
        "🎯 Выберите заявку для обработки:", 
        [""] + list(req_opts.keys()), 
        index=current_index,
        key="prov_reg_sel_widget"
    )

    if not sel_label:
        st.session_state.sel_prov_id = None
        return
    
    rid = req_opts[sel_label]
    st.session_state.sel_prov_id = rid # Запоминаем выбор
    det = reqs[reqs['req_id'] == rid].iloc[0]
    
    # Рассчитываем сроки от даты поступления (created_at)
    base_date = det['created_at'].date()
    deadline_val = add_business_days(base_date, 5)
    deadline_rev = add_business_days(base_date, 10)

    is_closed = det['stage_code'] in ['REQ_CLOSE', 'REQ_REGIS_RETUR', 'REQ_REFUS_RECEI']

    # 3. ДЕТАЛЬНЫЙ ПРОСМОТР
    with st.container(border=True):
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown(f"🚦 **Этап:** <span style='background-color:{det['stage_color']}; color:white; padding:2px 8px; border-radius:4px;'>{det['stage_name']}</span>", unsafe_allow_html=True)
            st.write(f"🏢 **Заявитель:** {det['applicant_name']}")
            st.write(f"📞 **Контакт:** {det['contact_person']} | {det['phone']}")
            if det['reg_number']: st.info(f"🔢 Внутренний номер: **{det['reg_number']}**")

            # 🟢 БЛОК КОНТРОЛЬНЫХ СРОКОВ (SLA)
            with st.expander("⏳ Контрольные сроки (SLA)", expanded=not is_closed):
                sc1, sc2 = st.columns(2)
                sc1.metric("Валидация (5 дн.)", deadline_val.strftime("%d.%m.%Y"))
                sc2.metric("Рассмотрение (10 дн.)", deadline_rev.strftime("%d.%m.%Y"))
                if not is_closed and datetime.now().date() > deadline_val:
                    st.error("🚨 Срок валидации превышен!")
               
        with c2:
            # 🟢 НИПД с названием набора
            data_label = f"{det['request_type']}"
            if det['request_type'] == 'НИПД' and pd.notna(det['dataset_name']):
                data_label += f" | {det['dataset_name']} ({det['info_name']})"
            st.write(f"📦 **Данные:** {data_label}")
            
            # 🟢 Справочная информация
            if det['request_type'] == 'НИПД':
                with st.expander("ℹ️ Справка по базе", expanded=True):
                    st.caption(f"**Поставщик:** {det['supplier_name'] or 'Не найден'}")
                    st.caption(f"**Формат:** {det['format'] or '—'}")
                    st.caption(f"**Право:** {det['provision_right'] or '—'}")

            if det['scan_url']: st.link_button("📄 Открыть скан", det['scan_url'], width='stretch')
            else: st.warning("⚠️ Заявка не приложена")

        # --- ГЕО-БЛОК ---
        if det['area_coords_raw']:
            with st.expander("🗺️ Геометрия запрашиваемой области", expanded=False):
                coords = parse_area_coords(det['area_coords_raw'])
                if coords: render_preview_map(coords)

        # 🟢 ЦЕНТРАЛЬНЫЙ ВЫЗОВ ДОКУМЕНТОВ
        #_render_provision_docs(session, rid, is_closed=is_closed)

        # --- 🛠️ УПРАВЛЕНИЕ ЭТАПАМИ (WORKFLOW) ---
        st.divider()
        #st.markdown("##### 🛠️ Переход на следующий этап")
        
        cur_code = det['stage_code']
        
        # Вспомогательный UI для времени (Пункт 4)
        def render_time_selector(key_prefix, rid):
            st.write("🕒 **Время совершения действия:**")
            mode = st.radio("Установить время:", ["Текущее", "Ввести вручную"], 
                            horizontal=True, key=f"tm_{key_prefix}_{rid}")
            
            if mode == "Ввести вручную":
                cc1, cc2 = st.columns(2)
                # Подставляем ТЕКУЩЕЕ время как дефолт, чтобы не начинать с 00:00
                d = cc1.date_input("Дата", value=datetime.now().date(), key=f"d_{key_prefix}_{rid}")
                t = cc2.time_input("Время", value=datetime.now().time(), key=f"t_{key_prefix}_{rid}", step=60)
                return datetime.combine(d, t)
            
            return datetime.now()

        # Кнопки переходов
        # 🟢 ЭТАП 1: ЗАЯВКА ПОСТУПИЛА
        if cur_code == 'REQ_OPENE': # ПОСТУПИЛА -> РЕГИСТРАЦИЯ
            with st.popover("✅ Зарегистрировать и присвоить номер", width='stretch'):
                target_dt = render_time_selector("reg", rid)
                _render_provision_docs(session, rid, is_closed=is_closed)

                new_no = st.text_input("Внутренний номер регистрации *")
                if st.button("Подтвердить регистрацию"):
                    if new_no: _move_to_stage(session, rid, 'REQ_REGIS_START', f"Присвоен № {new_no}", reg_no=new_no, custom_dt=target_dt)
                    else: st.error("Номер обязателен")

        # 🟢 ЭТАП 2: РЕГИСТРАЦИЯ
        elif cur_code == 'REQ_REGIS_START': # РЕГИСТРАЦИЯ -> ВАЛИДАЦИЯ
            st.info("📂 Заявка успешно зарегистрирована. Следующий шаг: проверка комплектности документов (валидация).")
            
            with st.popover("🔍 Начать проверку комплектности", width='stretch'):
                target_dt = render_time_selector("val_start", rid)
                if st.button("Начать валидацию"):
                    _move_to_stage(session, rid, 'REQ_REGIS_VALID', "Передано на проверку", custom_dt=target_dt)

        # 🟢 ЭТАП 3: ВАЛИДАЦИЯ
        elif cur_code == 'REQ_REGIS_VALID': # ВАЛИДАЦИЯ (КАРТА + РЕЗУЛЬТАТ)
            with st.container(border=True):
                st.write("📊 **Координаты из заявки:**")
                coords_input = st.text_area("Вставьте текст с координатами:", value=det['area_coords_raw'] or "", height=80, key="coords_ta")
                
                # Отрисовка по кнопке
                if st.button("🗺️ Отрисовать область на карте", width='stretch'):
                    parsed = parse_area_coords(coords_input)
                    if parsed:
                        st.session_state[f"preview_coords_{rid}"] = parsed
                    else: st.error("Формат не распознан")
                
                if f"preview_coords_{rid}" in st.session_state:
                    render_preview_map(st.session_state[f"preview_coords_{rid}"])

                st.write("---")
                _render_provision_docs(session, rid, is_closed=is_closed)

                target_dt = render_time_selector("val_end", rid)
                
                # Проверяем, ГКГФ ли это
                is_gkf = (det['request_type'] == 'Госкартгеофонд')
                
                cv1, cv2, cv3 = st.columns(3)
                with cv1:
                    if st.button("🎉 Пройдена", type="primary", width='stretch'):
                        # Для ГКГФ следующим этапом логично ставить REQ_REGIS_ENDED (Зарегистрирована)
                        _move_to_stage(session, rid, 'REQ_REGIS_ENDED', "Валидация успешна", coords_raw=coords_input, custom_dt=target_dt)
                
                with cv2:
                    # КНОПКА СКРЫВАЕТСЯ ДЛЯ ГКГФ
                    if not is_gkf:
                        if st.button("⚠️ Поставщику", width='stretch'):
                            _move_to_stage(session, rid, 'REQ_TRANS_PREPA', "Заявка перенаправляется Поставщику", coords_raw=coords_input, custom_dt=target_dt)
                    else:
                        st.info("ℹ️ ГКГФ: Поставщик не требуется (Оператор)")

                with cv3:
                    with st.popover("❌ Ошибка", use_container_width=True):
                        reason = st.text_area("Укажите причину возврата:", placeholder="Напр: некорректная доверенность...")
                        target_dt = render_time_selector("val_err", rid)
                        if st.button("Подтвердить возврат", type="primary"):
                            full_comm = f"Заявка возвращена без рассмотрения (Причина: {reason})"
                            _move_to_stage(session, rid, 'REQ_REGIS_RETUR', full_comm, coords_raw=coords_input, custom_dt=target_dt)

        # 🟢 ЭТАП 5: ЗАРЕГИСТРИРОВАНА -> ОБРАБОТКА ОПЕРАТОРОМ
        elif cur_code == 'REQ_REGIS_ENDED':
            with st.container(border=True):
                st.write("📋 Заявка готова к внутренней обработке.")
                target_dt = render_time_selector("proc_op_start", rid)
                if st.button("⚙️ Начать обработку Оператором", type="primary", width='stretch'):
                    _move_to_stage(session, rid, 'REQ_PROCE_OPERA', "Оператор приступил к подготовке договора", custom_dt=target_dt)

        # 🟢 ЭТАП 6: ПОДГОТОВКА ПЕРЕДАЧИ ПОСТАВЩИКУ
        elif cur_code == 'REQ_TRANS_PREPA':
            with st.container(border=True):
                st.info("ℹ️ На этом этапе необходимо направить уведомления Поставщику и Заявителю.")
                st.write("")
                _render_provision_docs(session, rid, is_closed=is_closed)

                target_dt = render_time_selector("trans_prep", rid)
                if st.button("📤 Подтвердить факт передачи Поставщику", type="primary", width='stretch'):
                    _move_to_stage(session, rid, 'REQ_TRANS_COMPL', "Уведомления направлены, заявка передана", custom_dt=target_dt)

        # 🟢 ЭТАП 7: ПЕРЕДАНА ПОСТАВЩИКУ
        elif cur_code == 'REQ_TRANS_COMPL':
            with st.container(border=True):
                st.write("⏳ Ожидание подтверждения начала работ от Поставщика...")
                target_dt = render_time_selector("trans_compl", rid)
                if st.button("⚙️ Поставщик приступил к обработке", type="primary", width='stretch'):
                    _move_to_stage(session, rid, 'REQ_PROCE_SUPPL', "Поставщик начал рассмотрение заявки", custom_dt=target_dt)

        # 🟢 ЭТАП 8: ОБРАБОТКА ОПЕРАТОРОМ (Аналогично 9-му этапу)
        elif cur_code == 'REQ_PROCE_OPERA':
            with st.container(border=True):
                st.write("📝 **Подготовка договора и расчет стоимости:**")
                _render_provision_docs(session, rid, is_closed=False) # Тут крепим черновик договора
                
                target_dt = render_time_selector("proc_op_end", rid)
                deadline = add_business_days(det['created_at'].date(), 10)
                st.caption(f"Срок по регламенту (10 раб. дн.): **{deadline.strftime('%d.%m.%Y')}**")

                co1, co2 = st.columns(2)
                with co1:
                    if st.button("📄 Проект договора отправлен", type="primary", width='stretch'):
                        _move_to_stage(session, rid, 'REQ_AGREE_SENT', "Проект договора направлен заявителю", custom_dt=target_dt)
                with co2:
                    with st.popover("🚫 Отказать", use_container_width=True):
                        reason = st.text_area("Обоснование отказа Оператора:", placeholder="Напр: содержит сведения о нац. безопасности...")
                        target_dt = render_time_selector("proc_op_ref", rid)
                        if st.button("Подтвердить отказ", type="primary"):
                            full_comm = f"Заявка закрыта после официального отказа Оператора ({reason})"
                            _move_to_stage(session, rid, 'REQ_REFUS_SUBMI', full_comm, custom_dt=target_dt)
        
        # 🟢 ЭТАП 9: ОБРАБОТКА ПОСТАВЩИКОМ
        elif cur_code == 'REQ_PROCE_SUPPL':
            with st.container(border=True):
                st.write("📝 **Результат рассмотрения Поставщиком:**")
                
                st.write("")
                target_dt = render_time_selector("proc_suppl", rid)
                
                deadline = add_business_days(det['created_at'].date(), 10)
                st.caption(f"Контрольный срок ответа (10 раб. дн. от подачи): **{deadline.strftime('%d.%m.%Y')}**")

                cv1, cv2 = st.columns(2)
                with cv1:
                    if st.button("📄 Проект договора готов", type="primary", width='stretch'):
                        _move_to_stage(session, rid, 'REQ_AGREE_SENT', "Поставщик подготовил проект договора", custom_dt=target_dt)
                with cv2:
                    with st.popover("🚫 Отказ Поставщика", use_container_width=True):
                        reason = st.text_area("Обоснование отказа Поставщика:", placeholder="Напр: данные не подлежат распространению...")
                        target_dt = render_time_selector("proc_sup_ref", rid)
                        if st.button("Зафиксировать отказ", type="primary"):
                            full_comm = f"Заявка закрыта после официального отказа Поставщика ({reason})"
                            _move_to_stage(session, rid, 'REQ_REFUS_SUBMI', full_comm, custom_dt=target_dt)

        # 🟢 ЭТАП 10: ОТКАЗАНО (Внедряем документы здесь)
        elif cur_code == 'REQ_REFUS_SUBMI':
            with st.container(border=True):
                st.error("🚫 Заявка отклонена на этапе рассмотрения.")
                _render_provision_docs(session, rid, is_closed=is_closed)
                st.write("")
                target_dt = render_time_selector("refus_close", rid)
                if st.button("🏁 Закрыть заявку (в архив)", type="secondary", width='stretch'):
                    _move_to_stage(session, rid, 'REQ_CLOSE', "Заявка закрыта после официального отказа", custom_dt=target_dt)

        # 🟢 ЭТАП 11: ДОГОВОР ОТПРАВЛЕН -> ОЖИДАНИЕ (ЭТАП 12)
        elif cur_code == 'REQ_AGREE_SENT':
            with st.container(border=True):
                st.write("📩 Проект договора находится у Заявителя.")
                target_dt = render_time_selector("agr_sent", rid)
                if st.button("⏳ Перейти в режим ожидания подписания", type="primary", width='stretch'):
                    _move_to_stage(session, rid, 'REQ_AGREE_WAIT', "Начат отсчет 10 дней на подписание Заявителем", custom_dt=target_dt)
        
        # 🟢 ЭТАП 12: ОЖИДАНИЕ ПОДПИСАНИЯ
        elif cur_code == 'REQ_AGREE_WAIT':
            with st.container(border=True):
                st.info("⏳ Ожидание подписанных экземпляров договора от Заявителя.")

                target_dt = render_time_selector("agree_wait", rid)
                _render_provision_docs(session, rid, is_closed=is_closed)

                c_v1, c_v2 = st.columns(2)
                with c_v1:
                    if st.button("🤝 Договор подписан", type="primary", width='stretch'):
                        _move_to_stage(session, rid, 'REQ_AGREE_CONCL', "Договор официально заключен", custom_dt=target_dt)
                with c_v2:
                    if st.button("🚫 Отказ от подписания", type="secondary", width='stretch'):
                        _move_to_stage(session, rid, 'REQ_REFUS_RECEI', "Заявитель не вернул подписанный договор", custom_dt=target_dt)

        # 🟢 ЭТАП 14: ДОГОВОР ЗАКЛЮЧЕН
        elif cur_code == 'REQ_AGREE_CONCL':
            with st.container(border=True):
                st.success("🤝 Договор заключен. Можно переходить к передаче данных.")

                target_dt = render_time_selector("exec_start", rid)
                if st.button("📦 Начать исполнение (передачу)", type="primary", width='stretch'):
                    _move_to_stage(session, rid, 'REQ_AGREE_EXECU', "Начат процесс подготовки и передачи данных", custom_dt=target_dt)

        # 🟢 ЭТАП 15: ИСПОЛНЕНИЕ ДОГОВОРА
        elif cur_code == 'REQ_AGREE_EXECU':
            with st.container(border=True):
                st.info("🛠 Процесс передачи данных по договору.")
                
                target_dt = render_time_selector("exec_end", rid)
                _render_provision_docs(session, rid, is_closed=is_closed)
                if st.button("✅ Данные переданы (Акт подписан)", type="primary", width='stretch'):
                    _move_to_stage(session, rid, 'REQ_AGREE_COMPL', "Данные переданы Заявителю, акт подписан", custom_dt=target_dt)

        # 🟢 ЭТАП 16: ИСПОЛНЕНА
        elif cur_code == 'REQ_AGREE_COMPL':
            with st.container(border=True):
                st.success("🏁 Все обязательства по заявке выполнены.")

                target_dt = render_time_selector("final_close", rid)
                if st.button("🔒 Закрыть заявку в архив", type="primary", width='stretch'):
                    _move_to_stage(session, rid, 'REQ_CLOSE', "Заявка переведена в архив", custom_dt=target_dt)

        # 🟢 ЭТАП 17 / 4 / 13: ФИНАЛЬНЫЕ СТАТУСЫ (АРХИВ)
        elif cur_code in ['REQ_CLOSE', 'REQ_REGIS_RETUR', 'REQ_REFUS_RECEI']:
            st.success("✅ Заявка находится в архиве. Все действия завершены.")
            

        # 4. ИСТОРИЯ ЭТАПОВ
        st.markdown("---")
        st.write("**🕰 История прохождения:**")
        history = query_db("""
            SELECT h.history_id, h.actual_start, s.stage_name, u.display_name, h.comments
            FROM provision_request_history h
            JOIN stages s ON h.stage_id = s.stage_id
            LEFT JOIN users u ON h.responsible_id = u.user_id
            WHERE h.req_id = :rid ORDER BY h.actual_start DESC
        """, {"rid": rid})
        
        for _, h_row in history.iterrows():
            st.caption(f"**{h_row['actual_start'].strftime('%d.%m.%Y %H:%M')}** — {h_row['stage_name']} ({h_row['display_name'] or 'Система'})")
            st.write(f"└ {h_row['comments']}")
            
            # Проверяем, были ли в этом этапе документы
            h_docs = query_db("SELECT doc_name, doc_url FROM stage_documents WHERE provision_history_id = :hid", {"hid": int(h_row['history_id'])})
            if not h_docs.empty:
                cols = st.columns(len(h_docs) if len(h_docs) < 4 else 4) # Рисуем в ряд до 4-х штук
                for i, (_, d) in enumerate(h_docs.iterrows()):
                    with cols[i % 4]:
                        st.caption(f"🔗 [{d['doc_name']}]({d['doc_url']})")

def _move_to_stage(session, req_id, stage_code, comment, reg_no=None, coords_raw=None, custom_dt=None):
    """Обновленная функция: записывает подробный комментарий в историю и уведомляет пользователя"""
    try:
        stage_res = session.execute(text("SELECT stage_id, stage_name FROM stages WHERE stage_code = :c LIMIT 1"), {"c": stage_code}).fetchone()
        new_sid = int(stage_res[0])
        new_sname = stage_res[1]
        exec_time = custom_dt if custom_dt else datetime.now()

        # 1. Обновляем статус заявки
        upd_query = "UPDATE provision_requests SET status_id = :sid"
        params = {"sid": new_sid, "rid": req_id}
        if reg_no: 
            upd_query += ", reg_number = :rn"; params["rn"] = reg_no
        if coords_raw:
            upd_query += ", area_coords_raw = :cr"; params["cr"] = coords_raw
        upd_query += " WHERE req_id = :rid"
        session.execute(text(upd_query), params)

        # 2. Закрываем прошлый этап
        session.execute(text("UPDATE provision_request_history SET actual_end = :t WHERE req_id = :rid AND actual_end IS NULL"), 
                        {"rid": req_id, "t": exec_time})

        # 3. Открываем новый этап
        session.execute(text("""
            INSERT INTO provision_request_history (req_id, stage_id, actual_start, comments, responsible_id)
            VALUES (:rid, :sid, :t, :comm, :uid)
        """), {"rid": req_id, "sid": new_sid, "t": exec_time, "comm": comment, "uid": st.session_state.auth['user_id']})

        session.commit(); clear_cache()
        
        # 🟢 Уведомление пользователя перед обновлением
        st.toast(f"✅ Статус изменен: {new_sname}", icon="🚀")
        if reg_no:
            st.toast(f"🔢 Присвоен номер: {reg_no}")
            
        time_module.sleep(0.5) # Даем время БД и кэшу синхронизироваться
        st.rerun()
        
    except Exception as e:
        st.error(f"Ошибка: {e}"); session.rollback()
    
def _render_provision_docs(session, req_id, is_closed=False):
    """Блок управления документами для заявок на предоставление"""
    # 1. Находим ID текущей (активной) записи в истории
    curr_h = query_db("SELECT history_id FROM provision_request_history WHERE req_id = :rid AND actual_end IS NULL LIMIT 1", {"rid": req_id})
    
    # Список уже прикрепленных показываем ВСЕГДА
    docs = query_db("""
        SELECT sd.* FROM stage_documents sd
        JOIN provision_request_history h ON sd.provision_history_id = h.history_id
        WHERE h.req_id = :rid
    """, {"rid": req_id})
    
    if not docs.empty:
        st.markdown("##### 📂 Документы по заявке")
        for _, d in docs.iterrows():
            d_c1, d_c2 = st.columns([0.85, 0.15])
            d_c1.link_button(f"📄 {d['doc_name']}", d['doc_url'], width='stretch')
            # Удаление разрешено, только если заявка НЕ закрыта
            if not is_closed:
                if d_c2.button("🗑", key=f"del_doc_pr_{d['doc_id']}"):
                    session.execute(text("DELETE FROM stage_documents WHERE doc_id = :id"), {"id": int(d['doc_id'])})
                    session.commit(); clear_cache(); st.rerun()
    
    # Форму добавления показываем только если НЕ закрыта и есть активный этап
    if not is_closed and not curr_h.empty:
        hid = int(curr_h.iloc[0]['history_id'])
        with st.popover("📎 Прикрепить документ", width='stretch'):
            name = st.text_input("Название", key=f"add_doc_n_{hid}")
            url = st.text_input("Ссылка", key=f"add_doc_u_{hid}")
            if st.button("Добавить", key=f"btn_add_{hid}"):
                if name and url:
                    session.execute(text("INSERT INTO stage_documents (provision_history_id, doc_name, doc_url) VALUES (:hid, :n, :u)"),
                                    {"hid": hid, "n": name, "u": url})
                    session.commit(); clear_cache(); st.rerun()