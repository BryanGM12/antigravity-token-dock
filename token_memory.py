"""
Token Memory System for Antigravity Accounts
Persistently tracks token percentages, refresh intervals, and ETAs for all authorized accounts.
Tracks both Gemini Models and Claude/GPT Models with sub-minute resolution.
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger("TokenMemory")

MEMORY_DIR = os.path.expandvars(r"%USERPROFILE%\.openclaw\workspace\state\antigravity_controller")
MEMORY_FILE = os.path.join(MEMORY_DIR, "token_memory.json")
os.makedirs(MEMORY_DIR, exist_ok=True)

try:
    from config_manager import get_authorized_emails
    DEFAULT_ACCOUNTS = get_authorized_emails()
except Exception:
    DEFAULT_ACCOUNTS = [
        "account1.pro@gmail.com",
        "account2.pro@gmail.com",
        "account3.pro@gmail.com",
        "account4.pro@gmail.com"
    ]

def parse_refresh_delta(text: str) -> Optional[timedelta]:
    """Parses text like '4 days, 6 hours' or '3 horas, 56 minutos' into a timedelta."""
    if not text:
        return None
        
    days = 0
    hours = 0
    minutes = 0
    seconds = 0
    
    m_day = re.search(r'(\d+)\s*(?:day|días|dias|día|dia)s?', text, re.IGNORECASE)
    if m_day:
        days = int(m_day.group(1))
        
    m_hr = re.search(r'(\d+)\s*(?:hour|horas|hora|hr|hrs|h)s?', text, re.IGNORECASE)
    if m_hr:
        hours = int(m_hr.group(1))
        
    m_min = re.search(r'(\d+)\s*(?:minute|minutos|minuto|min|m)s?', text, re.IGNORECASE)
    if m_min:
        minutes = int(m_min.group(1))
        
    m_sec = re.search(r'(\d+)\s*(?:second|segundos|segundo|sec|s)s?', text, re.IGNORECASE)
    if m_sec:
        seconds = int(m_sec.group(1))
        
    if days == 0 and hours == 0 and minutes == 0 and seconds == 0:
        return None
        
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)

def _init_empty_account_record() -> Dict[str, Any]:
    return {
        "weekly_remaining_pct": None,
        "five_hour_remaining_pct": None,
        "weekly_refresh_text": None,
        "weekly_refresh_eta": None,
        "five_hour_refresh_text": None,
        "five_hour_refresh_eta": None,
        "gemini": {
            "weekly_remaining_pct": None,
            "five_hour_remaining_pct": None,
            "weekly_refresh_text": None,
            "weekly_refresh_eta": None,
            "five_hour_refresh_text": None,
            "five_hour_refresh_eta": None,
            "weekly_reset_time": None,
            "five_hour_reset_time": None,
            "disabled": False
        },
        "claude_gpt": {
            "weekly_remaining_pct": None,
            "five_hour_remaining_pct": None,
            "weekly_refresh_text": None,
            "weekly_refresh_eta": None,
            "five_hour_refresh_text": None,
            "five_hour_refresh_eta": None,
            "weekly_reset_time": None,
            "five_hour_reset_time": None,
            "disabled": False
        },
        "models": {},
        "last_updated": None,
        "is_exhausted": False
    }

def load_memory() -> Dict[str, Any]:
    """Loads persistent account memory from disk or returns initialized template."""
    data = None
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read token memory file: {e}")
            
    if not data or not isinstance(data, dict):
        data = {
            "updated_at": None,
            "active_account": None,
            "auto_switch_enabled": True,
            "pinned_account": None,
            "sound_enabled": True,
            "accounts": {}
        }
        
    if "accounts" not in data:
        data["accounts"] = {}
    if "auto_switch_enabled" not in data:
        data["auto_switch_enabled"] = True
    if "pinned_account" not in data:
        data["pinned_account"] = None
    if "sound_enabled" not in data:
        data["sound_enabled"] = True
        
    # Ensure all 3 default accounts exist
    for acc in DEFAULT_ACCOUNTS:
        if acc not in data["accounts"]:
            data["accounts"][acc] = _init_empty_account_record()
        else:
            # Ensure sub-keys exist
            for k in ["gemini", "claude_gpt", "models"]:
                if k not in data["accounts"][acc]:
                    data["accounts"][acc][k] = {} if k == "models" else {
                        "weekly_remaining_pct": None,
                        "five_hour_remaining_pct": None,
                        "weekly_refresh_text": None,
                        "weekly_refresh_eta": None,
                        "five_hour_refresh_text": None,
                        "five_hour_refresh_eta": None,
                        "weekly_reset_time": None,
                        "five_hour_reset_time": None,
                        "disabled": False
                    }
                    
    return data

def save_memory(data: Dict[str, Any]):
    """Saves memory atomically to disk."""
    data["updated_at"] = datetime.now().isoformat()
    temp_file = MEMORY_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp_file, MEMORY_FILE)

def update_account_snapshot(
    email: str,
    weekly_pct: Optional[int] = None,
    five_hour_pct: Optional[int] = None,
    weekly_refresh_text: Optional[str] = None,
    five_hour_refresh_text: Optional[str] = None,
    weekly_reset_time: Optional[int] = None,
    five_hour_reset_time: Optional[int] = None,
    gemini_data: Optional[Dict[str, Any]] = None,
    claude_data: Optional[Dict[str, Any]] = None,
    models_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Updates the persistent snapshot for a specific account with live values and calculated ETAs."""
    data = load_memory()
    now = datetime.now()
    norm_email = email.strip().lower()
    
    target_key = None
    for acc in data["accounts"]:
        if acc.split("@")[0].lower() in norm_email:
            target_key = acc
            break
            
    if not target_key:
        target_key = norm_email
        data["accounts"][target_key] = _init_empty_account_record()
        
    acc_entry = data["accounts"][target_key]
    data["active_account"] = target_key
    acc_entry["last_updated"] = now.isoformat()
    
    # Process Gemini Data
    gem = acc_entry.setdefault("gemini", {})
    if gemini_data:
        for k, v in gemini_data.items():
            if v is not None:
                gem[k] = v
                
    # Fallback to top-level args for Gemini
    if weekly_pct is not None:
        gem["weekly_remaining_pct"] = weekly_pct
    if five_hour_pct is not None:
        gem["five_hour_remaining_pct"] = five_hour_pct
    if weekly_refresh_text:
        gem["weekly_refresh_text"] = weekly_refresh_text
    if five_hour_refresh_text:
        gem["five_hour_refresh_text"] = five_hour_refresh_text
    if weekly_reset_time:
        gem["weekly_reset_time"] = weekly_reset_time
    if five_hour_reset_time:
        gem["five_hour_reset_time"] = five_hour_reset_time
        
    # Calculate Gemini ETAs
    if gem.get("weekly_reset_time"):
        try:
            gem["weekly_refresh_eta"] = datetime.fromtimestamp(gem["weekly_reset_time"]).isoformat()
        except Exception:
            pass
    elif gem.get("weekly_refresh_text"):
        d = parse_refresh_delta(gem["weekly_refresh_text"])
        if d:
            gem["weekly_refresh_eta"] = (now + d).isoformat()
            
    if gem.get("five_hour_reset_time"):
        try:
            gem["five_hour_refresh_eta"] = datetime.fromtimestamp(gem["five_hour_reset_time"]).isoformat()
        except Exception:
            pass
    elif gem.get("five_hour_refresh_text"):
        d = parse_refresh_delta(gem["five_hour_refresh_text"])
        if d:
            gem["five_hour_refresh_eta"] = (now + d).isoformat()
            
    # Process Claude & GPT Data
    c_gpt = acc_entry.setdefault("claude_gpt", {})
    if claude_data:
        for k, v in claude_data.items():
            if v is not None:
                c_gpt[k] = v
                
    # Calculate Claude ETAs
    if c_gpt.get("weekly_reset_time"):
        try:
            c_gpt["weekly_refresh_eta"] = datetime.fromtimestamp(c_gpt["weekly_reset_time"]).isoformat()
        except Exception:
            pass
    elif c_gpt.get("weekly_refresh_text"):
        d = parse_refresh_delta(c_gpt["weekly_refresh_text"])
        if d:
            c_gpt["weekly_refresh_eta"] = (now + d).isoformat()
            
    if c_gpt.get("five_hour_reset_time"):
        try:
            c_gpt["five_hour_refresh_eta"] = datetime.fromtimestamp(c_gpt["five_hour_reset_time"]).isoformat()
        except Exception:
            pass
    elif c_gpt.get("five_hour_refresh_text"):
        d = parse_refresh_delta(c_gpt["five_hour_refresh_text"])
        if d:
            c_gpt["five_hour_refresh_eta"] = (now + d).isoformat()
            
    # Process Models Data
    if models_data:
        acc_entry.setdefault("models", {}).update(models_data)
        
    # Maintain top-level compatibility (defaults to Gemini values)
    acc_entry["weekly_remaining_pct"] = gem.get("weekly_remaining_pct")
    acc_entry["five_hour_remaining_pct"] = gem.get("five_hour_remaining_pct")
    acc_entry["weekly_refresh_text"] = gem.get("weekly_refresh_text")
    acc_entry["weekly_refresh_eta"] = gem.get("weekly_refresh_eta")
    acc_entry["five_hour_refresh_text"] = gem.get("five_hour_refresh_text")
    acc_entry["five_hour_refresh_eta"] = gem.get("five_hour_refresh_eta")
    
    # Determine exhaustion
    is_ex = False
    g_5h = gem.get("five_hour_remaining_pct")
    g_wk = gem.get("weekly_remaining_pct")
    if (g_5h is not None and g_5h <= 0) or (g_wk is not None and g_wk <= 0):
        is_ex = True
        
    acc_entry["is_exhausted"] = is_ex
    save_memory(data)
    return acc_entry

