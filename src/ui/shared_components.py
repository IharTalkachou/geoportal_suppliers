import streamlit as st
import pandas as pd
import plotly.graph_objects as go
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

def render_project_documents(project_id, compact=False):
    """Все ссылки на документы проекта в одном месте (общий компонент).

    Объединяет два источника:
      - project_documents - соглашение и протоколы проекта;
      - stage_documents   - файлы, приложенные к этапам обоих треков.
    Вызывается из паспорта проекта и из карточки поставщика.
    """
    docs = query_db("""
        SELECT pd.doc_kind AS title,
               COALESCE(pd.doc_number, pd.doc_kind) AS doc_name,
               pd.doc_url,
               pd.signed_date AS doc_date,
               pd.is_signed,
               -- Вид сведений (или его часть), к которому относится протокол.
               -- Пустой охват означает "весь проект", поэтому подставляется его
               -- состав. У соглашения охват не показывается - оно в проекте одно.
               CASE WHEN pd.doc_kind = 'Соглашение' THEN NULL ELSE COALESCE(
                   (SELECT string_agg(
                               CASE WHEN itp.part_name IS NOT NULL
                                    THEN i.info_name || ' → ' || itp.part_name
                                    ELSE i.info_name END, '; '
                               ORDER BY i.info_name, itp.sort_order NULLS LAST)
                      FROM project_document_items pdi
                      JOIN project_items pi ON pdi.item_id = pi.item_id
                      JOIN info_types i ON pi.info_id = i.info_id
                      LEFT JOIN info_type_parts itp ON pdi.part_id = itp.part_id
                     WHERE pdi.doc_id = pd.doc_id),
                   (SELECT string_agg(DISTINCT i.info_name, '; ')
                      FROM project_items pi
                      JOIN info_types i ON pi.info_id = i.info_id
                     WHERE pi.project_id = pd.project_id)
               ) END AS coverage
        FROM project_documents pd
        WHERE pd.project_id = :pid AND pd.doc_url IS NOT NULL AND pd.doc_url <> ''
        -- Порядок по номеру документа - как в реестре соглашений: номер хранится
        -- текстом, поэтому числовая часть извлекается отдельно, иначе "10"
        -- встало бы перед "8"
        ORDER BY CASE WHEN pd.doc_kind = 'Соглашение' THEN 0 ELSE 1 END,
                 NULLIF(regexp_replace(COALESCE(pd.doc_number, ''), '\D', '', 'g'), '')::bigint
                     NULLS LAST,
                 pd.doc_number, pd.doc_id
    """, {"pid": project_id})

    stage_docs = query_db("""
        SELECT s.stage_name AS title,
               sd.doc_name,
               sd.doc_url,
               ps.actual_end AS doc_date,
               ps.iteration_count,
               s.track_category
        FROM stage_documents sd
        JOIN project_stages ps ON sd.project_stage_id = ps.stage_progress_id
        JOIN stages s ON ps.stage_id = s.stage_id
        WHERE ps.project_id = :pid
        ORDER BY s.track_category, s.stage_order, ps.iteration_count
    """, {"pid": project_id})

    if docs.empty and stage_docs.empty:
        if not compact:
            st.caption("📂 Документы по проекту пока не загружены.")
        return

    st.markdown("##### 📂 Документы проекта" if not compact else "**📂 Документы**")

    def _link(url, name):
        return (f'<a href="{url}" target="_blank" style="text-decoration:none;">📄 {name}</a>')

    if not docs.empty:
        for _, d in docs.iterrows():
            mark = "✅" if d['is_signed'] else "⏳"
            date_txt = f" от {d['doc_date'].strftime('%d.%m.%Y')}" if pd.notna(d['doc_date']) else ""
            cov_txt = (f" — {d['coverage']}"
                       if pd.notna(d.get('coverage')) and str(d['coverage']).strip() else "")
            st.markdown(f"{mark} **{d['title']}**{date_txt} — {_link(d['doc_url'], d['doc_name'])}{cov_txt}",
                        unsafe_allow_html=True)

    if not stage_docs.empty:
        for track, group in stage_docs.groupby('track_category', sort=True):
            st.caption(track)
            for _, d in group.iterrows():
                it = f" (ит. {int(d['iteration_count'])})" if pd.notna(d['iteration_count']) else ""
                st.markdown(f"• {d['title']}{it} — {_link(d['doc_url'], d['doc_name'])}",
                            unsafe_allow_html=True)

