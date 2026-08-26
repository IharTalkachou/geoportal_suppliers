import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime
import time as time_module

from config.cache import query_db, clear_cache
from config.auth import log_action
from utils.date_utils import add_business_days

# ==========================================
# 📝 ФОРМА ПОДАЧИ ЗАЯВКИ
# ==========================================
def render_inclusion_form(session):
    if "incl_submitted" not in st.session_state:
        st.session_state.incl_submitted = False
    if "last_incl_id" not in st.session_state:
        st.session_state.last_incl_id = None

    if st.session_state.incl_submitted:
        st.success("🎉 Заявка о включении в НИПД успешно зафиксирована!")
        with st.container(border=True):
            st.markdown(f"""
                ### Заявка зарегистрирована
                Системный номер в базе: **{st.session_state.last_incl_id}**

                Теперь вы можете найти её в разделе **"Реестр заявок"** для дальнейшей обработки.
            """)
            if st.button("➕ Создать ещё одну заявку", type="primary", width="stretch"):
                st.session_state.incl_submitted = False
                st.session_state.last_incl_id = None
                st.rerun()
        return

    st.markdown("### 📝 Заявка о включении в Национальную инфраструктуру пространственных данных набора пространственных данных")

    with st.container(border=True):
        # --- 0. ДАТА И ВРЕМЯ ПОДАЧИ ---
        st.write("📅 **Дата и время подачи заявки**")
        cd1, cd2 = st.columns(2)
        with cd1: d_in = st.date_input("Число", value=datetime.now().date(), key="incl_d_widget")
        with cd2: t_in = st.time_input("Время", value=datetime.now().time(), key="incl_t_widget")
        submitted_dt = datetime.combine(d_in, t_in)

        st.divider()

        # --- 1. СВЕДЕНИЯ О ПОСТАВЩИКЕ (ВЛАДЕЛЬЦЕ) ---
        st.markdown("##### 👤 Сведения о поставщике (владельце) набора пространственных данных")
        sups_df = query_db("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")
        sup_map = dict(zip(sups_df["supplier_name"], sups_df["supplier_id"]))

        c_sup1, c_sup2 = st.columns([0.6, 0.4])
        with c_sup1:
            sup_mode = st.radio("Поставщик", ["Выбрать существующего", "Создать нового"], horizontal=True, key="incl_sup_mode")
        supplier_id = None
        with c_sup2:
            if sup_mode == "Выбрать существующего":
                sel_sup = st.selectbox("Поставщик *", [""] + sups_df["supplier_name"].tolist(), key="incl_sup_select")
                if sel_sup:
                    supplier_id = int(sup_map[sel_sup])
            else:
                new_sup_name = st.text_input("Наименование нового поставщика *", key="incl_new_sup_name")

        st.divider()

        # --- 2. ПРОЕКТ ---
        st.markdown("##### 📋 Проект")
        project_id = None
        if sup_mode == "Выбрать существующего" and supplier_id:
            proj_df = query_db("SELECT project_id, project_name FROM projects WHERE supplier_id = :sid ORDER BY project_id DESC", {"sid": supplier_id})
            proj_mode = st.radio("Проект", ["Выбрать существующий", "Создать новый"], horizontal=True, key="incl_proj_mode")
            if proj_mode == "Выбрать существующий" and not proj_df.empty:
                proj_map = dict(zip(proj_df["project_name"], proj_df["project_id"]))
                sel_proj = st.selectbox("Проект *", [""] + proj_df["project_name"].tolist(), key="incl_proj_select")
                if sel_proj:
                    project_id = int(proj_map[sel_proj])
            else:
                new_proj_name = st.text_input("Название нового проекта *", key="incl_new_proj_name")
        else:
            st.info("ℹ️ Проект будет создан автоматически вместе с новым поставщиком.")
            new_proj_name = st.text_input("Название нового проекта *", key="incl_new_proj_name_for_new_sup")

        st.divider()

        # --- 3. НАБОР ПРОСТРАНСТВЕННЫХ ДАННЫХ / ВИД СВЕДЕНИЙ ---
        st.markdown("##### 🗄️ Набор пространственных данных / вид сведений")
        dataset_id, info_id = None, None

        # Если выбран существующий проект — по умолчанию сужаем список до его project_items
        proj_items_df = pd.DataFrame()
        if project_id:
            proj_items_df = query_db("""
                SELECT it.info_id, it.info_name, ds.dataset_id, ds.dataset_name
                FROM project_items pi
                JOIN datasets ds ON pi.dataset_id = ds.dataset_id
                JOIN info_types it ON pi.info_id = it.info_id
                WHERE pi.project_id = :pid
                ORDER BY ds.dataset_name, it.info_name
            """, {"pid": project_id})

        if not proj_items_df.empty:
            ds_source = st.radio(
                "Источник набора/вида сведений",
                ["Из состава проекта", "Из полного справочника", "Создать новый"],
                horizontal=True, key="incl_ds_source"
            )
        else:
            ds_source = st.radio(
                "Источник набора/вида сведений",
                ["Из полного справочника", "Создать новый"],
                horizontal=True, key="incl_ds_source"
            )

        if ds_source == "Из состава проекта":
            item_opts = {f"{r['dataset_name']} — {r['info_name']}": (int(r['dataset_id']), int(r['info_id'])) for _, r in proj_items_df.iterrows()}
            sel_item = st.selectbox("Вид сведений в составе проекта *", [""] + list(item_opts.keys()), key="incl_item_select")
            if sel_item:
                dataset_id, info_id = item_opts[sel_item]

        elif ds_source == "Из полного справочника":
            dss = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
            ds_map = dict(zip(dss["dataset_name"], dss["dataset_id"]))
            c_ds1, c_ds2 = st.columns(2)
            with c_ds1:
                sel_ds = st.selectbox("Набор пространственных данных *", [""] + dss["dataset_name"].tolist(), key="incl_ds_select")
                if sel_ds:
                    dataset_id = int(ds_map[sel_ds])
            with c_ds2:
                if dataset_id:
                    infos = query_db("SELECT info_id, info_name FROM info_types WHERE dataset_id = :did ORDER BY info_name", {"did": dataset_id})
                    info_map = dict(zip(infos["info_name"], infos["info_id"]))
                    sel_info = st.selectbox("Вид сведений *", [""] + infos["info_name"].tolist(), key="incl_info_select")
                    if sel_info:
                        info_id = int(info_map[sel_info])
                else:
                    st.caption("Сначала выберите набор данных")

        else:  # Создать новый
            c_ds1, c_ds2 = st.columns(2)
            with c_ds1:
                new_ds_name = st.text_input("Название нового набора *", key="incl_new_ds_name")
            with c_ds2:
                new_info_name = st.text_input("Название нового вида сведений *", key="incl_new_info_name")

        ds_mode = "Создать новый" if ds_source == "Создать новый" else "Выбрать существующий"
        info_mode = ds_mode

        st.divider()

        # --- 4. ОБЩИЕ СВЕДЕНИЯ ОБ ИСТОЧНИКЕ И НАБОРЕ ---
        st.markdown("##### ℹ️ Общие сведения об информационном источнике и наборе пространственных данных")
        source_name = st.text_input("Название информационного источника, используемого для создания и обновления набора", key="incl_source_name")
        data_composition = st.text_area("Состав сведений, включаемых в набор (в том числе с указанием ограничительного грифа при наличии)", key="incl_data_composition")
        territory = st.text_input("Территория покрытия", key="incl_territory")

        st.divider()

        # --- 5. ВИД ДЕЙСТВИЯ И ДОСТУП ---
        c_a1, c_a2 = st.columns(2)
        with c_a1:
            action_type = st.radio("Вид действия по включению набора *", ["Первичное включение", "Обновление ранее включённого набора"], key="incl_action_type")
        with c_a2:
            access_variant = st.radio("Вариант доступа к размещаемому набору *", ["Общий публичный", "Защищённый с регистрацией пользователя"], key="incl_access_variant")

        resource_url = st.text_input("🔗 Ссылка на ресурс, содержащий включаемый набор пространственных данных и метаданные о нём", key="incl_resource_url")

        st.caption("Отправив электронную заявку на включение набора пространственных данных в Национальную инфраструктуру пространственных данных, заявитель соглашается с условием безвозмездного обеспечения пользователей сервисами поиска и доступа к метаданным о наборе пространственных данных, включённом в Национальную инфраструктуру пространственных данных.")

        st.divider()

        # --- 6. СОХРАНЕНИЕ ---
        if st.button("🚀 Зарегистрировать заявку", type="primary", width="stretch"):
            errors = []
            if sup_mode == "Выбрать существующего" and not supplier_id: errors.append("Выберите поставщика")
            if sup_mode == "Создать нового" and not st.session_state.get("incl_new_sup_name", "").strip(): errors.append("Укажите наименование нового поставщика")
            if ds_mode == "Выбрать существующий" and not dataset_id: errors.append("Выберите набор пространственных данных")
            if ds_mode == "Создать новый" and not st.session_state.get("incl_new_ds_name", "").strip(): errors.append("Укажите название нового набора")
            if info_mode == "Выбрать существующий" and not info_id: errors.append("Выберите вид сведений")
            if info_mode == "Создать новый" and not st.session_state.get("incl_new_info_name", "").strip(): errors.append("Укажите название нового вида сведений")

            if errors:
                for e in errors: st.error(e)
                st.stop()

            try:
                # 1. Поставщик (создание при необходимости)
                if sup_mode == "Создать нового":
                    supplier_id = session.execute(text("""
                        INSERT INTO suppliers (supplier_name) VALUES (:n) RETURNING supplier_id
                    """), {"n": st.session_state.incl_new_sup_name.strip()}).scalar()
                    log_action(st.session_state.auth["user_id"], "CREATE_SUPPLIER", "suppliers", int(supplier_id), new={"name": st.session_state.incl_new_sup_name.strip()})

                # 2. Проект (создание при необходимости)
                if sup_mode == "Создать нового":
                    project_id = session.execute(text("""
                        INSERT INTO projects (supplier_id, project_name, status) VALUES (:sid, :pn, 1) RETURNING project_id
                    """), {"sid": int(supplier_id), "pn": st.session_state.incl_new_proj_name_for_new_sup.strip()}).scalar()
                elif proj_mode == "Создать новый":
                    project_id = session.execute(text("""
                        INSERT INTO projects (supplier_id, project_name, status) VALUES (:sid, :pn, 1) RETURNING project_id
                    """), {"sid": int(supplier_id), "pn": st.session_state.incl_new_proj_name.strip()}).scalar()

                # 3. Набор данных (создание при необходимости)
                if ds_mode == "Создать новый":
                    dataset_id = session.execute(text("""
                        INSERT INTO datasets (dataset_name) VALUES (:n) RETURNING dataset_id
                    """), {"n": st.session_state.incl_new_ds_name.strip()}).scalar()
                    log_action(st.session_state.auth["user_id"], "CREATE_DATASET", "datasets", int(dataset_id), new={"name": st.session_state.incl_new_ds_name.strip()})

                # 4. Вид сведений (создание при необходимости)
                if info_mode == "Создать новый":
                    info_id = session.execute(text("""
                        INSERT INTO info_types (dataset_id, info_name) VALUES (:did, :n) RETURNING info_id
                    """), {"did": int(dataset_id), "n": st.session_state.incl_new_info_name.strip()}).scalar()
                    log_action(st.session_state.auth["user_id"], "CREATE_INFO_TYPE", "info_types", int(info_id), new={"name": st.session_state.incl_new_info_name.strip()})

                # 5. Заявка
                res = session.execute(text("""
                    INSERT INTO inclusion_requests (
                        created_at, supplier_id, project_id, dataset_id, info_id, source_name, data_composition,
                        territory, action_type, resource_url, access_variant, status_id
                    ) VALUES (
                        :ca, :sid, :pid, :did, :iid, :src, :comp, :terr, :act, :url, :acc,
                        (SELECT stage_id FROM stages WHERE stage_code = 'INCL_SUBMITTED' LIMIT 1)
                    ) RETURNING req_id
                """), {
                    "ca": submitted_dt, "sid": int(supplier_id), "pid": int(project_id) if project_id else None,
                    "did": int(dataset_id), "iid": int(info_id),
                    "src": source_name, "comp": data_composition, "terr": territory,
                    "act": action_type, "url": resource_url, "acc": access_variant
                })
                new_req_id = res.scalar()

                session.execute(text("""
                    INSERT INTO inclusion_request_history (req_id, stage_id, actual_start, comments, responsible_id)
                    VALUES (:rid, (SELECT stage_id FROM stages WHERE stage_code = 'INCL_SUBMITTED' LIMIT 1), :now, 'Заявка подана', :uid)
                """), {"rid": new_req_id, "now": submitted_dt, "uid": st.session_state.auth["user_id"]})

                session.commit(); clear_cache()
                log_action(st.session_state.auth["user_id"], "CREATE_INCLUSION_REQUEST", "inclusion_requests", int(new_req_id))

                st.session_state.incl_submitted = True
                st.session_state.last_incl_id = new_req_id
                st.rerun()

            except Exception as e:
                st.error(f"Ошибка БД: {e}"); session.rollback()