def get_effective_account_status(email: str) -> Dict[str, Any]:
    """
    Returns the account state considering time elapsed since last check.
    If 5-hour ETA or Weekly ETA has elapsed, automatically infers that tokens have refreshed!
    Calculates metrics for both Gemini and Claude groups.
    """
    data = load_memory()
    norm = email.strip().lower()
    target_key = next((k for k in data["accounts"] if k.split("@")[0].lower() in norm), norm)
    acc = data["accounts"].get(target_key, _init_empty_account_record())
    
    now = datetime.now()
    result = json.loads(json.dumps(acc))
    result["email"] = target_key
    result["is_active"] = (data.get("active_account") == target_key)
    
    def process_group(grp: Dict[str, Any]):
        # Check 5h
        if grp.get("five_hour_refresh_eta"):
            try:
                eta = datetime.fromisoformat(grp["five_hour_refresh_eta"])
                grp["five_hour_eta_clock"] = eta.strftime("%H:%M")
                if now >= eta:
                    grp["five_hour_remaining_pct"] = 100
                    grp["five_hour_recharge_in"] = "Recargado (100%)"
                    grp["five_hour_recharged"] = True
                else:
                    rem_sec = max(0, int((eta - now).total_seconds()))
                    grp["five_hour_remaining_seconds"] = rem_sec
                    grp["five_hour_recharge_in"] = f"{rem_sec // 3600}h {(rem_sec % 3600) // 60}m"
            except Exception:
                pass
        # Check Weekly
        if grp.get("weekly_refresh_eta"):
            try:
                w_eta = datetime.fromisoformat(grp["weekly_refresh_eta"])
                grp["weekly_eta_clock"] = w_eta.strftime("%d/%m %H:%M")
                if now >= w_eta:
                    grp["weekly_remaining_pct"] = 100
                    grp["weekly_recharge_in"] = "Recargado (100%)"
                    grp["weekly_recharged"] = True
                else:
                    rem_sec = max(0, int((w_eta - now).total_seconds()))
                    grp["weekly_remaining_seconds"] = rem_sec
                    grp["weekly_recharge_in"] = f"{rem_sec // 86400}d {(rem_sec % 86400) // 3600}h"
            except Exception:
                pass
                
    gem = result.setdefault("gemini", {})
    process_group(gem)
    c_gpt = result.setdefault("claude_gpt", {})
    process_group(c_gpt)
    
    # Sync top-level backward compatibility fields from Gemini
    result["five_hour_remaining_pct"] = gem.get("five_hour_remaining_pct")
    result["weekly_remaining_pct"] = gem.get("weekly_remaining_pct")
    result["five_hour_recharge_in"] = gem.get("five_hour_recharge_in")
    result["weekly_recharge_in"] = gem.get("weekly_recharge_in")
    result["five_hour_eta_clock"] = gem.get("five_hour_eta_clock")
    result["weekly_eta_clock"] = gem.get("weekly_eta_clock")
    result["five_hour_remaining_seconds"] = gem.get("five_hour_remaining_seconds")
    result["weekly_remaining_seconds"] = gem.get("weekly_remaining_seconds")
    
    # Determine effective exhaustion
    is_ex = False
    g_5h = gem.get("five_hour_remaining_pct")
    g_wk = gem.get("weekly_remaining_pct")
    if (g_5h is not None and g_5h <= 0) or (g_wk is not None and g_wk <= 0):
        is_ex = True
    result["is_exhausted"] = is_ex
    
    return result

