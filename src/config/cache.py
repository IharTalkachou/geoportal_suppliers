import streamlit as st
import pandas as pd
from sqlalchemy import text
from config.database import engine

@st.cache_data(ttl=120, show_spinner=False)
def query_db(sql_query: str, params: dict = None) -> pd.DataFrame:
    """
    Выполняет SQL-запрос и кэширует результат на 120 секунд.
    Автоматически обновляется при изменении запроса или параметров.
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql_query), conn, params=params)

def clear_cache():
    """Принудительно очищает кэш после успешной транзакции."""
    query_db.clear()