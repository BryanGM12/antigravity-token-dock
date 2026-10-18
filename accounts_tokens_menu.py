"""
accounts_tokens_menu.py
======================
Modulo autonomo de visualizacion de cuentas y tokens de Antigravity.
Proporciona exclusivamente el nuevo menu de cuentas y el estado de tokens en tiempo real.
Modo de ejecucion: Consola (ASCII), JSON (--json), o Micro-HUD Web (--serve).
"""

import argparse
import datetime
import html
import http.server
import json
import os
import re
import socketserver
import sys
import threading
from typing import Any, Dict, List, Optional

# Asegurar soporte UTF-8 en consola de Windows
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# -----------------------------------------------------------------------------
# Constantes y Configuracion Oficial
# -----------------------------------------------------------------------------

PRECONFIGURED_ACCOUNTS: List[Dict[str, str]] = [
    {"id": "primary_dev", "name": "primary_dev", "email": "primary.dev@gmail.com"},
    {"id": "backup_worker", "name": "backup_worker", "email": "backup.worker@gmail.com"},
    {"id": "ai_architect", "name": "ai_architect", "email": "ai.architect@gmail.com"},
    {"id": "reviewer_pro", "name": "reviewer_pro", "email": "reviewer.pro@gmail.com"},
    {"id": "qa_engineer", "name": "qa_engineer", "email": "qa.engineer@gmail.com"},
    {"id": "devops_runner", "name": "devops_runner", "email": "devops.runner@gmail.com"},
    {"id": "data_analyst", "name": "data_analyst", "email": "data.analyst@gmail.com"},
]

ALLOWED_GEMINI_MODELS: List[str] = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
]

TOKEN_MEMORY_PATHS: List[str] = [
    os.path.join(os.path.expanduser("~"), ".gemini", "token_memory.json"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "token_memory.json"),
]

ACCOUNT_TOKENS_PATHS: List[str] = [
    os.path.join(os.path.expanduser("~"), ".gemini", "account_tokens.json"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "account_tokens.json"),
]

PROFILES_DIR: str = os.path.expanduser("~/.gemini/profiles")
POOL_STATUS_FILE: str = os.path.expanduser("~/.gemini/pool_status.json")
ACTIVE_ACCOUNT_FILE: str = os.path.expanduser("~/.gemini/active_account.json")


# -----------------------------------------------------------------------------
# Lector Determinista de Estado de Tokens
# -----------------------------------------------------------------------------