def evaluate_switch_readiness(current_email: str) -> Tuple[bool, str, Optional[int], Optional[str]]:
    """
    Evaluates which authorized account is optimal to switch to.
    Ranks the other 2 authorized accounts:
    1. Unsampled accounts are prioritized to gather status.
    2. Accounts with available tokens (>0%) ranked by highest remaining tokens.
    3. If all candidates are exhausted, picks the one closest to its recharge ETA.
    Returns: (can_switch, reason, wait_seconds_if_any, best_target_account)
    """
    norm = current_email.strip().lower()
    candidate_emails = [
        acc for acc in DEFAULT_ACCOUNTS
        if acc.split("@")[0].lower() not in norm
    ]
    
    if not candidate_emails:
        return False, "No hay cuentas candidatas configuradas.", None, None
        
    candidates_scores = []
    
    for cand in candidate_emails:
        st = get_effective_account_status(cand)
        
        # 1. Never sampled: top priority
        if st.get("last_updated") is None:
            candidates_scores.append({
                "email": cand,
                "score": 9999,
                "can_use": True,
                "reason": f"Cuenta '{cand}' lista (sin muestreo previo).",
                "wait_sec": None
            })
            continue
            
        g_5h = st.get("gemini", {}).get("five_hour_remaining_pct")
        g_wk = st.get("gemini", {}).get("weekly_remaining_pct")
        c_5h = st.get("claude_gpt", {}).get("five_hour_remaining_pct")
        c_wk = st.get("claude_gpt", {}).get("weekly_remaining_pct")
        
        # Check if tokens available
        tokens_available = (g_5h is None or g_5h > 0) and (g_wk is None or g_wk > 0)
        
        if tokens_available:
            score = (g_5h if g_5h is not None else 100) + (g_wk if g_wk is not None else 100)
            if c_5h is not None:
                score += c_5h * 0.5
            candidates_scores.append({
                "email": cand,
                "score": score,
                "can_use": True,
                "reason": f"Cuenta '{cand}' con tokens disponibles (Gemini 5h: {g_5h}%, Semanal: {g_wk}%).",
                "wait_sec": None
            })
        else:
            # Exhausted: compute minimum wait
            rem_5h = st.get("gemini", {}).get("five_hour_remaining_seconds", 0)
            rem_wk = st.get("gemini", {}).get("weekly_remaining_seconds", 0)
            
            wait_s = None
            if rem_5h > 0 and (g_wk is None or g_wk > 0):
                wait_s = rem_5h
            elif rem_wk > 0 and (g_5h is None or g_5h > 0):
                wait_s = rem_wk
            elif rem_5h > 0 and rem_wk > 0:
                wait_s = min(rem_5h, rem_wk)
                
            wait_s = wait_s or 3600
            score = -wait_s
            candidates_scores.append({
                "email": cand,
                "score": score,
                "can_use": False,
                "reason": f"Cuenta '{cand}' agotada. Recarga estimada en {wait_s // 60}m.",
                "wait_sec": wait_s
            })
            
    # Sort candidates by score descending
    candidates_scores.sort(key=lambda x: x["score"], reverse=True)
    best = candidates_scores[0]
    
    if best["can_use"]:
        return True, best["reason"], None, best["email"]
    else:
        mins = (best["wait_sec"] or 0) // 60
        hrs = mins // 60
        rem_m = mins % 60
        wait_str = f"{hrs}h {rem_m}m" if hrs > 0 else f"{mins}m"
        return False, f"Todas las cuentas alternas están agotadas. Próxima recarga en {wait_str} ({best['email']}).", best["wait_sec"], best["email"]

