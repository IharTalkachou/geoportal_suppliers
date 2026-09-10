import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache
from config.auth import log_action

# ==========================================
# 🛠️ СЕРВИСНЫЕ ФУНКЦИИ И ЛОГИКА
# ==========================================

def format_date_ru(d):
    """Красивый формат даты: 25 июня 2026"""
    if not d: return "—"
    months = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    return f"{d.day} {months[d.month-1]} {d.year}"

def _resync_buro_iterations(session, project_id):
    """Пересчет итераций на основе хронологии (только документарный трек)"""
    rows = query_db("""
        SELECT ps.stage_progress_id, ps.stage_id, ps.micro_status, ps.planned_start, ps.actual_start, ps.actual_end
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        WHERE ps.project_id = :pid AND s.track_category = '1. Документарный'
    """, {"pid": project_id})
    if rows.empty: return
    for s_id in rows['stage_id'].unique():
        sub = rows[rows['stage_id'] == s_id].copy()
        def get_sort_key(r):
            start = r['actual_start'] or r['planned_start'] or date.min
            if r['micro_status'] == 4: return (r['actual_end'] or date.max, start)
            if r['micro_status'] == 1: return (r['planned_start'] or date.min, start)
            return (start, start)
        sub['sort_key'] = sub.apply(get_sort_key, axis=1)
        sub = sub.sort_values(by='sort_key')
        for i, (_, row) in enumerate(sub.iterrows(), 1):
            session.execute(text("UPDATE project_stages SET iteration_count = :v WHERE stage_progress_id = :id"),
                            {"v": i, "id": int(row['stage_progress_id'])})

def load_project_documents(project_id):
    """Документы проекта (соглашение + протоколы) вместе с охватом.

    Пустой охват = документ покрывает весь проект (обычный случай).
    """
    docs = query_db("""
        SELECT pd.doc_id, pd.project_id, pd.doc_kind, pd.doc_number, pd.doc_url,
               pd.signed_date, pd.is_signed, pd.notes, pd.sort_order,
               pd.signed_stage_id, ps.iteration_count AS signed_iteration
        FROM project_documents pd
        LEFT JOIN project_stages ps ON pd.signed_stage_id = ps.stage_progress_id
        WHERE pd.project_id = :pid
        ORDER BY CASE WHEN pd.doc_kind = 'Соглашение' THEN 0 ELSE 1 END,
                 pd.sort_order NULLS LAST, pd.doc_id
    """, {"pid": project_id})
    return docs

def load_document_coverage(project_id):
    """Охват всех документов проекта: одна строка на связь документ-набор(-часть)."""
    return query_db("""
        SELECT pdi.link_id, pdi.doc_id, pdi.item_id, pdi.part_id,
               d.dataset_name, i.info_name, itp.part_name
        FROM project_document_items pdi
        JOIN project_documents pd ON pdi.doc_id = pd.doc_id
        JOIN project_items pi ON pdi.item_id = pi.item_id
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        LEFT JOIN info_type_parts itp ON pdi.part_id = itp.part_id
        WHERE pd.project_id = :pid
        ORDER BY d.dataset_name, i.info_name, itp.sort_order NULLS LAST
    """, {"pid": project_id})

def build_coverage_options(project_id):
    """Строит варианты охвата для мультиселекта: {подпись: (item_id, part_id)}.

    У вида сведений с частями предлагается И вариант "целиком" (part_id = None),
    И каждая часть отдельно. Раньше обычный LEFT JOIN отдавал только части, из-за
    чего существующая строка охвата с part_id IS NULL не находилась среди опций,
    не попадала в default мультиселекта и молча удалялась при следующем
    сохранении документа (охват переписывается целиком: DELETE + INSERT).
    """
    rows = query_db("""
        -- Вариант "вид сведений целиком"
        SELECT pi.item_id, d.dataset_name, i.info_name,
               NULL::int AS part_id, NULL::text AS part_name,
               0 AS ord, NULL::int AS part_ord,
               EXISTS (SELECT 1 FROM info_type_parts itp WHERE itp.info_id = pi.info_id) AS has_parts
        FROM project_items pi
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        WHERE pi.project_id = :pid

        UNION ALL

        -- Отдельные части этого вида сведений
        SELECT pi.item_id, d.dataset_name, i.info_name,
               itp.part_id, itp.part_name,
               1 AS ord, itp.sort_order AS part_ord,
               TRUE AS has_parts
        FROM project_items pi
        JOIN datasets d ON pi.dataset_id = d.dataset_id
        JOIN info_types i ON pi.info_id = i.info_id
        JOIN info_type_parts itp ON itp.info_id = pi.info_id
        WHERE pi.project_id = :pid

        ORDER BY dataset_name, info_name, ord, part_ord NULLS LAST, part_id
    """, {"pid": project_id})

    opts = {}
    for _, r in rows.iterrows():
        base = f"{r['dataset_name']} | {r['info_name']}"
        if pd.notna(r['part_id']):
            opts[f"{base} → {r['part_name']}"] = (int(r['item_id']), int(r['part_id']))
        elif bool(r['has_parts']):
            # Уточняем подпись, только когда есть с чем спутать
            opts[f"{base} (целиком)"] = (int(r['item_id']), None)
        else:
            opts[base] = (int(r['item_id']), None)
    return opts

def doc_title(kind, number):
    """Подпись документа одной строкой: «Протокол 1», «Соглашение».

    Единый формат для карточки документа, карточки этапа и видов сведений -
    чтобы название везде выглядело одинаково.
    """
    num = (str(number).strip() if number is not None and str(number).strip() else "")
    return f"{kind} {num}".strip()

def custom_badge(text, bg_color="#E0E0E0", text_color="#333", bold=True):
    fw = "700" if bold else "500"
    return (f'<span style="background-color:{bg_color};color:{text_color};padding:2px 10px;'
            f'border-radius:4px;font-size:0.75rem;font-weight:{fw};display:inline-block;'
            f'margin-right:5px;border:1px solid rgba(0,0,0,0.05);white-space:nowrap;">{text}</span>')