def render_supplier_documents(supplier_id):
    """Все документы поставщика по всем его проектам (общий компонент).

    Тот же принцип, что и render_project_documents, но срез по поставщику:
    соглашение и протоколы из project_documents плюс файлы этапов из
    stage_documents, сгруппированные по проектам.
    """
    docs = query_db("""
        SELECT p.project_name,
               pd.doc_kind AS title,
               COALESCE(pd.doc_number, pd.doc_kind) AS doc_name,
               pd.doc_url,
               pd.signed_date AS doc_date,
               pd.is_signed,
               -- Вид сведений (или его часть), к которому относится протокол.
               -- Пустой охват означает "весь проект", поэтому подставляется его
               -- состав. У соглашения охват не показывается - оно у поставщика одно.
               CASE WHEN pd.doc_kind = 'Соглашение' THEN NULL ELSE COALESCE(
                   (SELECT string_agg(
                               CASE WHEN itp.part_name IS NOT NULL
                                    THEN i.info_name || ' → ' || itp.part_name
                                    ELSE i.info_name END, '; '
                               ORDER BY i.info_name, itp.sort_order NULLS LAST)
                      FROM project_document_items pdi
                      JOIN project_items pi ON pdi.item_id = pi.item_id
                      JOIN info_types i ON pi.info_id = i.info_id
                      LEFT JOIN info_type_parts itp ON pdi.part_id = itp.part_id
                     WHERE pdi.doc_id = pd.doc_id),
                   (SELECT string_agg(DISTINCT i.info_name, '; ')
                      FROM project_items pi
                      JOIN info_types i ON pi.info_id = i.info_id
                     WHERE pi.project_id = pd.project_id)
               ) END AS coverage
        FROM project_documents pd
        JOIN projects p ON pd.project_id = p.project_id
        WHERE p.supplier_id = :sid AND pd.doc_url IS NOT NULL AND pd.doc_url <> ''
        -- Порядок по номеру документа - тот же, что в реестре соглашений:
        -- номер хранится текстом, поэтому числовая часть извлекается отдельно,
        -- иначе "10" встало бы перед "8"
        ORDER BY p.project_name,
                 CASE WHEN pd.doc_kind = 'Соглашение' THEN 0 ELSE 1 END,
                 NULLIF(regexp_replace(COALESCE(pd.doc_number, ''), '\D', '', 'g'), '')::bigint
                     NULLS LAST,
                 pd.doc_number, pd.doc_id
    """, {"sid": supplier_id})

    stage_docs = query_db("""
        SELECT p.project_name,
               s.stage_name AS title,
               sd.doc_name,
               sd.doc_url,
               ps.iteration_count,
               s.track_category
        FROM stage_documents sd
        JOIN project_stages ps ON sd.project_stage_id = ps.stage_progress_id
        JOIN projects p ON ps.project_id = p.project_id
        JOIN stages s ON ps.stage_id = s.stage_id
        WHERE p.supplier_id = :sid
        ORDER BY p.project_name, s.track_category, s.stage_order, ps.iteration_count
    """, {"sid": supplier_id})

    st.markdown("##### 📂 Документы поставщика")
    if docs.empty and stage_docs.empty:
        st.caption("Документы по проектам поставщика пока не загружены.")
        return

    def _link(url, name):
        return f'<a href="{url}" target="_blank" style="text-decoration:none;">📄 {name}</a>'

    # Проекты в порядке появления; внутри - сначала соглашения/протоколы, затем файлы этапов
    projects = list(dict.fromkeys(
        docs['project_name'].tolist() + stage_docs['project_name'].tolist()
    ))

    for proj in projects:
        with st.expander(f"📁 {proj}", expanded=len(projects) == 1):
            mine = docs[docs['project_name'] == proj] if not docs.empty else docs
            for _, d in mine.iterrows():
                mark = "✅" if d['is_signed'] else "⏳"
                date_txt = f" от {d['doc_date'].strftime('%d.%m.%Y')}" if pd.notna(d['doc_date']) else ""
                cov_txt = (f" — {d['coverage']}"
                           if pd.notna(d.get('coverage')) and str(d['coverage']).strip() else "")
                st.markdown(f"{mark} **{d['title']}**{date_txt} — {_link(d['doc_url'], d['doc_name'])}{cov_txt}",
                            unsafe_allow_html=True)

            mine_st = stage_docs[stage_docs['project_name'] == proj] if not stage_docs.empty else stage_docs
            for track, group in mine_st.groupby('track_category', sort=True):
                st.caption(track)
                for _, d in group.iterrows():
                    it = f" (ит. {int(d['iteration_count'])})" if pd.notna(d['iteration_count']) else ""
                    st.markdown(f"• {d['title']}{it} — {_link(d['doc_url'], d['doc_name'])}",
                                unsafe_allow_html=True)