def format_memory_status_table() -> str:
    """Renders a comprehensive, high-visibility terminal report of all 3 accounts and refresh ETAs."""
    data = load_memory()
    active_email = data.get("active_account") or "Desconocida"
    updated_at = data.get("updated_at") or "Nunca"
    
    updated_str = updated_at
    if updated_at != "Nunca":
        try:
            dt = datetime.fromisoformat(updated_at)
            updated_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
            
    lines = []
    lines.append("================================================================================")
    lines.append("     SISTEMA DE RECONOCIMIENTO & MEMORIA DE TOKENS (4 CUENTAS) - ANTIGRAVITY    ")
    lines.append("================================================================================")
    lines.append(f" Cuenta Activa en Sesion:  {active_email}")
    lines.append(f" Ultima Sincronizacion:    {updated_str}")
    lines.append("--------------------------------------------------------------------------------")
    
    for email in DEFAULT_ACCOUNTS:
        st = get_effective_account_status(email)
        is_active = (st["email"].split("@")[0].lower() in active_email.lower())
        tag = "[ACTIVA]   " if is_active else "[EN ESPERA]"
        lines.append(f" {tag} {email}  [👑 PRO]")
        
        if st.get("last_updated") is None:
            lines.append("   - Gemini Models:      Sin registrar (se actualizara al rotar)")
            lines.append("   - Claude/GPT Models:  Sin registrar")
            lines.append("   - Estado Operativo:   [LISTA] Lista para alternar")
        else:
            gem = st.get("gemini", {})
            g_5h = gem.get("five_hour_remaining_pct")
            g_5h_s = f"{g_5h}%" if g_5h is not None else "--"
            t_5h = gem.get("five_hour_recharge_in") or gem.get("five_hour_refresh_text") or "Sin datos"
            eta_5h = f"({gem.get('five_hour_eta_clock')})" if gem.get('five_hour_eta_clock') else ""
            
            g_wk = gem.get("weekly_remaining_pct")
            g_wk_s = f"{g_wk}%" if g_wk is not None else "--"
            t_wk = gem.get("weekly_recharge_in") or gem.get("weekly_refresh_text") or "Sin datos"
            eta_wk = f"({gem.get('weekly_eta_clock')})" if gem.get('weekly_eta_clock') else ""
            
            lines.append(f"   - Gemini Models:      5h: {g_5h_s:<4} (Recarga: {t_5h} {eta_5h}) | Semanal: {g_wk_s:<4} ({t_wk})")
            
            cgpt = st.get("claude_gpt", {})
            c_5h = cgpt.get("five_hour_remaining_pct")
            c_5h_s = f"{c_5h}%" if c_5h is not None else "--"
            c_wk = cgpt.get("weekly_remaining_pct")
            c_wk_s = f"{c_wk}%" if c_wk is not None else "--"
            t_cwk = cgpt.get("weekly_recharge_in") or cgpt.get("weekly_refresh_text") or "Sin datos"
            lines.append(f"   - Claude/GPT Models:  5h: {c_5h_s:<4} | Semanal: {c_wk_s:<4} (Recarga: {t_cwk})")
            
            # Models breakdown if available
            models = st.get("models", {})
            if models:
                m_parts = []
                for m_name, m_info in models.items():
                    frac = m_info.get("remaining_fraction")
                    if frac is not None:
                        pct = int(round(frac * 100))
                        short_name = m_name.replace("claude-", "c-").replace("gemini-", "g-")
                        m_parts.append(f"{short_name}:{pct}%")
                if m_parts:
                    lines.append(f"   - Modelos En Vivo:    {' '.join(m_parts[:4])}")
                    
            # Operational status
            if st.get("is_exhausted"):
                op_status = "[X] AGOTADA (0%) - Esperando recarga"
            elif (g_5h is not None and g_5h <= 15) or (g_wk is not None and g_wk <= 15):
                op_status = "[!] CUOTA BAJA - Proxima a agotarse"
            else:
                op_status = "[OK] OPERATIVA Y DISPONIBLE"
            lines.append(f"   - Estado Operativo:   {op_status}")
            
        lines.append("")
        
    lines.append("--------------------------------------------------------------------------------")
    can_switch, reason, wait_secs, best_target = evaluate_switch_readiness(active_email)
    lines.append(" EVALUACION DE AUTO-ROTACION:")
    if can_switch:
        lines.append(f" [OK] {reason}")
        lines.append(f"      Siguiente cuenta objetivo recomendada: {best_target}")
    else:
        lines.append(f" [!] {reason}")
        lines.append("      (El sistema retendra la alternancia para evitar bucle entre cuentas agotadas)")
    lines.append("================================================================================")
    
    return "\n".join(lines)

