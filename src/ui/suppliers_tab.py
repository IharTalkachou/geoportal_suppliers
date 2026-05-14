import streamlit as st
import pandas as pd
from config.cache import query_db, clear_cache

def render_suppliers_tab(session):
    st.subheader("📁 Поставщики")
    
    # Фильтр с сохранением состояния между rerun()
    if "sup_search" not in st.session_state:
        st.session_state.sup_search = ""
        
    search_term = st.text_input("🔍 Поиск по наименованию", key="sup_search")
    
    # Загрузка из кэша вместо прямого запроса к сессии
    df = query_db("SELECT * FROM suppliers ORDER BY supplier_name")
    
    # Применяем фильтр локально (не затрагивает БД)
    if search_term.strip():
        df = df[df["supplier_name"].str.contains(search_term, case=False, na=False)]
    
    with st.form("suppliers_form", clear_on_submit=False):
        edited_df = st.data_editor(
            df,
            key="suppliers_editor",
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "supplier_id": st.column_config.NumberColumn("ID", disabled=True),
                "supplier_name": st.column_config.TextColumn("Наименование", required=True),
            },
            disabled=["supplier_id"]
        )
        
        col1, col2 = st.columns([1, 4])
        if col1.form_submit_button("💾 Сохранить", type="primary"):
            try:
                # Логика sync (упрощена для примера, используйте вашу из Действия 2)
                # session.execute(...)
                session.commit()
                clear_cache()  # 🔑 Инвалидация кэша после изменения
                st.success("✅ Сохранено")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Ошибка: {e}")
                session.rollback()