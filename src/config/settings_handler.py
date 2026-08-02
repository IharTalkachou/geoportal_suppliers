import streamlit as st
from sqlalchemy.orm import Session
from config.database import engine
from models.tables import AppSetting

DEFAULT_SETTINGS = {
    "session_timeout_minutes": 30,
    "maintenance_mode": False,
    "maintenance_warning": False,
    "maintenance_message": "Технические работы скоро начнутся.",
    "lockout_message": "Система временно недоступна.",
    "total_registered_accounts": 0
}

def load_settings():
    """Загружает настройки из БД с кэшированием на 60 секунд."""
    return _get_settings_from_db()

@st.cache_data(ttl=60, show_spinner=False)
def _get_settings_from_db():
    settings = DEFAULT_SETTINGS.copy()
    try:
        with Session(engine) as session:
            db_settings = session.query(AppSetting).all()
            if db_settings:
                for s in db_settings:
                    settings[s.setting_key] = s.setting_value
    except Exception as e:
        print(f"⚠️ Ошибка загрузки настроек: {e}")
    return settings

def save_settings(settings_dict):
    """Сохраняет настройки в БД и сбрасывает кэш."""
    try:
        with Session(engine) as session:
            for key, value in settings_dict.items():
                setting = session.query(AppSetting).filter_by(setting_key=key).first()
                if setting:
                    setting.setting_value = value
                else:
                    session.add(AppSetting(setting_key=key, setting_value=value))
            session.commit()
        st.cache_data.clear()
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")
        return False