# Колонки, которые можно править прямо в таблице. Всё остальное - только чтение:
# название этапа и номер итерации задают идентичность записи (их правка тянет за
# собой пересчёт итераций), а охват видов сведений хранится как массив объектов
# affected_item_ids - из текста ячейки его не собрать. Для этого есть форма этапа.
_EDITABLE_COLS = ["Статус", "Исполнитель", "План. начало", "Дедлайн",
                  "Факт. начало", "Факт. конец", "Комментарий"]

# Статусы, при которых фактические даты не имеют смысла: "Планируется" и "Отложено".
# Форма этапа их для этих статусов принудительно обнуляет и блокирует - здесь
# повторяем ту же проверку, иначе таблица стала бы обходным путём мимо неё.
_NO_ACTUAL_STATUSES = {1, 5}


def render_stages_table(df, extra_col=None, session=None, project_id=None,
                        is_readonly=True, resync_fn=None, track_key="buro"):
    """Табличный вид этапов, общий для обоих треков.

    Порядок строк тот же, что и в карточках: сначала незакрытые, внутри - по дате
    от свежих к старым (сортировка приходит из SQL вызывающей вкладки).
    extra_col - опциональная пара (заголовок, имя колонки в df) для трек-специфичных
    данных: в технологическом треке это охват видов сведений.

    Если переданы session/project_id и не is_readonly, таблица становится
    редактируемой: правка безопасных полей (_EDITABLE_COLS) и удаление строк с
    подтверждением. resync_fn - пересчёт итераций своего трека
    (_resync_buro_iterations / _resync_tech_iterations), вызывается после записи.
    """
    if df.empty:
        st.info("Этапы не заведены.")
        return

    editable = (session is not None and project_id is not None and not is_readonly
                and resync_fn is not None)

    def _d(v):
        return v.strftime('%d.%m.%Y') if pd.notna(v) else "—"

    # В режиме редактирования даты остаются датами (иначе их нечем править),
    # в режиме просмотра форматируются в строки - как было раньше
    def _date_cell(v):
        if editable:
            return pd.to_datetime(v).date() if pd.notna(v) else None
        return _d(v)

    rows = []
    for _, r in df.iterrows():
        row = {
            "Этап": r['stage_name'],
            "Ит.": int(r['iteration_count']) if pd.notna(r['iteration_count']) else None,
            "Статус": r['micro_status_name'],
            "Исполнитель": r['responsible_name'] or "Не назначен",
        }
        if extra_col:
            header, col = extra_col
            row[header] = r.get(col) or "—"
        row.update({
            "План. начало": _date_cell(r['planned_start']),
            "Дедлайн": _date_cell(r['planned_end']),
            "Факт. начало": _date_cell(r['actual_start']),
            "Факт. конец": _date_cell(r['actual_end']),
            "Комментарий": r['comments'] or "",
        })
        rows.append(row)

    table = pd.DataFrame(rows)
    calc_h = (len(table) * 35) + 45
    height = min(700, max(120, calc_h))

    if not editable:
        st.dataframe(table, width="stretch", hide_index=True, height=height)
        return

    _render_editable_stages_table(table, df, session, project_id, extra_col,
                                  resync_fn, track_key, height)


