import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "app_config.json")

def load_settings():
    """Загружает настройки из файла. Если файла нет, возвращает дефолты."""
    defaults = {
        "session_timeout_minutes": 30,
        "maintenance_mode": False,
        "maintenance_warning": False,
        "maintenance_message": "Технические работы скоро начнутся.",
        "lockout_message": "Система временно недоступна."
    }
    if not os.path.exists(CONFIG_PATH):
        return defaults
    
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return {**defaults, **json.load(f)}
    except Exception:
        return defaults

def save_settings(settings):
    """Сохраняет словарь настроек в JSON."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False