# ==========================================
# 💬 ДИАЛОГОВЫЕ ОКНА (CRUD)
# ==========================================

DOC_FORM_KEYS = ["doc_kind", "doc_number", "doc_url", "doc_signed", "doc_date", "doc_notes", "doc_coverage"]
STAGE_FORM_KEYS = ["d_stage", "d_ms", "d_p_start", "d_p_end", "d_comm", "d_resp",
                   "d_a_start", "d_a_end", "d_doc", "d_docs_multi"]

def clear_doc_form_state():
    """Сброс ключей формы документа. См. clear_stage_form_state."""
    for k in DOC_FORM_KEYS:
        st.session_state.pop(k, None)

def clear_stage_form_state():
    """Сброс ключей формы этапа.

    Виджеты диалога используют статичные key=, а Streamlit ИГНОРИРУЕТ value=/index=,
    если ключ уже присутствует в session_state. Ключи переживают закрытие диалога,
    поэтому чистить их нужно и при открытии формы, и сразу после сохранения/удаления -
    иначе в следующем открытом этапе подтягиваются поля предыдущего.
    """
    for k in STAGE_FORM_KEYS:
        st.session_state.pop(k, None)
    # Готовность/новая ссылка на этапе "Внесение изменений в протокол" -
    # per-документные ключи (d_ready_<doc_id>, d_newurl_<doc_id>), заранее
    # неизвестные - чистим по префиксу, иначе тянутся из ранее открытого этапа
    for k in [k for k in st.session_state if k.startswith("d_ready_") or k.startswith("d_newurl_")]:
        st.session_state.pop(k, None)

@st.dialog("Документ проекта")
def document_mgmt_dialog(session, project_id, allow_agreement, existing_data=None):
    is_edit = existing_data is not None

    kinds = ["Протокол"]
    if allow_agreement or (is_edit and existing_data['doc_kind'] == 'Соглашение'):
        kinds = ["Соглашение", "Протокол"]

    def_kind = existing_data['doc_kind'] if is_edit else kinds[0]
    c1, c2 = st.columns(2)
    c1.selectbox("Вид документа *", kinds, key="doc_kind",
                 index=kinds.index(def_kind) if def_kind in kinds else 0)
    c2.text_input("Номер / наименование", key="doc_number",
                  value=(existing_data['doc_number'] or "") if is_edit else "")

    st.text_input("🔗 Ссылка на скан", key="doc_url",
                  value=(existing_data['doc_url'] or "") if is_edit else "")

    c3, c4 = st.columns(2)
    is_signed = c3.checkbox("✅ Подписан", key="doc_signed",
                            value=bool(existing_data['is_signed']) if is_edit else False)
    # Дата подписания имеет смысл только у подписанного документа
    if not is_signed:
        st.session_state.doc_date = None
    c4.date_input("🖋 Дата подписания", key="doc_date",
                  value=existing_data['signed_date'] if is_edit else None,
                  disabled=not is_signed)

    st.text_area("Примечание", key="doc_notes",
                 value=(existing_data['notes'] or "") if is_edit else "")

    # Охват - редкий сценарий, поэтому свёрнут по умолчанию
    cov_opts = build_coverage_options(project_id)
    default_cov = []
    if is_edit:
        cov_df = load_document_coverage(project_id)
        mine = cov_df[cov_df['doc_id'] == int(existing_data['doc_id'])]
        current = {(int(r['item_id']), int(r['part_id']) if pd.notna(r['part_id']) else None)
                   for _, r in mine.iterrows()}
        default_cov = [lbl for lbl, val in cov_opts.items() if val in current]

    with st.expander("📎 Охват документа (по умолчанию — весь проект)"):
        if not cov_opts:
            st.caption("В проекте пока нет состава наборов.")
        else:
            st.caption("Оставьте пустым, если документ покрывает проект целиком. "
                       "Заполняйте, только когда виды сведений разнесены по разным протоколам.")
        st.multiselect("Покрываемые виды сведений", options=list(cov_opts.keys()),
                       default=default_cov, key="doc_coverage")

    if st.button("💾 Сохранить", type="primary", width='stretch'):
        try:
            params = {
                "pid": project_id,
                "kind": st.session_state.doc_kind,
                "num": (st.session_state.doc_number or "").strip() or None,
                "url": (st.session_state.doc_url or "").strip() or None,
                "signed": bool(st.session_state.doc_signed),
                "sdate": st.session_state.doc_date if st.session_state.doc_signed else None,
                "notes": (st.session_state.doc_notes or "").strip() or None,
            }
            if is_edit:
                params["id"] = int(existing_data['doc_id'])
                session.execute(text("""
                    UPDATE project_documents
                    SET doc_kind=:kind, doc_number=:num, doc_url=:url,
                        is_signed=:signed, signed_date=:sdate, notes=:notes
                    WHERE doc_id=:id
                """), params)
                doc_id = params["id"]
            else:
                next_order = session.execute(text(
                    "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM project_documents WHERE project_id = :pid"
                ), {"pid": project_id}).scalar()
                params["ord"] = next_order
                doc_id = session.execute(text("""
                    INSERT INTO project_documents
                        (project_id, doc_kind, doc_number, doc_url, is_signed, signed_date, notes, sort_order)
                    VALUES (:pid, :kind, :num, :url, :signed, :sdate, :notes, :ord)
                    RETURNING doc_id
                """), params).scalar()

            # Выбранный охват: (item_id, part_id)
            selected = [cov_opts[label] for label in st.session_state.doc_coverage]
            # "Целиком" уже включает все части этого вида сведений: если выбрано
            # и то и другое, строки по частям избыточны и дали бы двойное
            # покрытие в отчётах
            whole_items = {iid for iid, pid in selected if pid is None}
            selected = [(iid, pid) for iid, pid in selected
                        if pid is None or iid not in whole_items]

            # Охват переписываем целиком - проще и надёжнее вычисления дельты
            session.execute(text("DELETE FROM project_document_items WHERE doc_id = :id"), {"id": int(doc_id)})
            for item_id, part_id in selected:
                session.execute(text("""
                    INSERT INTO project_document_items (doc_id, item_id, part_id)
                    VALUES (:d, :i, :p)
                """), {"d": int(doc_id), "i": item_id, "p": part_id})

            session.commit()
            from utils.project_utils import sync_project_status
            sync_project_status(session, project_id)
            clear_cache()
            clear_doc_form_state()
            st.session_state.buro_toast = "✅ Документ сохранён"
            st.rerun()
        except Exception as e:
            st.error(f"Ошибка: {e}")
            session.rollback()

