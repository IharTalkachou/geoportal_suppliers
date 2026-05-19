import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.cache import query_db, clear_cache

def render_datasets_tab(session):
    st.subheader("📚 Справочники: Наборы и Виды сведений")

    # ==========================================
    # ЧАСТЬ 1: НАБОРЫ ДАННЫХ (Datasets)
    # ==========================================
    st.markdown("### 📦 Наборы данных")
    ds_df = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")

    ds_col_config = {
        "dataset_name": st.column_config.TextColumn("Название набора", required=True),
        "dataset_id": st.column_config.NumberColumn("ID", disabled=True)
    }

    with st.form("ds_editor_form"):
        edited_ds = st.data_editor(
            ds_df, key="ds_editor", hide_index=True, use_container_width=True,
            num_rows="dynamic", column_config=ds_col_config, disabled=["dataset_id"],
            column_order=["dataset_name"]  # 🔹 ID скрыт из UI
        )

        orig_ds = set(ds_df["dataset_id"].dropna().astype(int))
        curr_ds = set(edited_ds["dataset_id"].dropna().astype(int))
        ds_to_delete = list(orig_ds - curr_ds)

        blocked_ds = []
        if ds_to_delete:
            for did in ds_to_delete:
                cnt = session.execute(text("SELECT COUNT(*) FROM project_items WHERE dataset_id = :id"), {"id": did}).scalar()
                if cnt > 0:
                    blocked_ds.append(did)

        if blocked_ds:
            st.warning(f"⚠️ Невозможно удалить наборы. Они уже используются в составе проектов.")

        if st.form_submit_button("💾 Сохранить наборы", type="primary"):
            try:
                safe_delete = [d for d in ds_to_delete if d not in blocked_ds]
                if safe_delete:
                    session.execute(text("DELETE FROM datasets WHERE dataset_id IN :ids"), {"ids": tuple(safe_delete)})

                for _, row in edited_ds.iterrows():
                    pid = row.get("dataset_id")
                    if pd.isna(pid):
                        session.execute(text("INSERT INTO datasets (dataset_name) VALUES (:name)"), {"name": row["dataset_name"]})
                    else:
                        session.execute(text("UPDATE datasets SET dataset_name = :name WHERE dataset_id = :id"),
                                        {"name": row["dataset_name"], "id": int(pid)})
                session.commit()
                clear_cache()
                st.success("✅ Наборы сохранены!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка: {e}")
                session.rollback()

    st.divider()

    # ==========================================
    # ЧАСТЬ 2: ВИДЫ СВЕДЕНИЙ (Info Types)
    # ==========================================
    st.markdown("### 📄 Виды сведений")
    datasets_list = query_db("SELECT dataset_id, dataset_name FROM datasets ORDER BY dataset_name")
    if datasets_list.empty:
        st.info("📭 Сначала создайте хотя бы один набор данных в блоке выше.")
        return

    ds_map = dict(zip(datasets_list["dataset_name"], datasets_list["dataset_id"]))
    sel_ds_name = st.selectbox("🔍 Редактировать виды для набора:", list(ds_map.keys()), key="info_ds_filter")
    sel_ds_id = ds_map[sel_ds_name]

    # Загрузка видов
    info_df = query_db(
        'SELECT info_id, info_name, type, format, "update" FROM info_types WHERE dataset_id = :did ORDER BY info_name',
        {"did": sel_ds_id}
    )

    # 🔑 Загрузка справочников для выпадающих списков
    formats = pd.read_sql(text("SELECT format_name FROM ref_file_formats ORDER BY format_name"), session.bind)["format_name"].tolist()
    periods = pd.read_sql(text("SELECT period_name FROM ref_update_periods ORDER BY period_name"), session.bind)["period_name"].tolist()

    info_col_config = {
        "info_name": st.column_config.TextColumn("Название вида", required=True),
        "type": st.column_config.SelectboxColumn("Тип", options=["Данные", "Сервис"]),
        "format": st.column_config.SelectboxColumn("Формат", options=formats),
        "update": st.column_config.SelectboxColumn("Срок обновления", options=periods),
        "info_id": st.column_config.NumberColumn("ID", disabled=True)
    }

    with st.form("info_editor_form"):
        edited_info = st.data_editor(
            info_df, key="info_editor", hide_index=True, use_container_width=True,
            num_rows="dynamic", column_config=info_col_config, disabled=["info_id"],
            column_order=["info_name", "type", "format", "update"]  # 🔹 ID скрыт из UI
        )

        orig_info = set(info_df["info_id"].dropna().astype(int))
        curr_info = set(edited_info["info_id"].dropna().astype(int))
        info_to_delete = list(orig_info - curr_info)

        if st.form_submit_button("💾 Сохранить виды сведений", type="primary"):
            try:
                if info_to_delete:
                    session.execute(text("DELETE FROM info_types WHERE info_id IN :ids"), {"ids": tuple(info_to_delete)})

                for _, row in edited_info.iterrows():
                    pid = row.get("info_id")
                    if pd.isna(pid):
                        session.execute(text("""
                            INSERT INTO info_types (dataset_id, info_name, type, format, "update")
                            VALUES (:did, :name, :typ, :fmt, :upd)
                        """), {
                            "did": sel_ds_id, "name": row["info_name"],
                            "typ": row.get("type"), "fmt": row.get("format"), "upd": row.get("update")
                        })
                    else:
                        session.execute(text("""
                            UPDATE info_types SET info_name=:name, type=:typ, format=:fmt, "update"=:upd
                            WHERE info_id=:id
                        """), {
                            "name": row["info_name"], "typ": row.get("type"),
                            "fmt": row.get("format"), "upd": row.get("update"), "id": int(pid)
                        })
                session.commit()
                clear_cache()
                st.success("✅ Виды сведений сохранены!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка: {e}")
                session.rollback()