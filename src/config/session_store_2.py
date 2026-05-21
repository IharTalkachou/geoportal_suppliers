import json
import uuid
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SESSION_DIR = Path(os.getenv("SESSION_DIR", "/app/app_data/sessions"))
SESSION_DIR.mkdir(parents=True, exist_ok=True)

def _debug(msg: str):
    sys.stderr.write(f"[FP] {msg}\n")
    sys.stderr.flush()

def _normalize_fingerprint(ua: str, lang: str) -> str:
    """
    Создает стабильный ключ: Браузер/Версия/ОС/Язык.
    Устойчив к Ctrl+R, но различает Chrome/Firefox/Edge/Safari.
    """
    ua = ua.lower() if ua else ""
    lang = lang.lower().split(",")[0].strip() if lang else "xx"

    # 1. Браузер + мажорная версия
    browser, ver = "unknown", "0"
    if "firefox/" in ua:
        browser = "firefox"
        m = re.search(r"firefox/([\d.]+)", ua)
    elif "edg/" in ua:
        browser = "edge"
        m = re.search(r"edg/([\d.]+)", ua)
    elif "chrome/" in ua:
        browser = "chrome"
        m = re.search(r"chrome/([\d.]+)", ua)
    elif "safari/" in ua and "chrome/" not in ua:
        browser = "safari"
        m = re.search(r"version/([\d.]+)", ua)
    else:
        m = None
    if m: ver = m.group(1).split(".")[0]

    # 2. ОС
    os_name = "unknown"
    if "windows" in ua: os_name = "win"
    elif "macintosh" in ua or "mac os" in ua: os_name = "mac"
    elif "linux" in ua: os_name = "linux"
    elif "android" in ua: os_name = "android"
    elif "iphone" in ua or "ipad" in ua: os_name = "ios"

    return f"{browser}_{ver}_{os_name}_{lang}"

def _compute_fingerprint() -> dict:
    import streamlit as st
    try:
        headers = dict(st.context.headers) if hasattr(st.context, 'headers') else {}
        ua = headers.get("User-Agent") or headers.get("user-agent", "")
        lang = headers.get("Accept-Language") or headers.get("accept-language", "")
        
        fp_key = _normalize_fingerprint(ua, lang)
        _debug(f"🔍 FP Key: {fp_key}")
        return {"fp_key": fp_key}
    except Exception as e:
        _debug(f"⚠️ FP Error: {e}")
        return {"fp_key": f"err_{type(e).__name__}"}

def _fingerprints_match(stored: dict, current: dict, strict_ip: bool = False) -> bool:
    return stored.get("fp_key") == current.get("fp_key")

def create_token(auth_data: dict) -> str:
    token = str(uuid.uuid4())
    safe_data = auth_data.copy()
    safe_data["_ui_state"] = {k: v for k, v in {
        "selected_supplier_id": auth_data.get("ui_supplier_id"),
        "selected_project_id": auth_data.get("ui_project_id"),
        "show_admin": auth_data.get("ui_show_admin", False)
    }.items() if v is not None}
    
    safe_data["_fingerprint"] = _compute_fingerprint()
    if isinstance(safe_data.get("last_active"), datetime):
        safe_data["last_active"] = safe_data["last_active"].isoformat()
    safe_data["_saved_at"] = datetime.now().isoformat()
    
    with open(SESSION_DIR / f"{token}.json", "w", encoding="utf-8") as f:
        json.dump(safe_data, f, ensure_ascii=False)
    _debug(f"🔑 Created: {token[:8]}... | FP: {safe_data['_fingerprint']['fp_key']}")
    return token

def restore_session(token: str, strict_ip: bool = False) -> dict | None:
    import streamlit as st
    fp = SESSION_DIR / f"{token}.json"
    if not fp.exists(): return None
    
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    saved = datetime.fromisoformat(data.pop("_saved_at", datetime.now().isoformat()))
    if datetime.now() - saved > timedelta(minutes=30):
        fp.unlink(missing_ok=True)
        _debug("⏱ Expired.")
        return None
        
    current_fp = _compute_fingerprint()
    stored_fp = data.get("_fingerprint", {})
    _debug(f"🔍 Check: Stored={stored_fp.get('fp_key')} vs Current={current_fp['fp_key']}")
    
    if not _fingerprints_match(stored_fp, current_fp, strict_ip):
        fp.unlink(missing_ok=True)
        _debug("🚨 MISMATCH! Destroyed.")
        try:
            from config.auth import log_action
            log_action(user_id=data.get("user_id"), action="SESSION_RESTORE_FAILED", 
                       target_table="auth", old=stored_fp, new=current_fp)
        except: pass
        return None
        
    # Восстановление
    if isinstance(data.get("last_active"), str):
        data["last_active"] = datetime.fromisoformat(data["last_active"])
    for k, v in data.pop("_ui_state", {}).items():
        if v is not None: st.session_state[k] = v
    _debug(f"✅ Restored: {token[:8]}...")
    return data

def destroy_session(token: str) -> None:
    (SESSION_DIR / f"{token}.json").unlink(missing_ok=True)
    _debug(f"🗑 Destroyed: {token[:8]}...")

def cleanup_expired_sessions(max_age_hours: int = 24) -> int:
    removed = 0
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    for p in SESSION_DIR.glob("*.json"):
        try:
            if datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                p.unlink(); removed += 1
        except: continue
    return removed