def _render_editable_stages_table(table, df, session, project_id, extra_col,
                                  resync_fn, track_key, height):
    """Редактируемая таблица этапов: правка безопасных полей + удаление строк."""
    m_ref = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses")
    micro_map = {r['micro_status_name']: int(r['micro_status_id']) for _, r in m_ref.iterrows()}

    staff_df = query_db("SELECT user_id, display_name FROM users "
                        "WHERE show_in_staff=True AND is_active=True ORDER BY display_name")
    staff_map = dict(zip(staff_df["display_name"], staff_df["user_id"]))

    # Идентификаторы строк держим отдельно от таблицы, а не колонкой: скрытая колонка
    # в data_editor всё равно доступна пользователю через меню, а подмена id сломала
    # бы адресацию UPDATE/DELETE
    ids = df['stage_progress_id'].astype(int).tolist()

    ed_key = f"stages_editor_{track_key}_{project_id}"
    work = table.copy()
    work.insert(0, "🗑", False)

    ro_cols = [c for c in work.columns if c not in _EDITABLE_COLS and c != "🗑"]
    col_cfg = {
        "🗑": st.column_config.CheckboxColumn(
            "🗑", help="Отметьте строки, которые нужно удалить", width="small"),
        "Этап": st.column_config.TextColumn("Этап 🔒", disabled=True),
        "Ит.": st.column_config.NumberColumn("Ит. 🔒", disabled=True, width="small"),
        "Статус": st.column_config.SelectboxColumn(
            "Статус ✏️", options=list(micro_map.keys()), required=True),
        "Исполнитель": st.column_config.SelectboxColumn(
            "Исполнитель ✏️", options=["Не назначен"] + list(staff_map.keys()), required=True),
        "План. начало": st.column_config.DateColumn("План. начало ✏️", format="DD.MM.YYYY"),
        "Дедлайн": st.column_config.DateColumn("Дедлайн ✏️", format="DD.MM.YYYY"),
        "Факт. начало": st.column_config.DateColumn("Факт. начало ✏️", format="DD.MM.YYYY"),
        "Факт. конец": st.column_config.DateColumn("Факт. конец ✏️", format="DD.MM.YYYY"),
        "Комментарий": st.column_config.TextColumn("Комментарий ✏️"),
    }
    if extra_col:
        col_cfg[extra_col[0]] = st.column_config.TextColumn(f"{extra_col[0]} 🔒", disabled=True)

    st.caption("✏️ — поле редактируется прямо в таблице · 🔒 — только чтение, "
               "правится через форму этапа · отметьте 🗑 для удаления строки")

    edited = st.data_editor(
        work, key=ed_key, width="stretch", hide_index=True, height=height,
        disabled=ro_cols, column_config=col_cfg, num_rows="fixed",
    )

    # Сравниваем с исходной таблицей, а не с состоянием редактора: так одинаково
    # ловятся и правки ячеек, и отметки на удаление
    to_delete = [ids[i] for i in range(len(ids)) if bool(edited.iloc[i]["🗑"])]
    changed = []
    for i in range(len(ids)):
        if ids[i] in to_delete:
            continue
        diff = {c: edited.iloc[i][c] for c in _EDITABLE_COLS
                if not _same(edited.iloc[i][c], table.iloc[i][c])}
        if diff:
            changed.append((ids[i], i, diff))

    if not changed and not to_delete:
        return

    parts = []
    if changed:
        parts.append(f"изменено строк: {len(changed)}")
    if to_delete:
        parts.append(f"будет удалено этапов: {len(to_delete)}")
    st.info(" · ".join(parts))

    confirm = True
    if to_delete:
        confirm = st.checkbox(
            f"⚠️ Подтверждаю удаление {len(to_delete)} этап(ов) — действие необратимо",
            key=f"{ed_key}_confirm_del")

    if st.button("💾 Сохранить изменения", type="primary", width="stretch",
                 key=f"{ed_key}_save", disabled=not confirm):
        _save_table_changes(session, project_id, changed, to_delete,
                            micro_map, staff_map, resync_fn, track_key)


