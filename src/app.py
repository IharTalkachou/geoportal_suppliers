import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
from ui.suppliers_tab import render_suppliers_tab
from ui.projects_tab import render_projects_tab
from ui.project_items_tab import render_project_items_tab
from ui.stages_tracking import render_stages_tab
from ui.analytics_tab import render_analytics_tab

load_dotenv()
DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
engine = create_engine(DB_URL, pool_pre_ping=True)

st.set_page_config(page_title="Поставщики Национального геопортала", layout="wide", page_icon="🌍")
st.title("🗺️ Управление поставщиками пространственных данных")

if "current_tab" not in st.session_state:
    st.session_state.current_tab = "📁 Поставщики"

tabs = st.tabs(["📁 Поставщики", "👥 Контакты", "📂 Проекты", "⚙️ Этапы", "📊 Аналитика"])

with tabs[0]:
    with Session(engine) as session:
        render_suppliers_tab(session)
with tabs[1]: st.info("Раздел 'Контакты' в разработке")
with tabs[2]:
    with Session(engine) as session:
        render_projects_tab(session)
        st.divider()
        render_project_items_tab(session)
with tabs[3]:
    with Session(engine) as session:
        render_stages_tab(session)
with tabs[4]:
    render_analytics_tab()