@st.dialog("Удаление документа")
def confirm_delete_document_dialog(session, doc_id, project_id):
    st.warning("Удалить этот документ? Этапы, связанные с ним, останутся, но потеряют привязку.")
    if st.button("❌ Да, удалить", type="primary", width='stretch'):
        try:
            session.execute(text("DELETE FROM project_documents WHERE doc_id = :id"), {"id": int(doc_id)})
            session.commit()
            from utils.project_utils import sync_project_status
            sync_project_status(session, project_id)
            clear_cache()
            clear_doc_form_state()
            st.rerun()
        except Exception as e:
            st.error(f"Ошибка: {e}")
            session.rollback()

def render_documents_block(session, project_id, is_agreement_project, is_readonly):
    """Блок документов проекта над колонками этапов."""
    docs = load_project_documents(project_id)
    cov_df = load_document_coverage(project_id)

    has_agreement = (not docs.empty) and (docs['doc_kind'] == 'Соглашение').any()
    allow_agreement = bool(is_agreement_project) and not has_agreement

    h1, h2 = st.columns([0.8, 0.2])
    signed_n = int(docs['is_signed'].sum()) if not docs.empty else 0
    total_n = len(docs)
    h1.markdown(f"##### 📄 Документы проекта ({signed_n}/{total_n} подписано)" if total_n
                else "##### 📄 Документы проекта")
    if not is_readonly:
        if h2.button("➕ Добавить документ", width='stretch'):
            clear_doc_form_state()
            document_mgmt_dialog(session, project_id, allow_agreement)

    if docs.empty:
        st.caption("Документы не заведены — бюрократический прогресс считается по этапам, как раньше.")
        st.divider()
        return

    cols = st.columns(min(3, len(docs)))
    for idx, (_, doc) in enumerate(docs.iterrows()):
        with cols[idx % len(cols)]:
            with st.container(border=True):
                if doc['is_signed']:
                    badge = custom_badge(f"Подписан {format_date_ru(doc['signed_date'])}", "#27AE60", "white")
                else:
                    badge = custom_badge("В работе", "#F39C12", "white")
                st.markdown(badge, unsafe_allow_html=True)

                st.markdown(f"**{doc_title(doc['doc_kind'], doc['doc_number'])}**")

                mine = cov_df[cov_df['doc_id'] == doc['doc_id']]
                if mine.empty:
                    st.caption("📦 Охват: весь проект")
                else:
                    names = [f"{r['info_name']} → {r['part_name']}" if pd.notna(r['part_name']) else r['info_name']
                             for _, r in mine.iterrows()]
                    st.caption("📦 " + "; ".join(names))

                if doc['doc_url']:
                    st.markdown(
                        f'<a href="{doc["doc_url"]}" target="_blank" style="text-decoration:none;font-size:0.8rem;">📄 Открыть скан</a>',
                        unsafe_allow_html=True)

                if doc['notes']:
                    st.caption(f"💬 {doc['notes']}")

                if not is_readonly:
                    b1, b2 = st.columns(2)
                    if b1.button("✏️", key=f"ed_doc_{doc['doc_id']}", width='stretch', help="Редактировать"):
                        clear_doc_form_state()
                        document_mgmt_dialog(session, project_id, allow_agreement, existing_data=doc)
                    if b2.button("🗑", key=f"dl_doc_{doc['doc_id']}", width='stretch', help="Удалить"):
                        confirm_delete_document_dialog(session, int(doc['doc_id']), project_id)

    st.divider()