def _same(a, b):
    """Сравнение значений ячейки с учётом пустых: NaN/None/'' считаем равными."""
    a_empty = a is None or (isinstance(a, float) and pd.isna(a)) or a == ""
    b_empty = b is None or (isinstance(b, float) and pd.isna(b)) or b == ""
    if a_empty and b_empty:
        return True
    if a_empty or b_empty:
        return False
    return a == b


def _save_table_changes(session, project_id, changed, to_delete,
                        micro_map, staff_map, resync_fn, track_key):
    """Запись правок таблицы одной транзакцией + пересчёт итераций и статуса проекта.

    Порядок тот же, что в форме и диалоге удаления: commit -> пересчёт итераций ->
    commit -> sync_project_status -> clear_cache. Иначе номера итераций и статус
    проекта разъедутся с данными.
    """
    from utils.project_utils import sync_project_status
    from config.cache import clear_cache
    from config.auth import log_action

    col_to_field = {
        "План. начало": "planned_start", "Дедлайн": "planned_end",
        "Факт. начало": "actual_start", "Факт. конец": "actual_end",
        "Комментарий": "comments",
    }

    try:
        for ps_id, _row_idx, diff in changed:
            sets, params = [], {"id": int(ps_id)}

            if "Статус" in diff:
                sets.append("micro_status = :mst")
                params["mst"] = micro_map[diff["Статус"]]
                # Фактические даты бессмысленны для "Планируется"/"Отложено" -
                # форма этапа их обнуляет, повторяем то же самое
                if params["mst"] in _NO_ACTUAL_STATUSES:
                    sets += ["actual_start = NULL", "actual_end = NULL"]
                    diff.pop("Факт. начало", None)
                    diff.pop("Факт. конец", None)

            if "Исполнитель" in diff:
                sets.append("responsible_id = :rid")
                val = diff["Исполнитель"]
                params["rid"] = staff_map.get(val) if val != "Не назначен" else None

            for col, field in col_to_field.items():
                if col in diff:
                    v = diff[col]
                    if col == "Комментарий":
                        params[field] = v or None
                    else:
                        params[field] = pd.to_datetime(v).date() if pd.notna(v) else None
                    sets.append(f"{field} = :{field}")

            if not sets:
                continue
            session.execute(
                text(f"UPDATE project_stages SET {', '.join(sets)} WHERE stage_progress_id = :id"),
                params)
            log_action(st.session_state["auth"]["user_id"], "UPDATE_STAGE_INLINE",
                       "project_stages", int(ps_id), new={k: str(v) for k, v in diff.items()})

        for ps_id in to_delete:
            session.execute(text("DELETE FROM project_stages WHERE stage_progress_id = :id"),
                            {"id": int(ps_id)})
            log_action(st.session_state["auth"]["user_id"], "DELETE_STAGE_INLINE",
                       "project_stages", int(ps_id))

        session.commit()
        resync_fn(session, project_id)
        session.commit()
        sync_project_status(session, project_id)
        clear_cache()

        msg = []
        if changed:
            msg.append(f"изменено: {len(changed)}")
        if to_delete:
            msg.append(f"удалено: {len(to_delete)}")
        st.session_state[f"{track_key}_toast"] = "✅ Сохранено (" + ", ".join(msg) + ")"
        st.rerun()
    except Exception as e:
        session.rollback()
        st.error(f"Ошибка сохранения: {e}")


# ==========================================
# 📊 ДИАГРАММА ГАНТА (третий вид этапов)
# ==========================================