def load_raw_token_state() -> Dict[str, Any]:
    """
    Carga de forma determinista el estado de tokens desde token_memory.json
    con fallback completo a account_tokens.json, ~/.gemini/pool_status.json,
    ~/.gemini/active_account.json y carpetas de perfiles en ~/.gemini/profiles/.
    """
    raw_state: Dict[str, Any] = {
        "active_account": "",
        "accounts": {},
        "tokens": {},
    }

    # 1. Cuenta activa autoritativa desde ~/.gemini/active_account.json
    if os.path.isfile(ACTIVE_ACCOUNT_FILE):
        try:
            with open(ACTIVE_ACCOUNT_FILE, "r", encoding="utf-8") as af:
                act_data = json.load(af)
                if isinstance(act_data, dict):
                    raw_state["active_account"] = act_data.get("active_email") or act_data.get("active_alias") or ""
        except Exception:
            pass

    # 2. Cargar primero pool_status.json (fuente viva y actualizada de cuotas Google API)
    if os.path.isfile(POOL_STATUS_FILE):
        try:
            with open(POOL_STATUS_FILE, "r", encoding="utf-8") as pf:
                pool_data = json.load(pf)
                if isinstance(pool_data, dict) and isinstance(pool_data.get("accounts"), dict):
                    for p_alias, p_acc in pool_data["accounts"].items():
                        if isinstance(p_acc, dict):
                            p_email = str(p_acc.get("email") or "").strip().lower()
                            key = p_email or p_alias.strip().lower()
                            rem_5h = int(round(float(p_acc.get("rem_5h", 1.0)) * 100))
                            rem_wk = int(round(float(p_acc.get("rem_weekly", 1.0)) * 100))
                            raw_reset_5h = p_acc.get("reset_5h")
                            raw_reset_wk = p_acc.get("reset_weekly")

                            five_hour_refresh = "Recargado (100%)"
                            if rem_5h < 100:
                                five_hour_refresh = format_relative_time(raw_reset_5h, fallback="3h")

                            weekly_refresh = "6 dias"
                            if raw_reset_wk:
                                weekly_refresh = format_relative_time(raw_reset_wk, fallback="6 dias")

                            acc_entry = {
                                "five_hour_remaining_pct": rem_5h,
                                "weekly_remaining_pct": rem_wk,
                                "five_hour_refresh_text": five_hour_refresh,
                                "weekly_refresh_text": weekly_refresh,
                                "gemini": {
                                    "five_hour_remaining_pct": rem_5h,
                                    "weekly_remaining_pct": rem_wk,
                                }
                            }
                            if rem_5h >= 100:
                                acc_entry["five_hour_refresh_text"] = "Recargado (100%)"
                                acc_entry["gemini"]["five_hour_refresh_text"] = "Recargado (100%)"
                            raw_state["accounts"][key] = acc_entry
                            if p_alias:
                                raw_state["accounts"][p_alias.strip().lower()] = acc_entry
                            if p_email:
                                raw_state["accounts"][p_email.strip().lower()] = acc_entry
        except Exception:
            pass

    # 3. Complementar con token_memory.json (tokens y modelos si no existen)
    for file_path in TOKEN_MEMORY_PATHS:
        if file_path and os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        if not raw_state["active_account"] and data.get("active_account"):
                            raw_state["active_account"] = str(data["active_account"]).strip()
                        if isinstance(data.get("accounts"), dict):
                            for acc_k, acc_v in data["accounts"].items():
                                if acc_k not in raw_state["accounts"]:
                                    raw_state["accounts"][acc_k] = acc_v
                                else:
                                    # Solo agregar campos que falten sin pisar cuotas vivas
                                    for sub_k, sub_v in acc_v.items():
                                        if sub_k not in raw_state["accounts"][acc_k]:
                                            raw_state["accounts"][acc_k][sub_k] = sub_v
                        if isinstance(data.get("tokens"), dict):
                            raw_state["tokens"].update(data["tokens"])
                        break
            except Exception:
                continue

    # 2. Cargar account_tokens.json (mapeo directo de email -> access_token OAuth)
    for tok_path in ACCOUNT_TOKENS_PATHS:
        if tok_path and os.path.isfile(tok_path):
            try:
                with open(tok_path, "r", encoding="utf-8") as f:
                    tok_data = json.load(f)
                    if isinstance(tok_data, dict):
                        for k, v in tok_data.items():
                            if isinstance(v, str) and v.startswith("ya29"):
                                k_clean = k.strip().lower()
                                raw_state["tokens"][k_clean] = v.strip()
                                if k_clean not in raw_state["accounts"]:
                                    raw_state["accounts"][k_clean] = {"token": v.strip()}
                                else:
                                    raw_state["accounts"][k_clean]["token"] = v.strip()
                        break
            except Exception:
                continue

    # 3. Fallback a carpetas de perfiles en ~/.gemini/profiles/
    if os.path.isdir(PROFILES_DIR):
        try:
            for entry in os.listdir(PROFILES_DIR):
                profile_dir = os.path.join(PROFILES_DIR, entry)
                if not os.path.isdir(profile_dir):
                    continue
                alias = entry.strip().lower()
                oauth_file = os.path.join(profile_dir, ".gemini", "oauth_creds.json")
                if not os.path.isfile(oauth_file):
                    oauth_file = os.path.join(profile_dir, "oauth_creds.json")

                if os.path.isfile(oauth_file):
                    try:
                        with open(oauth_file, "r", encoding="utf-8") as of:
                            oc_data = json.load(of)
                            if isinstance(oc_data, dict):
                                email = str(oc_data.get("verified_email") or "").strip().lower()
                                token = str(oc_data.get("access_token") or "").strip()
                                if token:
                                    if email:
                                        raw_state["tokens"][email] = token
                                    raw_state["tokens"][alias] = token
                                    target_key = email or alias
                                    if target_key not in raw_state["accounts"]:
                                        raw_state["accounts"][target_key] = {"token": token}
                                    else:
                                        raw_state["accounts"][target_key]["token"] = token
                    except Exception:
                        pass
        except Exception:
            pass

    # 4. Fallback de cuotas desde ~/.gemini/pool_status.json
    if os.path.isfile(POOL_STATUS_FILE):
        try:
            with open(POOL_STATUS_FILE, "r", encoding="utf-8") as pf:
                pool_data = json.load(pf)
                if isinstance(pool_data, dict) and isinstance(pool_data.get("accounts"), dict):
                    for p_alias, p_acc in pool_data["accounts"].items():
                        if isinstance(p_acc, dict):
                            p_email = str(p_acc.get("email") or "").strip().lower()
                            key = p_email or p_alias.strip().lower()
                            rem_5h = int(round(float(p_acc.get("rem_5h", 1.0)) * 100))
                            rem_wk = int(round(float(p_acc.get("rem_weekly", 1.0)) * 100))
                            existing = raw_state["accounts"].get(key, {})
                            existing.update({
                                "five_hour_remaining_pct": rem_5h,
                                "weekly_remaining_pct": rem_wk,
                                "five_hour_refresh_text": p_acc.get("reset_5h") or "Recargado (100%)",
                                "weekly_refresh_text": "6 dias",
                            })
                            if isinstance(existing.get("gemini"), dict):
                                existing["gemini"]["five_hour_remaining_pct"] = rem_5h
                                existing["gemini"]["weekly_remaining_pct"] = rem_wk
                            raw_state["accounts"][key] = existing
                            if p_alias:
                                raw_state["accounts"][p_alias.strip().lower()] = existing
                            if p_email:
                                raw_state["accounts"][p_email.strip().lower()] = existing
                            if rem_5h >= 100:
                                existing["five_hour_recharge_in"] = ""
                                existing["five_hour_refresh_text"] = "Recargado (100%)"
                                if isinstance(existing.get("gemini"), dict):
                                    existing["gemini"]["five_hour_recharge_in"] = ""
                                    existing["gemini"]["five_hour_refresh_text"] = "Recargado (100%)"
        except Exception:
            pass

    # 5. Fallback de cuenta activa desde ~/.gemini/active_account.json
    if not raw_state.get("active_account") and os.path.isfile(ACTIVE_ACCOUNT_FILE):
        try:
            with open(ACTIVE_ACCOUNT_FILE, "r", encoding="utf-8") as af:
                act_data = json.load(af)
                if isinstance(act_data, dict):
                    raw_state["active_account"] = act_data.get("active_email") or act_data.get("active_alias") or ""
        except Exception:
            pass

    if not raw_state.get("active_account"):
        raw_state["active_account"] = "primary.dev@gmail.com"

    return raw_state