# =============================================================================
# Control Functions: Auto-Switch, Pinning, Sound & Recharge Watcher
# =============================================================================

def is_auto_switch_enabled() -> bool:
    mem = load_memory()
    return bool(mem.get("auto_switch_enabled", True))

def set_auto_switch_enabled(enabled: bool) -> bool:
    mem = load_memory()
    mem["auto_switch_enabled"] = bool(enabled)
    save_memory(mem)
    return bool(enabled)

def get_pinned_account() -> Optional[str]:
    mem = load_memory()
    return mem.get("pinned_account")

def set_pinned_account(email: Optional[str]) -> Optional[str]:
    mem = load_memory()
    mem["pinned_account"] = email.strip().lower() if email else None
    save_memory(mem)
    return mem["pinned_account"]

def is_sound_enabled() -> bool:
    mem = load_memory()
    return bool(mem.get("sound_enabled", True))

def set_sound_enabled(enabled: bool) -> bool:
    mem = load_memory()
    mem["sound_enabled"] = bool(enabled)
    save_memory(mem)
    return bool(enabled)

def check_recharge_notifications() -> List[str]:
    """
    Checks if any previously exhausted accounts have finished their 5h countdown.
    Marks them as recharged and returns the list of newly recharged emails.
    """
    mem = load_memory()
    recharged = []
    now = datetime.now()
    updated = False
    
    for email, acc in mem.get("accounts", {}).items():
        if acc.get("is_exhausted"):
            eta_str = acc.get("five_hour_refresh_eta")
            if eta_str:
                try:
                    eta_dt = datetime.fromisoformat(eta_str)
                    if now >= eta_dt:
                        acc["is_exhausted"] = False
                        gem = acc.setdefault("gemini", {})
                        gem["five_hour_remaining_pct"] = 100
                        gem["five_hour_refresh_text"] = "Recargado (100%)"
                        recharged.append(email)
                        updated = True
                except Exception:
                    pass
    if updated:
        save_memory(mem)
    return recharged