@st.dialog("Управление этапом")
def stage_mgmt_dialog(session, project_id, stage_map, micro_map, existing_data=None):
    is_edit = existing_data is not None
    st_names, ms_names = list(stage_map.keys()), list(micro_map.keys())

    # ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ (Фикс конфликта Session State)
    if "d_p_start" not in st.session_state:
        st.session_state.d_p_start = existing_data['planned_start'] if is_edit else date.today()
    
    if "d_p_end" not in st.session_state:
        if is_edit:
            st.session_state.d_p_end = existing_data['planned_end']
        else:
            dur = stage_map[st_names[0]]['duration']
            st.session_state.d_p_end = st.session_state.d_p_start + timedelta(days=dur)
    
    staff_df = query_db("SELECT user_id, display_name FROM users WHERE show_in_staff=True AND is_active=True ORDER BY display_name")
    staff_map = dict(zip(staff_df["display_name"], staff_df["user_id"]))
    staff_options = ["Не назначен"] + list(staff_map.keys())

    col1, col2 = st.columns(2)
    with col1:
        def on_p_start_change():
            dur = stage_map.get(st.session_state.d_stage, {}).get("duration", 0)
            st.session_state.d_p_end = st.session_state.d_p_start + timedelta(days=dur)
        def_resp = existing_data['responsible_name'] if (is_edit and existing_data.get('responsible_name')) else "Не назначен"
        st.selectbox("Этап *", st_names, key="d_stage", index=st_names.index(existing_data['stage_name']) if is_edit else 0, on_change=on_p_start_change)
        st.selectbox("Статус", ms_names, key="d_ms", index=ms_names.index(existing_data['micro_status_name']) if is_edit else 0)
        st.selectbox("👤 Ответственный", staff_options, key="d_resp", index=staff_options.index(def_resp) if def_resp in staff_options else 0)
    with col2:
        st.date_input("🗓️ План. начало", key="d_p_start", on_change=on_p_start_change)
        st.date_input("🎯 Дедлайн", key="d_p_end")
    
    st.divider()
    c3, c4 = st.columns(2)
    is_not_started = micro_map[st.session_state.d_ms] in (1, 5)  # Планируется / Отложено
    if is_not_started:
        st.session_state.d_a_start = None
        st.session_state.d_a_end = None
    c3.date_input("🚀 Факт. начало", key="d_a_start", value=existing_data['actual_start'] if is_edit else None, disabled=is_not_started)
    c4.date_input("🏁 Факт. конец", key="d_a_end", value=existing_data['actual_end'] if is_edit else None, disabled=is_not_started)
    st.text_area("Комментарий", value=existing_data['comments'] if is_edit else "", key="d_comm")

    # Привязка этапа подписания к документам проекта. На одном этапе может быть
    # подписано сразу несколько документов (соглашение + протокол, либо несколько
    # протоколов), поэтому выбор множественный. Документы заводятся и правятся
    # прямо здесь - отдельно ходить в блок «Документы проекта» не требуется.
    signed_doc_ids = []
    cur_code = stage_map.get(st.session_state.d_stage, {}).get("code")
    is_signing_stage = cur_code == 'CONTRACT_SIGNED'
    # Этап "Согласование протокола" - работа над документом ДО подписания:
    # соглашение может быть уже подписано, пока протоколы ещё согласовываются
    is_drafting_stage = cur_code == 'PROTOCOL_NEGOTIATIONS'
    # Этап "Внесение изменений в протокол" - работа над УЖЕ подписанным
    # документом; при закрытии он считается перезаключённым в новой редакции
    is_changes_stage = cur_code == 'CHANGES_PROTOCOL'

    if is_signing_stage or is_drafting_stage or is_changes_stage:
        st.divider()
        if is_signing_stage:
            st.markdown("**📄 Подписываемые документы**")
        elif is_changes_stage:
            st.markdown("**📄 Изменяемые документы**")
        else:
            st.markdown("**📄 Согласуемые документы**")

        all_pdocs = load_project_documents(project_id)
        pdocs = all_pdocs
        if is_changes_stage:
            # Только подписанные ПРОТОКОЛЫ со сканом: название этапа предполагает
            # изменения именно в протокол (не в соглашение), а без скана менять
            # нечего - как в реальности, так и по логике данных
            pdocs = all_pdocs[(all_pdocs['doc_kind'] == 'Протокол') &
                              (all_pdocs['is_signed'] == True) &
                              all_pdocs['doc_url'].notna() &
                              (all_pdocs['doc_url'].astype(str).str.strip() != "")]

        # Охват документов - показываем прямо в подписи, чтобы было видно,
        # какие виды сведений (или их части) затрагивает каждый документ
        cov_by_doc = {}
        _cov = load_document_coverage(project_id)
        if not _cov.empty:
            for did, grp in _cov.groupby('doc_id'):
                names = [f"{r['info_name']} → {r['part_name']}" if pd.notna(r['part_name']) else r['info_name']
                         for _, r in grp.iterrows()]
                cov_by_doc[int(did)] = "; ".join(names)

        cur_ids = []
        cur_ready_state = {}
        if is_edit:
            if is_signing_stage:
                cur_ids = [int(x) for x in query_db(
                    "SELECT doc_id FROM project_documents WHERE signed_stage_id = :sid",
                    {"sid": int(existing_data['stage_progress_id'])}
                )['doc_id'].tolist()]
            else:
                # Работа над документом - связь многие-ко-многим: один документ
                # проходит несколько итераций этапа, каждая со своей строкой
                _cs = query_db("""
                    SELECT doc_id, is_ready, new_url FROM project_document_stages
                    WHERE stage_progress_id = :sid
                """, {"sid": int(existing_data['stage_progress_id'])})
                cur_ids = [int(x) for x in _cs['doc_id'].tolist()]
                for _, r in _cs.iterrows():
                    cur_ready_state[int(r['doc_id'])] = (bool(r['is_ready']), r['new_url'] or "")

        if pdocs.empty:
            if is_changes_stage:
                st.warning("⚠️ Нет подписанных протоколов со сканом — вносить изменения не во что.")
            else:
                st.caption("В проекте пока нет документов — добавьте ниже.")
        else:
            doc_opts = {}
            for _, d in pdocs.iterrows():
                mark = "✅" if d['is_signed'] else "⏳"
                label = f"{mark} {doc_title(d['doc_kind'], d['doc_number'])}"
                # Охват документа: он же определяет, какие виды сведений
                # затрагивает работа по этому протоколу
                cov = cov_by_doc.get(int(d['doc_id']))
                if cov:
                    label += f" — {cov}"
                doc_opts[label] = int(d['doc_id'])

            if is_signing_stage:
                ms_label = "Какие документы подписаны на этом этапе"
                ms_help = "Можно отметить сразу несколько. При статусе «Выполнено» они будут помечены подписанными."
            elif is_changes_stage:
                ms_label = "В какие протоколы вносятся изменения"
                ms_help = "Можно отметить сразу несколько — готовность и новая ссылка указываются для каждого отдельно."
            else:
                ms_label = "Над какими документами идёт работа"
                ms_help = "Виды сведений берутся из охвата документа — задаются в его карточке в разделе «Документы»."

            st.multiselect(
                ms_label,
                options=list(doc_opts.keys()),
                default=[l for l, v in doc_opts.items() if v in cur_ids],
                key="d_docs_multi",
                help=ms_help
            )
            signed_doc_ids = [doc_opts[l] for l in st.session_state.get("d_docs_multi", [])]

            if is_changes_stage and signed_doc_ids:
                st.caption("Готовность и новая ссылка — отдельно для каждого протокола:")
                for did in signed_doc_ids:
                    d_row = pdocs[pdocs['doc_id'] == did].iloc[0]
                    dname = doc_title(d_row['doc_kind'], d_row['doc_number'])
                    default_ready, default_url = cur_ready_state.get(did, (False, ""))
                    with st.container(border=True):
                        rc1, rc2 = st.columns([0.4, 0.6])
                        is_ready = rc1.checkbox("✅ Готов", key=f"d_ready_{did}", value=default_ready)
                        rc1.caption(dname)
                        if is_ready:
                            rc2.text_input("🔗 Новая ссылка на изменённый протокол",
                                          key=f"d_newurl_{did}", value=default_url)
                        else:
                            rc2.caption("Протокол ещё дорабатывается")

        # Заведение/правка документов, не выходя из формы этапа. Для этапа
        # изменений не нужно: там работают только с уже выбранными выше
        # протоколами, отдельный перечень всех документов проекта ни к чему
        if not is_changes_stage:
            with st.expander("➕ Добавить / ✏️ изменить документ"):
                # Соглашение допустимо только в проекте с соответствующим признаком
                # и только одно (частичный уникальный индекс idx_pdocs_one_agreement)
                is_agreement_project = bool(query_db(
                    "SELECT is_agreement_project FROM projects WHERE project_id = :pid",
                    {"pid": project_id}
                ).iloc[0]['is_agreement_project'])
                kinds = ["Протокол"]
                has_agreement = (not all_pdocs.empty) and (all_pdocs['doc_kind'] == 'Соглашение').any()
                if is_agreement_project and not has_agreement:
                    kinds = ["Соглашение", "Протокол"]

                ic1, ic2 = st.columns(2)
                new_kind = ic1.selectbox("Вид", kinds, key="d_inline_kind")
                new_num = ic2.text_input("Номер / наименование", key="d_inline_num")
                new_url = st.text_input("🔗 Ссылка на скан", key="d_inline_url")
                if st.button("Добавить документ", key="d_inline_add", width='stretch'):
                    if not new_num.strip():
                        st.warning("Укажите номер или наименование документа")
                    else:
                        try:
                            nxt = session.execute(text(
                                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM project_documents WHERE project_id = :pid"
                            ), {"pid": project_id}).scalar()
                            session.execute(text("""
                                INSERT INTO project_documents (project_id, doc_kind, doc_number, doc_url, sort_order)
                                VALUES (:pid, :k, :n, :u, :o)
                            """), {"pid": project_id, "k": new_kind, "n": new_num.strip(),
                                   "u": new_url.strip() or None, "o": nxt})
                            session.commit(); clear_cache()
                            for k in ["d_inline_kind", "d_inline_num", "d_inline_url"]:
                                st.session_state.pop(k, None)
                            clear_doc_form_state()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}"); session.rollback()

                if not all_pdocs.empty:
                    st.divider()
                    for _, d in all_pdocs.iterrows():
                        ec1, ec2, ec3 = st.columns([0.5, 0.35, 0.15])
                        ec1.caption(f"{d['doc_kind']}: {d['doc_number'] or '—'}")
                        upd_url = ec2.text_input("URL", value=d['doc_url'] or "",
                                                 key=f"d_inline_url_{d['doc_id']}",
                                                 label_visibility="collapsed", placeholder="ссылка на скан")
                        if ec3.button("💾", key=f"d_inline_save_{d['doc_id']}", help="Сохранить ссылку"):
                            try:
                                session.execute(text("UPDATE project_documents SET doc_url = :u WHERE doc_id = :id"),
                                                {"u": upd_url.strip() or None, "id": int(d['doc_id'])})
                                session.commit(); clear_cache(); st.rerun()
                            except Exception as e:
                                st.error(f"Ошибка: {e}"); session.rollback()


    # Протокол переговоров - веха этапа "Переговоры": дата + скан.
    # Это ДРУГАЯ сущность, нежели протокол передачи данных: он не покрывает
    # виды сведений и не участвует в расчёте прогресса, поэтому живёт
    # в stage_documents, а не в project_documents.
    is_nego_stage = stage_map.get(st.session_state.d_stage, {}).get("code") == 'NEGOTIATIONS'
    if is_nego_stage:
        st.divider()
        if not is_edit:
            st.caption("📑 Протокол переговоров можно приложить после сохранения этапа.")
        else:
            nego_ps_id = int(existing_data['stage_progress_id'])
            nego_docs = query_db("""
                SELECT doc_id, doc_name, doc_url, doc_date
                FROM stage_documents
                WHERE project_stage_id = :id AND is_nego_protocol
                ORDER BY doc_date NULLS LAST, doc_id
            """, {"id": nego_ps_id})

            has_proto = st.checkbox("📑 Есть протокол переговоров", key="d_has_proto",
                                    value=not nego_docs.empty)
            if has_proto:
                for _, d in nego_docs.iterrows():
                    pc1, pc2 = st.columns([0.85, 0.15])
                    dt = f" от {d['doc_date'].strftime('%d.%m.%Y')}" if pd.notna(d['doc_date']) else ""
                    if d['doc_url']:
                        pc1.markdown(f'<a href="{d["doc_url"]}" target="_blank" '
                                     f'style="text-decoration:none;">📑 {d["doc_name"]}{dt}</a>',
                                     unsafe_allow_html=True)
                    else:
                        pc1.caption(f"📑 {d['doc_name']}{dt} (без скана)")
                    if pc2.button("🗑", key=f"del_nego_{d['doc_id']}", help="Удалить протокол"):
                        session.execute(text("DELETE FROM stage_documents WHERE doc_id = :id"),
                                        {"id": int(d['doc_id'])})
                        session.commit(); clear_cache(); st.rerun()

                with st.popover("➕ Добавить протокол переговоров", width='stretch'):
                    np1, np2 = st.columns(2)
                    np_name = np1.text_input("Номер / наименование", key="d_nego_name")
                    np_date = np2.date_input("Дата протокола", key="d_nego_date", value=None)
                    np_url = st.text_input("🔗 Ссылка на скан", key="d_nego_url")
                    if st.button("Сохранить протокол", key="d_nego_save"):
                        if not np_name.strip():
                            st.warning("Укажите номер или наименование протокола")
                        else:
                            try:
                                session.execute(text("""
                                    INSERT INTO stage_documents
                                        (project_stage_id, doc_name, doc_url, doc_date, is_nego_protocol)
                                    VALUES (:id, :n, :u, :d, TRUE)
                                """), {"id": nego_ps_id, "n": np_name.strip(),
                                       "u": np_url.strip() or None, "d": np_date})
                                session.commit(); clear_cache()
                                for k in ["d_nego_name", "d_nego_date", "d_nego_url"]:
                                    st.session_state.pop(k, None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Ошибка: {e}"); session.rollback()

    if is_edit:
        st.caption("📂 Документы")
        # 1. Загрузка существующих
        # Используем int() для ID, так как pandas может вернуть numpy.int64
        curr_ps_id = int(existing_data['stage_progress_id'])
        # Протоколы переговоров показываются в своём блоке выше - здесь только
        # обычные вложения, иначе один документ дублировался бы в двух местах
        docs = query_db("""
            SELECT * FROM stage_documents
            WHERE project_stage_id = :id AND COALESCE(is_nego_protocol, FALSE) = FALSE
        """, {"id": curr_ps_id})
        
        for _, d in docs.iterrows():
            dc1, dc2 = st.columns([0.85, 0.15])
            dc1.caption(f"📄 {d['doc_name']}")
            # Удаление
            if dc2.button("🗑", key=f"del_doc_buro_{d['doc_id']}"):
                session.execute(text("DELETE FROM stage_documents WHERE doc_id = :id"), {"id": int(d['doc_id'])})
                session.commit()
                clear_cache()
                st.rerun()
        
        # 2. Добавление нового
        with st.popover("📎 Добавить документ", width='stretch'):
            new_n = st.text_input("Название (напр. Письмо №...)")
            new_u = st.text_input("URL-ссылка")
            if st.button("Сохранить ссылку", key="btn_save_new_doc_buro"):
                if new_n and new_u:
                    try:
                        session.execute(text("""
                            INSERT INTO stage_documents (project_stage_id, doc_name, doc_url) 
                            VALUES (:id, :n, :u)
                        """), {"id": curr_ps_id, "n": new_n, "u": new_u})
                        session.commit()
                        clear_cache()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {e}")
                else:
                    st.warning("Заполните поля")

    if st.button("💾 Сохранить", type="primary", width='stretch'):
        try:
            r_id = staff_map.get(st.session_state.d_resp) if st.session_state.d_resp != "Не назначен" else None
            params = {
                "pid": project_id, "sid": stage_map[st.session_state.d_stage]["id"],
                "mst": micro_map[st.session_state.d_ms], "ps": st.session_state.d_p_start,
                "pe": st.session_state.d_p_end, "as": st.session_state.d_a_start,
                "ae": st.session_state.d_a_end, "comm": st.session_state.d_comm,
                "rid": r_id
            }
            if is_edit:
                params["id"] = int(existing_data['stage_progress_id'])
                session.execute(text("UPDATE project_stages SET stage_id=:sid, micro_status=:mst, planned_start=:ps, planned_end=:pe, actual_start=:as, actual_end=:ae, comments=:comm, responsible_id=:rid WHERE stage_progress_id=:id"), params)
                ps_id = params["id"]
            else:
                ps_id = session.execute(text("INSERT INTO project_stages (project_id, stage_id, micro_status, iteration_count, planned_start, planned_end, actual_start, actual_end, comments, responsible_id) VALUES (:pid, :sid, :mst, 1, :ps, :pe, :as, :ae, :comm, :rid) RETURNING stage_progress_id"), params).scalar()

            if is_signing_stage:
                is_done = micro_map[st.session_state.d_ms] == 4
                # Снимаем привязку с документов, откреплённых от этапа в этой правке
                session.execute(text("""
                    UPDATE project_documents
                    SET signed_stage_id = NULL, is_signed = false, signed_date = NULL
                    WHERE signed_stage_id = :sid
                """), {"sid": int(ps_id)})
                # Проставляем текущий набор; подписанными помечаем только на закрытом этапе
                for did in signed_doc_ids:
                    session.execute(text("""
                        UPDATE project_documents
                        SET signed_stage_id = :sid,
                            is_signed = :done,
                            signed_date = CASE WHEN :done THEN COALESCE(:ae, signed_date) ELSE NULL END
                        WHERE doc_id = :did
                    """), {"sid": int(ps_id), "done": is_done,
                           "ae": st.session_state.d_a_end, "did": did})
            elif is_drafting_stage:
                # Работа над документом до подписания: связь многие-ко-многим,
                # правим только строки ЭТОЙ итерации этапа - привязки к другим
                # итерациям того же документа остаются нетронутыми
                session.execute(text("""
                    DELETE FROM project_document_stages WHERE stage_progress_id = :sid
                """), {"sid": int(ps_id)})
                for did in signed_doc_ids:
                    session.execute(text("""
                        INSERT INTO project_document_stages (doc_id, stage_progress_id)
                        VALUES (:did, :sid)
                        ON CONFLICT (doc_id, stage_progress_id) DO NOTHING
                    """), {"did": did, "sid": int(ps_id)})
            elif is_changes_stage:
                # Готовность и новая ссылка - индивидуально для КАЖДОГО выбранного
                # протокола, а не для этапа целиком: один этап может вести
                # изменение нескольких протоколов с разной готовностью.
                # Как только протокол отмечен готовым - он считается перезаключённым
                # в новой редакции немедленно, без ожидания закрытия всего этапа.
                per_doc = []
                for did in signed_doc_ids:
                    ready = bool(st.session_state.get(f"d_ready_{did}", False))
                    new_url_val = (st.session_state.get(f"d_newurl_{did}", "") or "").strip() or None
                    if ready and not new_url_val:
                        d_row = pdocs[pdocs['doc_id'] == did].iloc[0]
                        dname = doc_title(d_row['doc_kind'], d_row['doc_number'])
                        raise ValueError(f"Укажите новую ссылку для готового протокола «{dname}»")
                    per_doc.append((did, ready, new_url_val))

                session.execute(text("""
                    DELETE FROM project_document_stages WHERE stage_progress_id = :sid
                """), {"sid": int(ps_id)})
                for did, ready, new_url_val in per_doc:
                    session.execute(text("""
                        INSERT INTO project_document_stages (doc_id, stage_progress_id, is_ready, new_url)
                        VALUES (:did, :sid, :ready, :url)
                    """), {"did": did, "sid": int(ps_id), "ready": ready, "url": new_url_val})
                    if ready:
                        session.execute(text("""
                            UPDATE project_documents
                            SET doc_url = :url, signed_date = COALESCE(:ae, CURRENT_DATE)
                            WHERE doc_id = :did
                        """), {"url": new_url_val, "ae": st.session_state.d_a_end, "did": did})

            session.commit(); _resync_buro_iterations(session, project_id); session.commit()
            from utils.project_utils import sync_project_status
            sync_project_status(session, project_id)
            clear_cache()
            clear_stage_form_state()
            st.session_state.buro_toast = "✅ Изменения сохранены"; st.rerun()
        except Exception as e: st.error(f"Ошибка: {e}"); session.rollback()

@st.dialog("Удаление")
def confirm_delete_dialog(session, stage_id, project_id):
    st.warning("Удалить этот этап?")
    if st.button("❌ Да, удалить", type="primary", width='stretch'):
        session.execute(text("DELETE FROM project_stages WHERE stage_progress_id = :id"), {"id": stage_id})
        session.commit(); _resync_buro_iterations(session, project_id); session.commit()
        from utils.project_utils import sync_project_status
        sync_project_status(session, project_id)
        clear_cache(); clear_stage_form_state(); st.rerun()

# ==========================================
# 📊 ОСНОВНОЙ ЭКРАН
# ==========================================

def render_bureaucracy_tab(session, project_id, user_role="user"):
    is_readonly = (user_role == "user")
    
    # 1. Справочники
    s_ref = query_db("SELECT stage_id, stage_name, duration_days, stage_code FROM stages WHERE track_category = '1. Документарный' ORDER BY stage_order")
    m_ref = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses")
    stage_map = {r['stage_name']: {"id": int(r['stage_id']), "duration": int(r['duration_days'] or 0),
                                   "code": r['stage_code']} for _, r in s_ref.iterrows()}
    micro_map = {r['micro_status_name']: int(r['micro_status_id']) for _, r in m_ref.iterrows()}

    is_agreement_project = bool(query_db(
        "SELECT is_agreement_project FROM projects WHERE project_id = :pid", {"pid": project_id}
    ).iloc[0]['is_agreement_project'])

    # 2. Данные
    df = query_db("""
        SELECT ps.*, s.stage_name, s.stage_order, s.stage_code, ms.micro_status_name, u.display_name as responsible_name
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        LEFT JOIN users u ON ps.responsible_id = u.user_id
        WHERE ps.project_id = :pid 
          AND s.track_category = '1. Документарный'  -- 👈 ВОТ ЭТОТ ФИЛЬТР УБЕРЕТ ТЕХНОЛОГИЮ
        ORDER BY 
            CASE WHEN ps.micro_status = 4 THEN 1 ELSE 0 END ASC, 
            COALESCE(ps.actual_end, ps.actual_start, ps.planned_start) DESC,
            s.stage_order DESC -- 👈 ТЕПЕРЬ ПРИ РАВНЫХ ДАТАХ ПОБЕДИТ ТОТ, КТО ПОСЛЕДНИЙ В СПИСКЕ ЭТАПОВ
    """, {"pid": project_id})

    if "buro_toast" in st.session_state:
        st.toast(st.session_state.buro_toast); del st.session_state.buro_toast

    h_col1, h_col2 = st.columns([0.8, 0.2])
    h_col1.subheader("📜 Бюрократический трек")
    if not is_readonly:
        if h_col2.button("➕ Добавить этап", width='stretch', type="primary"):
            clear_stage_form_state()
            stage_mgmt_dialog(session, project_id, stage_map, micro_map)

    view_mode = st.radio("Вид отображения", ["🗂 Карточки", "📋 Таблица"],
                         key=f"buro_view_{project_id}", horizontal=True,
                         label_visibility="collapsed")
    if view_mode == "📋 Таблица":
        from ui.shared_components import render_stages_table
        render_stages_table(df)
        return

    # Распределение
    work_df = df[df['micro_status'].isin([2, 3, 6])]
    plan_df = df[df['micro_status'].isin([1, 5])]
    done_df = df[df['micro_status'] == 4]

    c_work, c_plan, c_done = st.columns(3)

    with c_work:
        st.markdown("##### ⚡ В работе / Ожидание")
        for _, row in work_df.iterrows():
            render_stage_card(session, row, project_id, stage_map, micro_map, is_readonly)

    with c_plan:
        st.markdown("##### 🗓️ Плановые")
        for _, row in plan_df.iterrows():
            render_stage_card(session, row, project_id, stage_map, micro_map, is_readonly)

    with c_done:
        st.markdown("##### ✅ Выполнено")
        for _, row in done_df.iterrows():
            render_stage_card(session, row, project_id, stage_map, micro_map, is_readonly)

def render_stage_card(session, row, project_id, stage_map, micro_map, is_readonly):
    """Универсальный отрисовщик карточек по типам статусов"""
    ms = row['micro_status']
    is_overdue = (ms == 6)
    
    # Определение просрочки для выполненных
    was_late = False
    if ms == 4 and row['actual_end'] and row['planned_end']:
        if row['actual_end'] > row['planned_end']: was_late = True

    # 1. Цветовая схема
    colors = {4: "#27AE60", 6: "#E74C3C", 2: "#3498DB", 1: "#95A5A6", 3: "#F39C12", 5: "#7F8C8D"}
    main_color = colors.get(ms, "#BDC3C7")
    bg_color = "#FFF9F9" if is_overdue else "#FFFFFF"
    border_style = f"2px solid {main_color}" if is_overdue else "1px solid #E0E0E0"

    card_key = f"card_{row['stage_progress_id']}"
    if is_overdue:
        st.markdown(f'<style>div[data-testid="stVerticalBlockBorderWrapper"]:has(>.st-key-{card_key}) {{ border: {border_style} !important; background-color: {bg_color} !important; }}</style>', unsafe_allow_html=True)

    with st.container(border=True, key=card_key):
        # СТРОКА 1: Статус и даты
        if ms == 4: # Выполнено
            bolt = " ⚡" if was_late else ""
            txt = f"{row['micro_status_name']} {format_date_ru(row['actual_end'])}{bolt}"
            st.markdown(custom_badge(txt, main_color, "white"), unsafe_allow_html=True)
        
        elif ms == 1: # Планируется
            txt = f"Планируется с {format_date_ru(row['planned_start'])} по {format_date_ru(row['planned_end'])}"
            st.markdown(custom_badge(txt, main_color, "white"), unsafe_allow_html=True)
        
        elif ms == 5: # Отложено
            txt = f"Отложено с {format_date_ru(row['planned_start'])}"
            st.markdown(custom_badge(txt, main_color, "white"), unsafe_allow_html=True)
        
        else: # В работе / Ожидание / Просрочено
            start_txt = f"с {format_date_ru(row['actual_start'] or row['planned_start'])}"
            if is_overdue:
                txt = f"ПРОСРОЧЕНО! Дедлайн {format_date_ru(row['planned_end'])}"
            else:
                txt = f"{row['micro_status_name']} {start_txt}"
            st.markdown(custom_badge(txt, main_color, "white"), unsafe_allow_html=True)

        # СТРОКА 2: Комментарий (Защищенный b-тег для обхода проблем разметки)
        comm_text = row['comments'] or "—"
        st.markdown(f'<div style="margin: 8px 0; font-size: 0.95rem;"><b>💬 {comm_text}</b></div>', unsafe_allow_html=True)

        # СТРОКА 3: Этап + Итерация и Исполнитель
        b_stage = custom_badge(f"{row['stage_name']} (ит. {int(row['iteration_count'])})", "#F4ECF7", "#6C3483")
        b_resp = custom_badge(row['responsible_name'] or "Не назначен", "#FEF9E7", "#9A7D0A")
        st.markdown(f"<div>{b_stage}{b_resp}</div>", unsafe_allow_html=True)

        # СТРОКА 3а: Документы, подписанные на этом этапе (со ссылкой на скан)
        signed = query_db("""
            SELECT pd.doc_kind, pd.doc_number, pd.doc_url,
                   (pd.signed_stage_id = :id) AS is_signed_here,
                   COALESCE(pds.is_ready, FALSE) AS is_ready
            FROM project_documents pd
            LEFT JOIN project_document_stages pds
                   ON pds.doc_id = pd.doc_id AND pds.stage_progress_id = :id
            WHERE pd.signed_stage_id = :id
               OR EXISTS (SELECT 1 FROM project_document_stages pds2
                           WHERE pds2.doc_id = pd.doc_id AND pds2.stage_progress_id = :id)
            ORDER BY CASE WHEN pd.doc_kind = 'Соглашение' THEN 0 ELSE 1 END,
                     pd.sort_order NULLS LAST, pd.doc_id
        """, {"id": int(row['stage_progress_id'])})
        if not signed.empty:
            def _doc_chip(label, url):
                if url:
                    return (f'<a href="{url}" target="_blank" '
                           f'style="text-decoration:none;font-size:0.8rem;">📑 {label}</a>')
                return f'<span style="font-size:0.8rem;">📑 {label}</span>'

            is_changes_row = row.get('stage_code') == 'CHANGES_PROTOCOL'
            parts = []
            for _, d in signed.iterrows():
                base = doc_title(d['doc_kind'], d['doc_number'])
                if d['is_signed_here']:
                    parts.append(_doc_chip(base, d['doc_url']))
                elif is_changes_row:
                    if d['is_ready']:
                        # Готов - ссылка уже обновлена на новую редакцию
                        parts.append(_doc_chip(f"{base} (готов, с изменениями)", d['doc_url']))
                    else:
                        # Пока не готов - ссылки ещё нет смысла показывать,
                        # старый скан больше не актуален
                        parts.append(f'<span style="font-size:0.8rem;">📑 {base} (изменяется)</span>')
                else:
                    parts.append(_doc_chip(f"{base} (в работе)", d['doc_url']))
            st.markdown('<div style="margin-top:8px;">' + " · ".join(parts) + '</div>',
                        unsafe_allow_html=True)

        # СТРОКА 4: Файлы
        docs = query_db("""
            SELECT doc_name, doc_url, doc_date, COALESCE(is_nego_protocol, FALSE) AS is_nego
            FROM stage_documents WHERE project_stage_id = :id
            ORDER BY is_nego DESC, doc_date NULLS LAST, doc_id
        """, {"id": int(row['stage_progress_id'])})
        if not docs.empty:
            links = []
            for _, d in docs.iterrows():
                # Протокол переговоров - веха этапа, показываем с датой и своей иконкой
                icon = "📑" if d['is_nego'] else "📄"
                dt = f" от {d['doc_date'].strftime('%d.%m.%Y')}" if pd.notna(d['doc_date']) else ""
                label = f"{icon} {d['doc_name']}{dt}"
                if d['doc_url']:
                    links.append(f'<a href="{d["doc_url"]}" target="_blank" '
                                 f'style="text-decoration:none; font-size:0.8rem;">{label}</a>')
                else:
                    links.append(f'<span style="font-size:0.8rem;">{label}</span>')
            st.markdown('<div style="margin-top:8px;">' + " ".join(links) + '</div>', unsafe_allow_html=True)

        # СТРОКА 5: Действия
        if not is_readonly:
            st.write("")
            with st.popover("⚙️ Действия"):
                if st.button("✏️ Редактировать", key=f"ed_{row['stage_progress_id']}", width='stretch'):
                    clear_stage_form_state()
                    stage_mgmt_dialog(session, project_id, stage_map, micro_map, existing_data=row)
                if st.button("🗑 Удалить", key=f"dl_{row['stage_progress_id']}", width='stretch'):
                    confirm_delete_dialog(session, int(row['stage_progress_id']), project_id)