def format_relative_time(val: str, fallback: str = "N/A") -> str:
    """Convierte marcas de tiempo ISO 8601 a duraciones relativas humanas (ej. 2h 15m, 5 dias)."""
    if not val:
        return fallback
    val_str = str(val).strip()
    if not val_str or val_str.lower().startswith("recargado"):
        return fallback

    if val_str.endswith("Z"):
        val_clean = val_str[:-1] + "+00:00"
    else:
        val_clean = val_str

    try:
        from datetime import datetime, timezone
        target_dt = datetime.fromisoformat(val_clean)
        now_dt = datetime.now(timezone.utc)
        diff_sec = int((target_dt - now_dt).total_seconds())
        if diff_sec <= 0:
            return "Listo"
        days = diff_sec // 86400
        hours = (diff_sec % 86400) // 3600
        minutes = (diff_sec % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h" if hours > 0 else f"{days} dias"
        if hours > 0:
            return f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
        return f"{minutes}m"
    except Exception:
        return val_str or fallback


def format_recharge_string(pct: int, recharge_or_refresh: str = "", secondary_text: str = "") -> str:
    """Formatea la cadena de recarga para cuota de 5 horas priorizando estado de 100% y luego cuentas regresivas."""
    if pct >= 100:
        return "Recargado (100%)"

    t1 = (recharge_or_refresh or "").strip()
    t2 = (secondary_text or "").strip()

    time_candidate = ""
    for cand in (t1, t2):
        if cand and not cand.lower().startswith("recargado") and not cand.startswith("0s"):
            if "T" in cand and ("Z" in cand or "+" in cand):
                cand = format_relative_time(cand, fallback=cand)
            time_candidate = cand
            break

    if time_candidate:
        return time_candidate
    if t1:
        if "T" in t1 and ("Z" in t1 or "+" in t1):
            return format_relative_time(t1, fallback=t1)
        return t1
    if t2:
        if "T" in t2 and ("Z" in t2 or "+" in t2):
            return format_relative_time(t2, fallback=t2)
        return t2
    return "N/A"


def resolve_accounts_state() -> Dict[str, Any]:
    """
    Construye el estado unificado y estructurado de las 7 cuentas preconfiguradas
    y los modelos autorizados de Google Gemini.
    """
    raw_data = load_raw_token_state()
    active_target_raw = str(raw_data.get("active_account") or "primary.dev@gmail.com").strip().lower()
    accounts_map = raw_data.get("accounts", {})
    if not isinstance(accounts_map, dict):
        accounts_map = {}
    tokens_map = raw_data.get("tokens", {})
    if not isinstance(tokens_map, dict):
        tokens_map = {}

    processed_accounts: List[Dict[str, Any]] = []

    for base in PRECONFIGURED_ACCOUNTS:
        email = base["email"].lower().strip()
        acc_id = base["id"]
        acc_name = base["name"]

        # Localizar datos de la cuenta en el mapa de cuentas (coincidencia exacta)
        acc_entry = None
        if email in accounts_map:
            acc_entry = accounts_map[email]
        elif email.lower() in accounts_map:
            acc_entry = accounts_map[email.lower()]
        elif acc_id in accounts_map:
            acc_entry = accounts_map[acc_id]
        elif acc_id.lower() in accounts_map:
            acc_entry = accounts_map[acc_id.lower()]

        if not acc_entry:
            for k, v in accounts_map.items():
                k_clean = str(k).strip().lower()
                if k_clean == email or k_clean == acc_id:
                    acc_entry = v
                    break

        gemini_sub = acc_entry.get("gemini", {}) if isinstance(acc_entry, dict) else {}

        # 1. Cuota de 5 horas
        raw_5h = None
        if isinstance(acc_entry, dict):
            raw_5h = acc_entry.get("five_hour_remaining_pct")
            if raw_5h is None and isinstance(gemini_sub, dict):
                raw_5h = gemini_sub.get("five_hour_remaining_pct")

        try:
            five_h_pct = int(round(float(str(raw_5h).replace("%", "")))) if raw_5h is not None else 100
        except (ValueError, TypeError):
            five_h_pct = 100

        # Texto y tiempo de recarga de 5 horas
        five_h_recharge = ""
        five_h_refresh = ""
        if isinstance(acc_entry, dict):
            five_h_recharge = acc_entry.get("five_hour_recharge_in") or ""
            five_h_refresh = acc_entry.get("five_hour_refresh_text") or ""
            if isinstance(gemini_sub, dict):
                if not five_h_recharge:
                    five_h_recharge = gemini_sub.get("five_hour_recharge_in") or ""
                if not five_h_refresh:
                    five_h_refresh = gemini_sub.get("five_hour_refresh_text") or ""

        five_h_formatted_refresh = format_recharge_string(five_h_pct, five_h_recharge, five_h_refresh)

        # 2. Cuota semanal
        raw_wk = None
        if isinstance(acc_entry, dict):
            raw_wk = acc_entry.get("weekly_remaining_pct")
            if raw_wk is None and isinstance(gemini_sub, dict):
                raw_wk = gemini_sub.get("weekly_remaining_pct")

        try:
            weekly_pct = int(round(float(str(raw_wk).replace("%", "")))) if raw_wk is not None else 100
        except (ValueError, TypeError):
            weekly_pct = 100

        weekly_refresh = ""
        if isinstance(acc_entry, dict):
            weekly_refresh = acc_entry.get("weekly_refresh_text") or acc_entry.get("weekly_recharge_in") or ""
            if not weekly_refresh and isinstance(gemini_sub, dict):
                weekly_refresh = gemini_sub.get("weekly_refresh_text") or gemini_sub.get("weekly_recharge_in") or ""
        if not weekly_refresh:
            weekly_refresh = "6 dias"

        # REGLA ESTRICTA: La cuota semanal se muestra UNICAMENTE si es <= 15%
        show_weekly_warning = (weekly_pct <= 15)
        weekly_warning_text = f"! Cuota Semanal Critica: {weekly_pct}%" if show_weekly_warning else None

        # Evaluacion de cuenta activa (soporta email o alias)
        is_active = (email == active_target_raw or acc_id == active_target_raw)
        status_tag = "[ACTIVA]" if is_active else ""
        active_symbol = "*" if is_active else " "

        # 3. Modelos autorizados: EXCLUSIVAMENTE Google Gemini
        models_data: Dict[str, Dict[str, Any]] = {}
        raw_models = acc_entry.get("models", {}) if isinstance(acc_entry, dict) else {}
        if not raw_models and isinstance(gemini_sub, dict):
            raw_models = gemini_sub.get("models", {})
        if not isinstance(raw_models, dict):
            raw_models = {}

        for model_id in ALLOWED_GEMINI_MODELS:
            m_pct = five_h_pct
            for mk, mv in raw_models.items():
                is_match = False
                if mk == model_id:
                    is_match = True
                elif model_id == "gemini-3.5-flash" and "lite" in mk:
                    is_match = False
                elif mk.startswith(model_id) or model_id in mk:
                    is_match = True

                if is_match:
                    if isinstance(mv, dict):
                        frac = mv.get("remaining_fraction")
                        if frac is not None:
                            try:
                                m_pct = int(round(float(frac) * 100))
                            except (ValueError, TypeError):
                                pass
                    break

            models_data[model_id] = {
                "model_id": model_id,
                "provider": "Google Gemini",
                "remaining_pct": m_pct,
                "refresh_text": five_h_formatted_refresh,
            }

        quota_summary = f"5h: {five_h_pct}% | Recarga: {five_h_formatted_refresh}"

        # 4. Token OAuth de la cuenta (Access Token)
        token_str = ""
        if email in tokens_map:
            token_str = tokens_map[email]
        elif acc_id in tokens_map:
            token_str = tokens_map[acc_id]
        elif isinstance(acc_entry, dict):
            token_str = acc_entry.get("token") or acc_entry.get("access_token") or ""

        token_str = str(token_str).strip()
        has_token = bool(token_str and token_str.startswith("ya29"))
        token_preview = f"{token_str[:12]}...{token_str[-6:]}" if len(token_str) > 18 else (token_str if token_str else "N/A")

        processed_accounts.append({
            "id": acc_id,
            "name": acc_name,
            "email": email,
            "is_active": is_active,
            "active_symbol": active_symbol,
            "status_tag": status_tag,
            "five_hour_remaining_pct": five_h_pct,
            "five_hour_refresh_text": five_h_formatted_refresh,
            "weekly_remaining_pct": weekly_pct,
            "weekly_refresh_text": weekly_refresh,
            "show_weekly_warning": show_weekly_warning,
            "weekly_warning_text": weekly_warning_text,
            "quota_summary": quota_summary,
            "token": {
                "access_token": token_str,
                "token_preview": token_preview,
                "has_token": has_token,
                "token_type": "Bearer",
            },
            "access_token": token_str,
            "token_preview": token_preview,
            "has_token": has_token,
            "models": models_data,
        })

    return {
        "updated_at": datetime.datetime.now().isoformat(),
        "active_account": active_target_raw,
        "gemini_models": ALLOWED_GEMINI_MODELS,
        "accounts": processed_accounts,
    }


# -----------------------------------------------------------------------------
# Renderizador en Consola (Tabla ASCII Limpia)
# -----------------------------------------------------------------------------

def render_console_table(state: Dict[str, Any]) -> str:
    """Genera la representacion visual en texto/ASCII limpio para terminal."""
    active_email = state.get("active_account", "")
    accounts = state.get("accounts", [])
    active_acc = next((a for a in accounts if a.get("is_active")), accounts[0] if accounts else None)

    active_acc_label = f"{active_acc['name']} ({active_acc['email']}) [ACTIVA]" if active_acc else active_email
    gemini_models_str = ", ".join(state.get("gemini_models", []))

    lines = []
    lines.append("==========================================================================================")
    lines.append("                           ANTIGRAVITY ACCOUNTS & TOKENS MENU                             ")
    lines.append("==========================================================================================")
    lines.append(f" Cuenta Activa            : {active_acc_label}")
    lines.append(f" Modelos Gemini Permitidos: {gemini_models_str}")
    lines.append("------------------------------------------------------------------------------------------")
    lines.append(" EST | ID          | EMAIL                       | 5H CUOTA (RECARGA)      | SEMANAL (RESETEO)")
    lines.append("-----+-------------+-----------------------------+-------------------------+------------------------")

    for acc in accounts:
        symbol = f"[{acc['active_symbol']}]" if acc["is_active"] else "   "
        aid = f"{acc['id']:<11}"
        aemail = f"{acc['email']:<27}"
        quota_str = f"{acc['quota_summary']:<23}"
        
        wk_str = f"Sem: {acc['weekly_remaining_pct']}% ({acc['weekly_refresh_text']})"
        if acc["show_weekly_warning"]:
            wk_str = f"! Sem: {acc['weekly_remaining_pct']}% (CRITICA)"
        wk_str_fmt = f"{wk_str:<24}"

        lines.append(f" {symbol} | {aid} | {aemail} | {quota_str} | {wk_str_fmt}")

    lines.append("==========================================================================================")

    # Bloque de la tarjeta de modelos Gemini del foco activo
    if active_acc:
        lines.append(f" [ Tarjeta de Modelos Gemini: {active_acc['name']} ({active_acc['email']}) ]")
        lines.append(f"  * Cuota 5 Horas : {active_acc['five_hour_remaining_pct']}% (Recarga: {active_acc['five_hour_refresh_text']})")
        lines.append(f"  * Cuota Semanal : {active_acc['weekly_remaining_pct']}% (Reseteo: {active_acc['weekly_refresh_text']})")
        if active_acc["show_weekly_warning"]:
            lines.append(f"  * ADVERTENCIA   : ! Cuota Semanal Critica <= 15% ({active_acc['weekly_remaining_pct']}%)")
        lines.append("  * Modelos Google Gemini Autorizados:")
        for m_id, m_data in active_acc.get("models", {}).items():
            lines.append(f"    => {m_id:<23}: {m_data['remaining_pct']}% disponible")
        lines.append("------------------------------------------------------------------------------------------")
        lines.append(" [ Tokens OAuth de Cuentas ]")
        for acc in accounts:
            tok_status = f"{acc['token_preview']:<23} [ACTIVO]" if acc["has_token"] else "No disponible"
            lines.append(f"  * {acc['id']:<11} ({acc['email']:<27}): {tok_status}")
        lines.append("==========================================================================================")

    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Micro-HUD Web (Servidor HTTP Nativo y de Solo Lectura)
# -----------------------------------------------------------------------------

def build_hud_html(state: Dict[str, Any]) -> str:
    """Genera el HTML/CSS exacto del menu desplegable nativo de Antigravity en modo de solo lectura."""
    state_json = json.dumps(state, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Antigravity - Menu de Cuentas y Tokens</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background-color: #121212;
            color: #cccccc;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            font-size: 13px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-start;
            min-height: 100vh;
            padding: 30px 16px;
        }}
        .hud-header {{
            text-align: center;
            margin-bottom: 20px;
        }}
        .hud-header h1 {{
            font-size: 16px;
            font-weight: 600;
            color: #ffffff;
            letter-spacing: 0.5px;
        }}
        .hud-header p {{
            font-size: 11px;
            color: #71717a;
            margin-top: 4px;
        }}
        /* Contenedor del Dropdown Nativo */
        .antigravity-dropdown-frame {{
            background: #1a1a1a;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
            width: 100%;
            max-width: 420px;
            padding: 8px 0;
            user-select: none;
        }}
        .antigravity-quota-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 14px 4px 14px;
        }}
        .antigravity-quota-title-wrap {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            font-weight: 600;
            color: #ffffff;
        }}
        .antigravity-info-icon {{
            display: inline-flex;
            align-items: center;
            color: #71717a;
        }}
        .antigravity-account-active-tag {{
            font-size: 11px;
            color: #888888;
            background: rgba(255, 255, 255, 0.05);
            padding: 2px 8px;
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            max-width: 210px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        /* Altura estable fija de 128px para prevenir parpadeos o saltos */
        #ag-gemini-card-container {{
            height: 128px;
            min-height: 128px;
            max-height: 128px;
            box-sizing: border-box;
            overflow: hidden;
            margin: 4px 10px 8px 10px;
        }}
        .antigravity-gemini-card {{
            background: #101010;
            border: 1px solid #282828;
            border-radius: 8px;
            padding: 10px 14px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            height: 128px;
            min-height: 128px;
            max-height: 128px;
            box-sizing: border-box;
            overflow: hidden;
        }}
        .antigravity-limit-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }}
        .antigravity-limit-info {{
            display: flex;
            flex-direction: column;
            flex: 1;
            min-width: 0;
        }}
        .antigravity-limit-title {{
            font-size: 12.5px;
            font-weight: 500;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .antigravity-limit-desc {{
            font-size: 11px;
            color: #888888;
            margin-top: 2px;
            line-height: 1.3;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .antigravity-limit-stat {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-shrink: 0;
        }}
        .antigravity-limit-pct {{
            font-size: 14px;
            font-weight: 600;
            color: #ffffff;
            min-width: 36px;
            text-align: right;
        }}
        .antigravity-limit-pct.is-warning {{
            color: #f85149;
        }}
        .antigravity-ring-wrap {{
            width: 26px;
            height: 26px;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .antigravity-ring-svg {{
            transform: rotate(-90deg);
            display: block;
        }}
        .antigravity-ring-bg {{
            fill: none;
            stroke: rgba(255, 255, 255, 0.12);
            stroke-width: 2.8;
        }}
        .antigravity-ring-fill {{
            fill: none;
            stroke-width: 2.8;
            stroke-linecap: round;
            stroke: #3fb950;
        }}
        .antigravity-card-row-divider {{
            height: 1px;
            background: rgba(255, 255, 255, 0.08);
            margin: 6px 0;
        }}
        .antigravity-models-tag-row {{
            display: flex;
            align-items: center;
            gap: 4px;
            margin-top: 6px;
            flex-wrap: nowrap;
            overflow: hidden;
        }}
        .antigravity-model-pill {{
            font-size: 10px;
            background: rgba(255, 255, 255, 0.06);
            color: #aaaaaa;
            padding: 1px 5px;
            border-radius: 4px;
            white-space: nowrap;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }}
        .antigravity-section-label {{
            font-size: 11px;
            font-weight: 600;
            color: #71717a;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 8px 14px 4px 14px;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .antigravity-acc-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            padding: 7px 14px;
            background: transparent;
            border: none;
            cursor: pointer;
            outline: none;
            text-align: left;
            transition: background 0.1s ease;
        }}
        .antigravity-acc-row:hover {{
            background: rgba(255, 255, 255, 0.06);
        }}
        .antigravity-acc-row.is-active {{
            background: rgba(255, 255, 255, 0.03);
        }}
        .antigravity-acc-left {{
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
            flex: 1;
        }}
        .antigravity-acc-check {{
            width: 14px;
            font-size: 13px;
            font-weight: 700;
            color: #3fb950;
            text-align: center;
            flex-shrink: 0;
            line-height: 1;
        }}
        .antigravity-acc-name-group {{
            display: flex;
            flex-direction: column;
            min-width: 0;
        }}
        .antigravity-acc-name {{
            font-size: 12.5px;
            font-weight: 500;
            color: #dddddd;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .antigravity-acc-email {{
            font-size: 11px;
            color: #71717a;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .antigravity-acc-right {{
            display: flex;
            align-items: center;
            gap: 6px;
            flex-shrink: 0;
        }}
        .antigravity-acc-active-badge {{
            font-size: 10px;
            font-weight: 600;
            color: #3fb950;
            background: rgba(63, 185, 80, 0.12);
            padding: 1px 6px;
            border-radius: 10px;
            border: 1px solid rgba(63, 185, 80, 0.3);
        }}
        .antigravity-acc-weekly-warning {{
            font-size: 10px;
            font-weight: 600;
            color: #f85149;
            background: rgba(248, 81, 73, 0.14);
            padding: 1px 5px;
            border-radius: 4px;
            border: 1px solid rgba(248, 81, 73, 0.3);
        }}
        .antigravity-acc-quota-badge {{
            font-size: 11px;
            font-weight: 500;
            color: #aaaaaa;
            background: rgba(255, 255, 255, 0.05);
            padding: 1px 6px;
            border-radius: 4px;
        }}
        .antigravity-acc-token-badge {{
            font-size: 10px;
            color: #888888;
            background: rgba(255, 255, 255, 0.04);
            padding: 1px 5px;
            border-radius: 4px;
            border: 1px solid rgba(255, 255, 255, 0.07);
            font-family: monospace;
        }}
        .antigravity-hud-footer {{
            padding: 8px 14px 4px 14px;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            color: #666666;
        }}
    </style>
</head>
<body>
    <div class="hud-header">
        <h1>Antigravity Accounts & Tokens Menu</h1>
        <p>Monitoreo Determinista en Tiempo Real (Solo Lectura)</p>
    </div>

    <div class="antigravity-dropdown-frame">
        <div class="antigravity-quota-header">
            <div class="antigravity-quota-title-wrap">
                <span>Gemini Models</span>
                <span class="antigravity-info-icon" title="Cuotas de Modelos Google Gemini">
                    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"/>
                        <line x1="12" y1="16" x2="12" y2="12"/>
                        <line x1="12" y1="8" x2="12.01" y2="8"/>
                    </svg>
                </span>
            </div>
            <span class="antigravity-account-active-tag" id="ag-focused-account-tag">...</span>
        </div>

        <!-- Tarjeta de Altura Estable (128px) -->
        <div id="ag-gemini-card-container"></div>

        <div class="antigravity-section-label">Cuentas Disponibles (7)</div>
        <div id="ag-accounts-list-container"></div>

        <div class="antigravity-hud-footer">
            <span id="ag-last-updated-text">Actualizado: --</span>
            <span>Modo: Consulta / Monitoreo</span>
        </div>
    </div>

    <script>
        const initialData = {state_json};
        let currentData = initialData;
        let focusedEmail = (initialData.active_account || 'primary.dev@gmail.com').toLowerCase().trim();

        function renderHUD(data) {{
            currentData = data;
            const accounts = data.accounts || [];
            const activeEmail = (data.active_account || '').toLowerCase().trim();
            const tagEl = document.getElementById('ag-focused-account-tag');
            const cardContainer = document.getElementById('ag-gemini-card-container');
            const listContainer = document.getElementById('ag-accounts-list-container');
            const updatedEl = document.getElementById('ag-last-updated-text');

            if (updatedEl && data.updated_at) {{
                try {{
                    const d = new Date(data.updated_at);
                    updatedEl.textContent = 'Actualizado: ' + d.toLocaleTimeString();
                }} catch (_e) {{
                    updatedEl.textContent = 'Actualizado: ' + data.updated_at;
                }}
            }}

            const focusedAcc = accounts.find(a => a.email.toLowerCase() === focusedEmail) || accounts[0] || null;
            if (tagEl && focusedAcc) {{
                tagEl.textContent = focusedAcc.name + ' (' + focusedAcc.email + ')';
            }}

            // Renderizar la tarjeta Gemini Models con altura fija de 128px
            if (cardContainer && focusedAcc) {{
                cardContainer.innerHTML = '';
                const card = document.createElement('div');
                card.className = 'antigravity-gemini-card';

                const r = 11;
                const circ = 2 * Math.PI * r;
                const fhPct = focusedAcc.five_hour_remaining_pct ?? 100;
                const wkPct = focusedAcc.weekly_remaining_pct ?? 100;

                // REGLA ESTRICTA: La fila de Weekly Limit se muestra UNICAMENTE si wkPct <= 15
                if (focusedAcc.show_weekly_warning && wkPct <= 15) {{
                    const wkRow = document.createElement('div');
                    wkRow.className = 'antigravity-limit-row';
                    const wkReset = focusedAcc.weekly_refresh_text || 'N/A';

                    wkRow.innerHTML = `
                        <div class="antigravity-limit-info">
                            <div class="antigravity-limit-title">
                                <span>Weekly Limit Remaining</span>
                                <span style="font-size:10px;font-weight:700;color:#f85149;background:rgba(248,81,73,0.18);padding:1px 5px;border-radius:4px;">! Cuota Critica</span>
                            </div>
                            <div class="antigravity-limit-desc" style="color:#f85149;">
                                Resetea en ${{wkReset}}
                            </div>
                        </div>
                        <div class="antigravity-limit-stat">
                            <span class="antigravity-limit-pct is-warning">${{wkPct}}%</span>
                            <div class="antigravity-ring-wrap">
                                <svg width="26" height="26" viewBox="0 0 28 28" class="antigravity-ring-svg">
                                    <circle class="antigravity-ring-bg" cx="14" cy="14" r="11" />
                                    <circle class="antigravity-ring-fill" cx="14" cy="14" r="11"
                                            stroke="#f85149"
                                            stroke-dasharray="${{circ}} ${{circ}}"
                                            stroke-dashoffset="${{Math.max(0, circ * (1 - wkPct / 100))}}" />
                                </svg>
                            </div>
                        </div>
                    `;
                    card.appendChild(wkRow);

                    const div = document.createElement('div');
                    div.className = 'antigravity-card-row-divider';
                    card.appendChild(div);
                }}

                // Five Hour Limit Remaining
                const fhRow = document.createElement('div');
                fhRow.className = 'antigravity-limit-row';
                const fhReset = focusedAcc.five_hour_refresh_text || 'Recargado (100%)';
                const fhDesc = fhPct >= 100 ? 'Cuota 5h completamente recargada.' : ('Recarga en ' + fhReset);

                fhRow.innerHTML = `
                    <div class="antigravity-limit-info">
                        <div class="antigravity-limit-title">Five Hour Limit Remaining</div>
                        <div class="antigravity-limit-desc">${{fhDesc}}</div>
                    </div>
                    <div class="antigravity-limit-stat">
                        <span class="antigravity-limit-pct">${{fhPct}}%</span>
                        <div class="antigravity-ring-wrap">
                            <svg width="26" height="26" viewBox="0 0 28 28" class="antigravity-ring-svg">
                                <circle class="antigravity-ring-bg" cx="14" cy="14" r="11" />
                                <circle class="antigravity-ring-fill" cx="14" cy="14" r="11"
                                        stroke="#3fb950"
                                        stroke-dasharray="${{circ}} ${{circ}}"
                                        stroke-dashoffset="${{Math.max(0, circ * (1 - fhPct / 100))}}" />
                            </svg>
                        </div>
                    </div>
                `;
                card.appendChild(fhRow);

                // Modelos Google Gemini autorizados
                const modelsRow = document.createElement('div');
                modelsRow.className = 'antigravity-models-tag-row';
                const modelsList = data.gemini_models || [];
                modelsList.forEach(m => {{
                    const pill = document.createElement('span');
                    pill.className = 'antigravity-model-pill';
                    pill.textContent = m;
                    modelsRow.appendChild(pill);
                }});
                card.appendChild(modelsRow);

                cardContainer.appendChild(card);
            }}

            // Renderizar la lista de cuentas
            if (listContainer) {{
                listContainer.innerHTML = '';
                accounts.forEach(acc => {{
                    const isCurrent = acc.is_active;
                    const row = document.createElement('button');
                    row.type = 'button';
                    row.className = 'antigravity-acc-row' + (isCurrent ? ' is-active' : '');

                    const left = document.createElement('div');
                    left.className = 'antigravity-acc-left';

                    const check = document.createElement('span');
                    check.className = 'antigravity-acc-check';
                    check.textContent = isCurrent ? '*' : '';

                    const nameGroup = document.createElement('div');
                    nameGroup.className = 'antigravity-acc-name-group';
                    nameGroup.innerHTML = `
                        <span class="antigravity-acc-name">${{acc.name}}</span>
                        <span class="antigravity-acc-email">${{acc.email}}</span>
                    `;

                    left.appendChild(check);
                    left.appendChild(nameGroup);

                    const right = document.createElement('div');
                    right.className = 'antigravity-acc-right';

                    if (isCurrent) {{
                        const badge = document.createElement('span');
                        badge.className = 'antigravity-acc-active-badge';
                        badge.textContent = '[ACTIVA]';
                        right.appendChild(badge);
                    }}

                    // Regla estricta: Mostrar etiqueta semanal UNICAMENTE si <= 15%
                    if (acc.show_weekly_warning) {{
                        const wBadge = document.createElement('span');
                        wBadge.className = 'antigravity-acc-weekly-warning';
                        wBadge.textContent = '! Sem: ' + acc.weekly_remaining_pct + '%';
                        right.appendChild(wBadge);
                    }}

                    const qBadge = document.createElement('span');
                    qBadge.className = 'antigravity-acc-quota-badge';
                    qBadge.textContent = '5h: ' + acc.five_hour_remaining_pct + '%';
                    right.appendChild(qBadge);

                    if (acc.has_token) {{
                        const tBadge = document.createElement('span');
                        tBadge.className = 'antigravity-acc-token-badge';
                        tBadge.textContent = 'Token: ' + acc.token_preview;
                        right.appendChild(tBadge);
                    }}

                    row.appendChild(left);
                    row.appendChild(right);

                    // Inspeccion interactiva al pasar el mouse o hacer click (Modo Solo Lectura)
                    row.addEventListener('mouseenter', () => {{
                        focusedEmail = acc.email.toLowerCase().trim();
                        renderHUD(currentData);
                    }});
                    row.addEventListener('click', () => {{
                        focusedEmail = acc.email.toLowerCase().trim();
                        renderHUD(currentData);
                    }});

                    listContainer.appendChild(row);
                }});
            }}
        }}

        renderHUD(initialData);

        // Polling automatico en tiempo real cada 4 segundos
        setInterval(async () => {{
            try {{
                const res = await fetch('/api/tokens');
                if (res.ok) {{
                    const freshData = await res.json();
                    renderHUD(freshData);
                }}
            }} catch (_err) {{}}
        }}, 4000);
    </script>
</body>
</html>
"""


class ReadOnlyHUDHandler(http.server.BaseHTTPRequestHandler):
    """Manejador HTTP de solo lectura. No implementa ninguna funcion de cambio de cuenta."""
    timeout = 10.0

    def log_message(self, format: str, *args: Any) -> None:
        # Silenciar logs ruidosos en stdout a menos que haya error
        if args and str(args[1]) in ("500", "404"):
            sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path == "":
            path = "/"

        if path in ("/", "/index.html"):
            state = resolve_accounts_state()
            content = build_hud_html(state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(content)
            return

        if path in ("/api/tokens", "/api/status"):
            state = resolve_accounts_state()
            content = json.dumps(state, indent=2, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    def do_POST(self) -> None:
        # Exclusion estricta: Operaciones de mutacion o cambio estan prohibidas
        self.send_response(405)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        response = json.dumps({"error": "Method Not Allowed. Switch operations strictly excluded."})
        self.wfile.write(response.encode("utf-8"))


def run_http_server(host: str = "127.0.0.1", port: int = 59123) -> None:
    """Inicia el servidor Micro-HUD en modo de solo lectura."""
    server_address = (host, port)
    
    # Permitir reusar direccion y configurar hilos demonio para terminacion limpia
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    try:
        with socketserver.ThreadingTCPServer(server_address, ReadOnlyHUDHandler) as httpd:
            print("==========================================================================================")
            print(f" Antigravity Accounts & Tokens Micro-HUD activo en: http://{host}:{port}/")
            print(" Modo: Solo lectura de tokens y cuentas. Cero mutaciones ni cambio de cuenta.")
            print(" Presione Ctrl+C para detener el servidor.")
            print("==========================================================================================")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nServidor detenido por el usuario.")
    except OSError as err:
        winerr = getattr(err, "winerror", getattr(err, "errno", None))
        if winerr in (10048, 10013, 48, 98):
            sys.stderr.write(
                f"Error: Puerto {port} ya esta en uso por otra instancia o proceso ([WinError {winerr}]). "
                f"Verifique instancias activas de Micro-HUD o especifique otro puerto con --port.\n"
            )
        else:
            sys.stderr.write(f"Error de socket en puerto {port}: {err}\n")
        sys.exit(1)
    except Exception as exc:
        sys.stderr.write(f"Error al iniciar servidor en puerto {port}: {exc}\n")
        sys.exit(1)


# -----------------------------------------------------------------------------
# Punto de Entrada Principal
# -----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visualizador del menu de cuentas y tokens de Antigravity (Solo lectura)."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida estructurada JSON del estado de cuentas y tokens."
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Ejecuta el servidor Micro-HUD Web de solo lectura."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=59123,
        help="Puerto para el servidor Micro-HUD (default: 59123)."
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host para el servidor Micro-HUD (default: 127.0.0.1)."
    )

    args = parser.parse_args()

    state = resolve_accounts_state()

    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return

    if args.serve:
        run_http_server(host=args.host, port=args.port)
        return

    # Modo consola por defecto
    table_output = render_console_table(state)
    print(table_output)


if __name__ == "__main__":
    main()
