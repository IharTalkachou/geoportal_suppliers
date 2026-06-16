import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from config.cache import query_db, clear_cache
from config.auth import log_action

def render_bureaucracy_tab(session, project_id, user_role="user"):
    st.subheader("📜 Бюрократия (Документарные этапы)")
    is_readonly = (user_role == "user")

    # 1. ЗАГРУЗКА СПРАВОЧНИКОВ
    stages = query_db("""
        SELECT stage_id, stage_name, stage_type, duration_days, stage_order, stage_code
        FROM stages WHERE track_category = '1. Документарный' ORDER BY stage_order
    """)
    micro_statuses = query_db("SELECT micro_status_id, micro_status_name FROM ref_micro_statuses ORDER BY micro_status_id")

    stage_map = {
        row["stage_name"]: {
            "id": int(row["stage_id"]), "type": row["stage_type"],
            "duration": int(row["duration_days"] or 0), "order": row["stage_order"]
        } for _, row in stages.iterrows()
    }
    micro_map = {name: int(mid) for name, mid in zip(micro_statuses["micro_status_name"], micro_statuses["micro_status_id"])}

    if not stage_map or not micro_map:
        st.warning("⚠️ Справочники пусты.")
        return
    
    # 2. ЗАГРУЗКА ДАННЫХ
    ps_df = query_db("""
        SELECT ps.stage_progress_id, s.stage_name, ms.micro_status_name,
               ps.iteration_count, ps.planned_start, ps.planned_end,
               ps.actual_start, ps.actual_end, ps.comments,
               u.display_name as responsible_name, ps.responsible_id,
               (SELECT COUNT(*) FROM stage_documents WHERE project_stage_id = ps.stage_progress_id) as doc_count -- 👈 Счётчик
        FROM project_stages ps
        JOIN stages s ON ps.stage_id = s.stage_id
        JOIN ref_micro_statuses ms ON ps.micro_status = ms.micro_status_id
        LEFT JOIN users u ON ps.responsible_id = u.user_id 
        WHERE ps.project_id = :pid
        ORDER BY COALESCE(ps.actual_start, ps.planned_start) ASC, s.stage_order ASC
    """, {"pid": project_id})

    # Добавим визуальный индикатор скрепки в DataFrame
    ps_df['📎'] = ps_df['doc_count'].apply(lambda x: f"📎 {x}" if x > 0 else "")

    st.dataframe(
        ps_df[["📎", "stage_name", "micro_status_name", "responsible_name", "iteration_count", "planned_start", "planned_end", "actual_start", "actual_end", "comments"]], 
        width='stretch', hide_index=True,
        column_config={
            "📎": st.column_config.TextColumn("Док.", width="small"),
            "stage_name": "Этап", 
            "micro_status_name": "Статус",
            "responsible_name": "Ответственный",
            "iteration_count": st.column_config.NumberColumn("Ит.", format="%d"),
            "planned_start": st.column_config.DateColumn("План. начало", format="DD.MM.YYYY"),
            "planned_end": st.column_config.DateColumn("Дедлайн", format="DD.MM.YYYY"),
            "actual_start": st.column_config.DateColumn("Факт. начало", format="DD.MM.YYYY"),
            "actual_end": st.column_config.DateColumn("Факт. конец", format="DD.MM.YYYY")
        }
    )
    
    if is_readonly: return

    # ==========================================
    # Вспомогательные функции расчёта
    # ==========================================
    def calculate_norm_end(s_name, start_date):
        if not s_name or not start_date: return None
        duration = stage_map.get(s_name, {}).get("duration", 0)
        return start_date + timedelta(days=duration)

    def sync_planned_end():
        """Вызывается при изменении этапа или дат начала"""
        if st.session_state.get("buro_manual_date"):
            return
        base_date = st.session_state.get("buro_a_start_in") or st.session_state.get("buro_p_start_in")
        st.session_state["buro_p_end_in"] = calculate_norm_end(st.session_state.get("buro_stage_in"), base_date)

    def on_toggle_manual():
        """Вызывается при клике на переключатель 'Вручную'"""
        if not st.session_state.get("buro_manual_date"):
            # Если выключили - принудительно возвращаем к норме
            sync_planned_end()

    # ==========================================
    # SMART CRUD
    # ==========================================
    with st.expander("➕ Добавить / ✏️ Редактировать этап"):
        item_options = ["(Добавить новый)"]
        item_ids_map = {f"{r['stage_name']} (Ит. {int(r['iteration_count'])})": int(r["stage_progress_id"]) for _, r in ps_df.iterrows()}
        item_options += list(item_ids_map.keys())

        sel_item = st.selectbox("Выберите этап:", item_options, key="buro_sel")
        is_editing = sel_item != "(Добавить новый)"

        # РЕАКТИВНАЯ ЗАГРУЗКА
        if st.session_state.get("buro_sel_prev") != sel_item:
            if is_editing:
                curr = ps_df[ps_df["stage_progress_id"] == item_ids_map[sel_item]].iloc[0]
                st.session_state["buro_stage_in"] = curr["stage_name"]
                st.session_state["buro_status_in"] = curr["micro_status_name"]
                st.session_state["buro_p_start_in"] = curr["planned_start"]
                st.session_state["buro_p_end_in"] = curr["planned_end"]
                st.session_state["buro_a_start_in"] = curr["actual_start"]
                st.session_state["buro_a_end_in"] = curr["actual_end"]
                st.session_state["buro_comments_in"] = curr["comments"] or ""
                st.session_state["buro_iter_in"] = int(curr["iteration_count"])
                
                # --- ЛОГИКА ОПРЕДЕЛЕНИЯ 'ВРУЧНУЮ' ---
                base = curr["actual_start"] or curr["planned_start"]
                norm_date = calculate_norm_end(curr["stage_name"], base)
                # Если дата в БД не равна расчетной - включаем тумблер
                st.session_state["buro_manual_date"] = (curr["planned_end"] != norm_date)
                
                resp_id = curr.get("responsible_id")
                if pd.notna(resp_id):
                    res = query_db("SELECT display_name FROM users WHERE user_id = :u", {"u": int(resp_id)})
                    st.session_state["buro_resp_in"] = res.iloc[0]["display_name"] if not res.empty else "Не назначен"
                else:
                    st.session_state["buro_resp_in"] = "Не назначен"
            else:
                st.session_state["buro_stage_in"] = list(stage_map.keys())[0]
                st.session_state["buro_status_in"] = "Планируется"
                st.session_state["buro_p_start_in"] = date.today()
                st.session_state["buro_p_end_in"] = calculate_norm_end(st.session_state["buro_stage_in"], date.today())
                st.session_state["buro_a_start_in"] = None
                st.session_state["buro_a_end_in"] = None
                st.session_state["buro_comments_in"] = ""
                st.session_state["buro_resp_in"] = "Не назначен"
                st.session_state["buro_manual_date"] = False
            
            st.session_state["buro_sel_prev"] = sel_item

        # ИНТЕРФЕЙС
        col1, col2 = st.columns(2)
        with col1:
            st.selectbox("Этап *", list(stage_map.keys()), key="buro_stage_in", on_change=sync_planned_end)
            st.selectbox("Микростатус", list(micro_map.keys()), key="buro_status_in")
            staff = ["Не назначен"] + sorted(query_db("SELECT display_name FROM users WHERE show_in_staff=True AND is_active=True")["display_name"].tolist())
            st.selectbox("👤 Ответственный", staff, key="buro_resp_in")

        with col2:
            st.date_input("🗓️ Плановое начало", key="buro_p_start_in", on_change=sync_planned_end)
            c_date, c_lock = st.columns([0.7, 0.3])
            with c_lock:
                st.write("<br>", unsafe_allow_html=True)
                # 🟢 ДОБАВЛЕН КОЛБЭК on_change
                st.toggle("✏️ Вручную", key="buro_manual_date", on_change=on_toggle_manual)
            with c_date:
                st.date_input("🎯 План. завершение (Дедлайн)", key="buro_p_end_in", disabled=not st.session_state.buro_manual_date)
            
            st.divider()
            st.date_input("🚀 Фактическое начало", key="buro_a_start_in", value=None, on_change=sync_planned_end)
            st.date_input("🏁 Фактическое окончание", key="buro_a_end_in", value=None)

        st.text_area("Комментарий", key="buro_comments_in")

        if not is_editing:
            st.checkbox("☑️ Автоматически закрыть предыдущий этап", value=True, key="buro_auto_close")

        # ==========================================
        # 📂 БЛОК РАБОТЫ С ДОКУМЕНТАМИ (Только при редактировании)
        # ==========================================
        if is_editing:
            st.markdown("---")
            st.markdown("##### 📂 Документы и ссылки")
            curr_progress_id = int(item_ids_map[sel_item])
            docs = query_db("SELECT * FROM stage_documents WHERE project_stage_id = :id", {"id": curr_progress_id})
            
            if not docs.empty:
                for _, d in docs.iterrows():
                    d_col1, d_col2 = st.columns([0.8, 0.2])
                    with d_col1:
                        st.link_button(f"📄 {d['doc_name']}", d['doc_url'], use_container_width=True)
                    with d_col2:
                        if st.button("🗑", key=f"del_doc_buro_{d['doc_id']}", help="Удалить ссылку"):
                            session.execute(text("DELETE FROM stage_documents WHERE doc_id = :id"), {"id": int(d['doc_id'])})
                            session.commit(); clear_cache(); st.rerun()
            else:
                st.caption("К этому этапу еще не прикреплено ни одного документа.")

            # 2. Форма добавления нового документа
            with st.expander("➕ Прикрепить ссылку на документ"):
                new_doc_name = st.text_input("Название", key="new_doc_name_in", placeholder="Письмо № 25/1111 от 16.02.2026")
                new_doc_url = st.text_input("URL-ссылка на файл", key="buro_doc_url_in", placeholder="http://repo.local/file.pdf")
                if st.button("📎 Добавить документ", key="btn_buro_add_doc"):
                    if new_doc_name and new_doc_url:
                        try:
                            session.execute(text("""
                                INSERT INTO stage_documents (project_stage_id, doc_name, doc_url)
                                VALUES (:psid, :name, :url)
                            """), {"psid": curr_progress_id, "name": new_doc_name, "url": new_doc_url})
                            session.commit(); clear_cache(); st.success("Документ добавлен!"); st.rerun()
                        except Exception as e: st.error(f"Ошибка: {e}")
                    else:
                        st.error("Заполните название и ссылку")
            st.markdown("---")

        # СОХРАНЕНИЕ
        if st.button("💾 Сохранить изменения", type="primary", use_container_width=True):
            try:
                s_id = stage_map[st.session_state.buro_stage_in]["id"]
                # 🟢 ИСПРАВЛЕНИЕ NUMPY INT
                r_id = None
                if st.session_state.buro_resp_in != "Не назначен":
                    r_res = query_db("SELECT user_id FROM users WHERE display_name = :n", {"n": st.session_state.buro_resp_in})
                    if not r_res.empty: r_id = int(r_res.iloc[0]["user_id"])

                if not is_editing and st.session_state.buro_auto_close:
                    session.execute(text("UPDATE project_stages SET actual_end=:n, micro_status=:ms WHERE project_id=:p AND actual_end IS NULL"),
                                    {"n": date.today(), "ms": micro_map["Выполнено"], "p": project_id})

                it_val = st.session_state.buro_iter_in if is_editing else \
                         session.execute(text("SELECT COALESCE(MAX(iteration_count), 0) + 1 FROM project_stages WHERE project_id=:p AND stage_id=:s"),
                                         {"p": project_id, "s": s_id}).scalar()

                params = {
                    "pid": project_id, "sid": s_id, "mst": int(micro_map[st.session_state.buro_status_in]),
                    "iter": int(it_val), "ps": st.session_state.buro_p_start_in, "pe": st.session_state.buro_p_end_in,
                    "as": st.session_state.buro_a_start_in, "ae": st.session_state.buro_a_end_in,
                    "comm": st.session_state.buro_comments_in, "rid": r_id
                }

                if is_editing:
                    params["id"] = int(item_ids_map[sel_item])
                    session.execute(text("""UPDATE project_stages SET stage_id=:sid, micro_status=:mst, iteration_count=:iter,
                        planned_start=:ps, planned_end=:pe, actual_start=:as, actual_end=:ae, comments=:comm, responsible_id=:rid
                        WHERE stage_progress_id=:id"""), params)
                else:
                    session.execute(text("""INSERT INTO project_stages (project_id, stage_id, micro_status, iteration_count,
                        planned_start, planned_end, actual_start, actual_end, comments, responsible_id)
                        VALUES (:pid, :sid, :mst, :iter, :ps, :pe, :as, :ae, :comm, :rid)"""), params)

                session.commit(); clear_cache(); st.success("Готово!"); st.rerun()
            except Exception as e: st.error(f"Ошибка БД: {e}"); session.rollback()

        if is_editing and st.button("🗑 Удалить", type="secondary", use_container_width=True):
            session.execute(text("DELETE FROM project_stages WHERE stage_progress_id = :id"), {"id": int(item_ids_map[sel_item])})
            session.commit(); clear_cache(); st.rerun()