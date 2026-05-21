import json
import uuid
import os
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st

# 🔹 Абсолютный путь для Docker: /app/app_data/sessions
SESSION_DIR = Path(os.getenv("SESSION_DIR", "/app/app_data/sessions"))
SESSION_DIR.mkdir(parents=True, exist_ok=True)

def create_token(auth_data: dict) -> str:
    """Сохраняет сессию + UI state на диск."""
    token = str(uuid.uuid4())
    safe_data = auth_data.copy()
    
    # 🔹 Сохраняем UI state (только простые типы: int, str, bool)
    ui_state = {
        "active_tab": st.session_state.get("active_tab", 0),
        "selected_supplier_id": st.session_state.get("selected_supplier_id"),
        "selected_project_id": st.session_state.get("selected_project_id"),
        "show_admin": st.session_state.get("show_admin", False),
        "dash_edit_mode": st.session_state.get("dash_edit_mode", False)
    }
    safe_data["_ui_state"] = ui_state
    
    # ... (остальной код сериализации datetime без изменений) ...
    if isinstance(safe_data.get("last_active"), datetime):
        safe_data["last_active"] = safe_data["last_active"].isoformat()
    safe_data["_saved_at"] = datetime.now().isoformat()
    
    file_path = SESSION_DIR / f"{token}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(safe_data, f, ensure_ascii=False)
    return token

def restore_session(token: str) -> dict | None:
    """Восстанавливает сессию + применяет UI state."""
    file_path = SESSION_DIR / f"{token}.json"
    if not file_path.exists():
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    saved_at = datetime.fromisoformat(data.pop("_saved_at", datetime.now().isoformat()))
    if datetime.now() - saved_at > timedelta(minutes=30):
        file_path.unlink(missing_ok=True)
        return None
        
    if isinstance(data.get("last_active"), str):
        data["last_active"] = datetime.fromisoformat(data["last_active"])
    
    # 🔹 Применяем UI state после восстановления авторизации
    ui_state = data.pop("_ui_state", {})
    for key, value in ui_state.items():
        if value is not None:  # Не перезаписываем, если None
            st.session_state[key] = value
            
    return data

def destroy_session(token: str) -> None:
    """Удаляет сессию с диска."""
    (SESSION_DIR / f"{token}.json").unlink(missing_ok=True)