# ==========================================
# 📋 РЕЕСТР ЗАЯВОК О ВКЛЮЧЕНИИ
# ==========================================
def render_inclusion_registry(session, user_role):
    st.markdown("### 📋 Реестр заявок о включении в НИПД")

    reqs = query_db("""
        SELECT ir.*, s.stage_name, s.stage_code, s.stage_color,
               sup.supplier_name, ds.dataset_name, it.info_name, p.project_name
        FROM inclusion_requests ir
        LEFT JOIN stages s ON ir.status_id = s.stage_id
        LEFT JOIN suppliers sup ON ir.supplier_id = sup.supplier_id
        LEFT JOIN datasets ds ON ir.dataset_id = ds.dataset_id
        LEFT JOIN info_types it ON ir.info_id = it.info_id
        LEFT JOIN projects p ON ir.project_id = p.project_id
        ORDER BY ir.req_id DESC
    """)

    if reqs.empty:
        st.info("Заявок пока нет."); return

    if "sel_incl_id" not in st.session_state:
        st.session_state.sel_incl_id = None

    req_opts = {f"ID {r['req_id']} | {r['supplier_name']} | {r['dataset_name']} ({r['info_name']})": r['req_id'] for _, r in reqs.iterrows()}

    current_index = 0
    if st.session_state.sel_incl_id:
        ids_list = [r['req_id'] for _, r in reqs.iterrows()]
        if st.session_state.sel_incl_id in ids_list:
            current_index = ids_list.index(st.session_state.sel_incl_id) + 1

    sel_label = st.selectbox("🎯 Выберите заявку для обработки:", [""] + list(req_opts.keys()), index=current_index, key="incl_reg_sel_widget")

    if not sel_label:
        st.session_state.sel_incl_id = None
        return

    rid = req_opts[sel_label]
    st.session_state.sel_incl_id = rid
    det = reqs[reqs['req_id'] == rid].iloc[0]

    base_date = det['created_at'].date()
    deadline_review = add_business_days(base_date, 15)
    deadline_notify = add_business_days(base_date, 10)

    is_closed = det['stage_code'] == 'INCL_CLOSED'
    cur_code = det['stage_code']

    with st.container(border=True):
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown(f"🚦 **Этап:** <span style='background-color:{det['stage_color']}; color:white; padding:2px 8px; border-radius:4px;'>{det['stage_name']}</span>", unsafe_allow_html=True)
            st.write(f"🏢 **Поставщик:** {det['supplier_name']}")
            st.write(f"🗄️ **Набор:** {det['dataset_name']} ({det['info_name']})")
            st.write(f"📌 **Вид действия:** {det['action_type']}")
            st.write(f"🔐 **Доступ:** {det['access_variant']}")
            if pd.notna(det['previous_request_id']):
                st.info(f"↩️ Повторная подача после заявки №{int(det['previous_request_id'])}")

            def go_to_sup_cb(sid):
                st.session_state["main_nav"] = "📁 Поставщики"
                st.session_state["filter_supplier_id"] = int(sid)
            st.button("🔎 Перейти к карточке поставщика", on_click=go_to_sup_cb, args=(det['supplier_id'],), width='stretch')

        with c2:
            if det['territory']: st.caption(f"**Территория:** {det['territory']}")
            if det['source_name']: st.caption(f"**Источник:** {det['source_name']}")
            if det['resource_url']: st.link_button("🔗 Открыть ресурс с набором", det['resource_url'], width='stretch')

            with st.expander("⏳ Контрольные сроки (SLA)", expanded=not is_closed):
                sc1, sc2 = st.columns(2)
                sc1.metric("Рассмотрение (15 раб. дн.)", deadline_review.strftime("%d.%m.%Y"))
                sc2.metric("Уведомление (10 раб. дн.)", deadline_notify.strftime("%d.%m.%Y"))
                if cur_code == 'INCL_REVIEW' and datetime.now().date() > deadline_review:
                    st.error("🚨 Срок рассмотрения превышен!")

        st.divider()

        def render_time_selector(key_prefix, rid):
            st.write("🕒 **Время совершения действия:**")
            mode = st.radio("Установить время:", ["Текущее", "Ввести вручную"], horizontal=True, key=f"itm_{key_prefix}_{rid}")
            if mode == "Ввести вручную":
                cc1, cc2 = st.columns(2)
                d = cc1.date_input("Дата", value=datetime.now().date(), key=f"id_{key_prefix}_{rid}")
                t = cc2.time_input("Время", value=datetime.now().time(), key=f"it_{key_prefix}_{rid}", step=60)
                return datetime.combine(d, t)
            return datetime.now()

        # 🟢 ЭТАП 1: ПОДАНА -> НА РАССМОТРЕНИИ
        if cur_code == 'INCL_SUBMITTED':
            target_dt = render_time_selector("review_start", rid)
            if st.button("🔍 Начать рассмотрение", type="primary", width='stretch'):
                _move_to_stage(session, rid, 'INCL_REVIEW', "Заявка принята к рассмотрению", custom_dt=target_dt)

        # 🟢 ЭТАП 2: НА РАССМОТРЕНИИ -> ВКЛЮЧЕНА / ОТКАЗАНО
        elif cur_code == 'INCL_REVIEW':
            st.write("📊 **Результат рассмотрения заявки:**")
            target_dt = render_time_selector("review_end", rid)
            cv1, cv2 = st.columns(2)
            with cv1:
                if st.button("✅ Включить в НИПД", type="primary", width='stretch'):
                    _move_to_stage(session, rid, 'INCL_APPROVED', "Принято решение о включении набора в НИПД", custom_dt=target_dt)
            with cv2:
                with st.popover("🚫 Отказать", width='stretch'):
                    reason = st.text_area("Обоснованный вывод о несоответствии требованиям:", key=f"reason_{rid}")
                    target_dt2 = render_time_selector("reject", rid)
                    if st.button("Подтвердить отказ", type="primary", key=f"btn_reject_{rid}"):
                        if reason:
                            _move_to_stage(session, rid, 'INCL_REJECTED', f"Отказано во включении (Причина: {reason})", custom_dt=target_dt2)
                        else:
                            st.error("Укажите обоснование отказа")

        # 🟢 ЭТАП 3: ВКЛЮЧЕНА -> ПУБЛИКАЦИЯ (сразу, без доп. кнопки)
        elif cur_code == 'INCL_APPROVED':
            target_dt = render_time_selector("to_publishing", rid)
            if st.button("📦 Перейти к согласованию и публикации", type="primary", width='stretch'):
                _move_to_stage(session, rid, 'INCL_PUBLISHING', "Набор включён в НИПД, начато согласование публикации", custom_dt=target_dt)

        # 🟢 ЭТАП 4: ОТКАЗАНО -> ПОВТОРНАЯ ПОДАЧА / СПОР
        elif cur_code == 'INCL_REJECTED':
            st.error("🚫 Заявка отклонена на этапе рассмотрения.")
            cv1, cv2 = st.columns(2)
            with cv1:
                target_dt = render_time_selector("resubmit", rid)
                if st.button("🔁 Повторная подача (после доработки)", width='stretch'):
                    _resubmit_request(session, det, custom_dt=target_dt)
            with cv2:
                target_dt2 = render_time_selector("dispute", rid)
                if st.button("⚖️ Спор в Госкомимущество", width='stretch'):
                    _move_to_stage(session, rid, 'INCL_DISPUTE', "Поставщик направил письмо о несогласии с отказом в Госкомимущество", custom_dt=target_dt2)

        # 🟢 ЭТАП 5: СПОР В ГОСКОМИМУЩЕСТВО -> ВКЛЮЧЕНА / ОТКАЗАНО (повторно)
        elif cur_code == 'INCL_DISPUTE':
            st.info("⚖️ Спор рассматривается Государственным комитетом по имуществу (10 раб. дн.).")
            deadline_dispute = add_business_days(det['created_at'].date(), 10)
            st.caption(f"Контрольный срок рассмотрения спора: **{deadline_dispute.strftime('%d.%m.%Y')}**")
            target_dt = render_time_selector("dispute_end", rid)
            cv1, cv2 = st.columns(2)
            with cv1:
                if st.button("✅ Спор решён в пользу поставщика", type="primary", width='stretch'):
                    _move_to_stage(session, rid, 'INCL_APPROVED', "Госкомимущество удовлетворило спор, набор включён в НИПД", custom_dt=target_dt)
            with cv2:
                if st.button("🚫 Отказ подтверждён", width='stretch'):
                    _move_to_stage(session, rid, 'INCL_REJECTED', "Госкомимущество подтвердило отказ во включении", custom_dt=target_dt)

        # 🟢 ЭТАП 6: ПУБЛИКАЦИЯ (длится, пока идёт согласование/проект) -> ОПУБЛИКОВАНО -> ЗАКРЫТА
        elif cur_code == 'INCL_PUBLISHING':
            st.info("🛠 Идёт согласование документов и подготовка к публикации набора на Национальном геопортале.")
            if det['project_id']:
                def go_to_proj_cb(pid):
                    st.session_state["main_nav"] = "📋 Проекты"
                    st.session_state["filter_project_id"] = int(pid)
                st.button(f"🔎 Перейти к проекту «{det['project_name']}»", on_click=go_to_proj_cb, args=(det['project_id'],), width='stretch')
            else:
                st.warning("⚠️ Проект не привязан к заявке.")

            target_dt = render_time_selector("published", rid)
            if st.button("🌐 Опубликовано на Национальном геопортале", type="primary", width='stretch'):
                _publish_and_close_stage(session, rid, custom_dt=target_dt)

        # 🟢 ЭТАП 7: ЗАКРЫТА
        elif cur_code == 'INCL_CLOSED':
            st.success("✅ Заявка находится в архиве. Набор опубликован на Национальном геопортале.")
            if det['published_at'] is not None and not pd.isna(det['published_at']):
                st.caption(f"Дата публикации: {det['published_at'].strftime('%d.%m.%Y %H:%M')}")

        # 4. ИСТОРИЯ ЭТАПОВ
        st.markdown("---")
        st.write("**🕰 История прохождения:**")
        history = query_db("""
            SELECT h.actual_start, s.stage_name, u.display_name, h.comments
            FROM inclusion_request_history h
            JOIN stages s ON h.stage_id = s.stage_id
            LEFT JOIN users u ON h.responsible_id = u.user_id
            WHERE h.req_id = :rid ORDER BY h.actual_start DESC
        """, {"rid": rid})

        for _, h_row in history.iterrows():
            st.caption(f"**{h_row['actual_start'].strftime('%d.%m.%Y %H:%M')}** — {h_row['stage_name']} ({h_row['display_name'] or 'Система'})")
            st.write(f"└ {h_row['comments']}")