# Цвет полосы факта = микростатус этапа. Ключи - значения micro_status_name
# из ref_micro_statuses; неизвестный статус получает серый, а не падает.
_GANTT_STATUS_COLORS = {
    'Выполнено': '#27AE60',
    'В работе': '#3498DB',
    'Ожидание': '#E67E22',
    'Просрочено': '#E74C3C',
    'Планируется': '#95A5A6',
    'Отложено': '#B39DDB',
}
_GANTT_FALLBACK_COLOR = '#7F8C8D'
_GANTT_PLAN_COLOR = '#CFD8DC'
_DAY_MS = 24 * 60 * 60 * 1000


def _gantt_span(start, end, today):
    """Начало и длительность полосы в миллисекундах для оси времени plotly.

    Этап длиной в один день дал бы нулевую ширину и стал невидимым, поэтому
    минимальная длительность - сутки. Незакрытый этап тянется до сегодня.
    """
    if pd.isna(start):
        return None, None
    start = pd.to_datetime(start)
    end = pd.to_datetime(end) if pd.notna(end) else today
    if end < start:
        end = start
    return start, max((end - start).total_seconds() * 1000, _DAY_MS)


def render_stages_gantt(df, extra_col=None):
    """Диаграмма Ганта по этапам трека: план и факт двумя полосами.

    На каждую итерацию этапа приходится строка: сверху бледная полоса плана
    (planned_start..planned_end), под ней плотная полоса факта
    (actual_start..actual_end, у незакрытого - до сегодня), окрашенная по
    микростатусу. Вид только для чтения: правка этапов - в карточках и таблице.

    extra_col - та же пара (заголовок, колонка), что у render_stages_table:
    в технологическом треке это охват видов сведений, он уходит в подсказку.
    """
    if df.empty:
        st.info("Этапы не заведены.")
        return

    today = pd.Timestamp.today().normalize()

    # Итерации одного этапа - отдельные строки, поэтому в подпись добавляется
    # номер; без него две итерации слились бы в одну категорию оси Y
    iter_counts = df.groupby('stage_name')['stage_progress_id'].count().to_dict()

    rows, skipped = [], []
    for _, r in df.sort_values(['stage_order', 'iteration_count']).iterrows():
        label = r['stage_name']
        if iter_counts.get(r['stage_name'], 1) > 1:
            label = f"{label} · ит. {int(r['iteration_count']) if pd.notna(r['iteration_count']) else '?'}"

        p_start, p_dur = _gantt_span(r['planned_start'], r['planned_end'], today)
        # Плановая полоса рисуется только когда обе даты заданы: одна лишь дата
        # старта даёт полосу произвольной длины, которой в плане не было
        if pd.isna(r['planned_end']):
            p_start, p_dur = None, None
        f_start, f_dur = _gantt_span(r['actual_start'], r['actual_end'], today)

        if p_start is None and f_start is None:
            skipped.append(label)
            continue

        extra_txt = ""
        if extra_col:
            val = r.get(extra_col[1])
            if val and str(val) != '—':
                extra_txt = f"<br>{extra_col[0]}: {val}"

        rows.append({
            'label': label,
            'status': r['micro_status_name'],
            'responsible': r['responsible_name'] or "Не назначен",
            'comment': (r['comments'] or "").strip(),
            'extra': extra_txt,
            'p_start': p_start, 'p_dur': p_dur,
            'f_start': f_start, 'f_dur': f_dur,
            'p_end': r['planned_end'], 'f_end': r['actual_end'],
            'a_start': r['actual_start'],
        })

    if not rows:
        st.info("У этапов не заполнены даты — диаграмму построить не из чего.")
        return

    # Порядок категорий задаётся явно: без этого plotly расставит их сам,
    # и этапы перестанут идти в порядке процесса
    labels = [x['label'] for x in rows]

    fig = go.Figure()

    # Порядок добавления трасс задаёт вертикальный порядок полос внутри строки:
    # трасса, добавленная позже, оказывается ВЫШЕ. Поэтому факт добавляется
    # первым, план - последним, и план читается верхней полосой.

    # 1. Факт - отдельная трасса на каждый статус, чтобы в легенде появились
    # названия статусов, а не безымянная разноцветная полоса
    fact_rows = [x for x in rows if x['f_start'] is not None]
    for status in sorted({x['status'] for x in fact_rows}):
        part = [x for x in fact_rows if x['status'] == status]
        fig.add_trace(go.Bar(
            y=[x['label'] for x in part],
            x=[x['f_dur'] for x in part],
            base=[x['f_start'] for x in part],
            orientation='h', name=status, offsetgroup='fact',
            marker=dict(color=_GANTT_STATUS_COLORS.get(status, _GANTT_FALLBACK_COLOR)),
            customdata=[[
                _fmt_d(x['a_start']),
                _fmt_d(x['f_end']) if pd.notna(x['f_end']) else "по настоящее время",
                x['responsible'],
                x['comment'] or x['label'],
                x['extra'],
            ] for x in part],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Факт: %{customdata[0]} – %{customdata[1]}<br>"
                f"Статус: {status}<br>"
                "Исполнитель: %{customdata[2]}<br>"
                "%{customdata[3]}%{customdata[4]}<extra></extra>"
            ),
        ))

    # 2. План - бледная полоса, добавляется последней и потому идёт сверху
    plan_rows = [x for x in rows if x['p_start'] is not None]
    if plan_rows:
        fig.add_trace(go.Bar(
            y=[x['label'] for x in plan_rows],
            x=[x['p_dur'] for x in plan_rows],
            base=[x['p_start'] for x in plan_rows],
            orientation='h', name='План', offsetgroup='plan',
            marker=dict(color=_GANTT_PLAN_COLOR),
            customdata=[[_fmt_d(x['p_start']), _fmt_d(x['p_end'])] for x in plan_rows],
            hovertemplate="<b>%{y}</b><br>План: %{customdata[0]} – %{customdata[1]}<extra></extra>",
        ))

    fig.add_vline(x=today.timestamp() * 1000, line_width=2,
                  line_dash="dash", line_color="#E74C3C")

    # Легенда и подписи оси дат живут в одном верхнем поле, поэтому её отступ
    # считается в пикселях, а не задаётся долей "на глаз": доля от высоты у
    # диаграммы на 3 этапа и на 30 даёт совершенно разный зазор, и легенда
    # наезжает на подписи дат.
    top_margin, bottom_margin = 95, 20
    height = max(280, len(labels) * 46 + 150)
    plot_h = max(1, height - top_margin - bottom_margin)
    legend_y = 1 + (52 / plot_h)   # ~52px над областью графика: две строки подписей оси

    fig.update_layout(
        barmode='group', bargap=0.25,
        height=height,
        # Ось дат сверху: у длинного списка этапов она остаётся на виду, не уезжая
        # вниз вместе с концом диаграммы
        xaxis=dict(type='date', side='top', showgrid=True, gridcolor='#ECEFF1'),
        # categoryarray в обратном порядке: первый по процессу этап должен быть сверху
        yaxis=dict(categoryorder='array', categoryarray=labels[::-1],
                   tickfont=dict(size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=legend_y, xanchor="left", x=0,
                    font=dict(size=10)),
        margin=dict(l=10, r=20, t=top_margin, b=bottom_margin),
        plot_bgcolor='white',
    )

    st.plotly_chart(fig, width='stretch')
    st.caption(
        "Бледная полоса — план, цветная под ней — факт (цвет по статусу); "
        "пунктир — сегодня. Незакрытый этап тянется до сегодняшнего дня. "
        "Диаграмма только для просмотра — этапы правятся в карточках и таблице."
    )

    if skipped:
        st.caption(f"⚠️ Без дат и потому не показаны: {', '.join(skipped)}")


def _fmt_d(v):
    return pd.to_datetime(v).strftime('%d.%m.%Y') if pd.notna(v) else "—"
