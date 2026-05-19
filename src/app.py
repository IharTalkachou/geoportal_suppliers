import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
from ui.suppliers_tab import render_suppliers_tab
from ui.analytics_tab import render_analytics_tab
from ui.datasets_tab import render_datasets_tab
from ui.project_dashboard import render_project_dashboard

load_dotenv()
DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
engine = create_engine(DB_URL, pool_pre_ping=True)

st.set_page_config(page_title="Поставщики Национального геопортала", layout="wide", page_icon="🌍")
st.title("🗺️ Управление поставщиками пространственных данных")

if "current_tab" not in st.session_state:
    st.session_state.current_tab = "📁 Поставщики"

tabs = st.tabs(["📁 Поставщики", "🗄️ Наборы", "📋 Проекты", "📊 Аналитика"])

with tabs[0]:
    with Session(engine) as session:
        render_suppliers_tab(session)
with tabs[1]: 
    with Session(engine) as session:
        render_datasets_tab(session)  
with tabs[2]:
    with Session(engine) as session:
        render_project_dashboard(session)      
with tabs[3]:
    render_analytics_tab()