def _move_to_stage(session, req_id, stage_code, comment, custom_dt=None):
    """Переводит заявку о включении в НИПД на следующий этап воронки"""
    try:
        stage_res = session.execute(text("SELECT stage_id, stage_name FROM stages WHERE stage_code = :c LIMIT 1"), {"c": stage_code}).fetchone()
        new_sid = int(stage_res[0])
        new_sname = stage_res[1]
        exec_time = custom_dt if custom_dt else datetime.now()

        session.execute(text("UPDATE inclusion_requests SET status_id = :sid WHERE req_id = :rid"), {"sid": new_sid, "rid": req_id})

        session.execute(text("UPDATE inclusion_request_history SET actual_end = :t WHERE req_id = :rid AND actual_end IS NULL"),
                        {"rid": req_id, "t": exec_time})

        session.execute(text("""
            INSERT INTO inclusion_request_history (req_id, stage_id, actual_start, comments, responsible_id)
            VALUES (:rid, :sid, :t, :comm, :uid)
        """), {"rid": req_id, "sid": new_sid, "t": exec_time, "comm": comment, "uid": st.session_state.auth['user_id']})

        session.commit(); clear_cache()
        st.toast(f"✅ Статус изменён: {new_sname}", icon="🚀")
        time_module.sleep(0.5)
        st.rerun()

    except Exception as e:
        st.error(f"Ошибка: {e}"); session.rollback()

def _publish_and_close_stage(session, req_id, custom_dt=None):
    """Фиксирует дату публикации (веха) и закрывает заявку в архив"""
    try:
        exec_time = custom_dt if custom_dt else datetime.now()
        session.execute(text("UPDATE inclusion_requests SET published_at = :pt WHERE req_id = :rid"), {"pt": exec_time, "rid": req_id})
        session.commit()
        _move_to_stage(session, req_id, 'INCL_CLOSED', "Набор опубликован на Национальном геопортале, заявка закрыта", custom_dt=custom_dt)
    except Exception as e:
        st.error(f"Ошибка: {e}"); session.rollback()

def _resubmit_request(session, det, custom_dt=None):
    """Создаёт новую заявку на основе отклонённой, со ссылкой на предыдущую"""
    try:
        exec_time = custom_dt if custom_dt else datetime.now()
        res = session.execute(text("""
            INSERT INTO inclusion_requests (
                supplier_id, project_id, dataset_id, info_id, source_name, data_composition,
                territory, action_type, resource_url, access_variant, status_id, previous_request_id
            ) VALUES (
                :sid, :pid, :did, :iid, :src, :comp, :terr, :act, :url, :acc,
                (SELECT stage_id FROM stages WHERE stage_code = 'INCL_SUBMITTED' LIMIT 1), :prev
            ) RETURNING req_id
        """), {
            "sid": int(det['supplier_id']), "pid": int(det['project_id']) if pd.notna(det['project_id']) else None,
            "did": int(det['dataset_id']), "iid": int(det['info_id']),
            "src": det['source_name'], "comp": det['data_composition'], "terr": det['territory'],
            "act": det['action_type'], "url": det['resource_url'], "acc": det['access_variant'],
            "prev": int(det['req_id'])
        })
        new_req_id = res.scalar()

        session.execute(text("""
            INSERT INTO inclusion_request_history (req_id, stage_id, actual_start, comments, responsible_id)
            VALUES (:rid, (SELECT stage_id FROM stages WHERE stage_code = 'INCL_SUBMITTED' LIMIT 1), :now, :comm, :uid)
        """), {"rid": new_req_id, "now": exec_time, "comm": f"Повторная подача после доработки (предыдущая заявка №{int(det['req_id'])})", "uid": st.session_state.auth["user_id"]})

        session.commit(); clear_cache()
        log_action(st.session_state.auth["user_id"], "RESUBMIT_INCLUSION_REQUEST", "inclusion_requests", int(new_req_id))
        st.toast(f"🔁 Создана новая заявка №{new_req_id}", icon="🔁")

        st.session_state.sel_incl_id = int(new_req_id)
        time_module.sleep(0.5)
        st.rerun()

    except Exception as e:
        st.error(f"Ошибка: {e}"); session.rollback()
