#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Configuration & Account Credentials Manager
=========================================================
Loads configured accounts from a local JSON file (accounts_config.json)
or falls back to safe template defaults to prevent leaking sensitive
personal email addresses and credentials in version control.
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".openclaw" / "workspace" / "state" / "antigravity_controller"
LOCAL_CONFIG_FILE = BASE_DIR / "accounts_config.json"
STATE_CONFIG_FILE = STATE_DIR / "accounts_config.json"
EXAMPLE_CONFIG_FILE = BASE_DIR / "accounts_config.example.json"

DEFAULT_TEMPLATE_ACCOUNTS = [
    {"email": "account1.pro@gmail.com", "name": "Account 1", "tier": "👑 Pro"},
    {"email": "account2.pro@gmail.com", "name": "Account 2", "tier": "👑 Pro"},
    {"email": "account3.pro@gmail.com", "name": "Account 3", "tier": "👑 Pro"},
    {"email": "account4.pro@gmail.com", "name": "Account 4", "tier": "👑 Pro"}
]

def ensure_config_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

def get_config_path() -> Path:
    if LOCAL_CONFIG_FILE.exists():
        return LOCAL_CONFIG_FILE
    if STATE_CONFIG_FILE.exists():
        return STATE_CONFIG_FILE
    return LOCAL_CONFIG_FILE

def load_accounts_config() -> List[Dict[str, str]]:
    """
    Loads authorized accounts from accounts_config.json.
    Falls back to template accounts if no configuration file exists.
    """
    # 1. Try local config
    for path in [LOCAL_CONFIG_FILE, STATE_CONFIG_FILE]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "accounts" in data:
                        return data["accounts"]
                    if isinstance(data, list):
                        return data
            except Exception:
                pass

    # 2. Try example config
    if EXAMPLE_CONFIG_FILE.exists():
        try:
            with open(EXAMPLE_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "accounts" in data:
                    return data["accounts"]
        except Exception:
            pass

    return DEFAULT_TEMPLATE_ACCOUNTS

def get_authorized_accounts() -> List[Dict[str, Any]]:
    return load_accounts_config()

def get_authorized_emails() -> List[str]:
    return [acc["email"].lower().strip() for acc in load_accounts_config() if "email" in acc]

def get_account_tab_map() -> Dict[str, int]:
    """Returns mapping from email to Tab navigation count for OAuth Chooser."""
    tab_map = {}
    for idx, acc in enumerate(load_accounts_config()):
        email = acc.get("email", "").lower().strip()
        if email:
            tab_map[email] = acc.get("tab_index", idx + 1)
    return tab_map

def get_account_row_offset(email: str) -> int:
    """Returns vertical pixel offset from anchor row in Google Account Chooser."""
    target = email.lower().strip()
    for idx, acc in enumerate(load_accounts_config()):
        acc_email = acc.get("email", "").lower().strip()
        if acc_email in target or target in acc_email:
            return acc.get("row_offset", idx * 61)
    return 0

def save_accounts_config(accounts: List[Dict[str, Any]], target_path: Optional[Path] = None):
    """Saves accounts to local config file."""
    p = target_path or get_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "accounts": accounts,
        "monitoring": {
            "poll_interval_sec": 20,
            "hud_port": 59123
        }
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    # Also mirror to STATE_CONFIG_FILE for daemon consistency
    if p != STATE_CONFIG_FILE:
        try:
            STATE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

def add_account(
    email: str,
    name: Optional[str] = None,
    tier: str = "👑 Pro",
    tab_index: Optional[int] = None,
    row_offset: Optional[int] = None
) -> Dict[str, Any]:
    """
    Adds or updates a Google account in the local configuration and initializes token memory.
    """
    accounts = load_accounts_config()
    norm_email = email.strip().lower()

    if not norm_email or "@" not in norm_email:
        raise ValueError("El correo electrónico proporcionado no tiene un formato válido.")

    # Check if account already exists
    for acc in accounts:
        if acc.get("email", "").strip().lower() == norm_email:
            if name:
                acc["name"] = name
            acc["tier"] = tier
            if tab_index is not None:
                acc["tab_index"] = tab_index
            if row_offset is not None:
                acc["row_offset"] = row_offset
            save_accounts_config(accounts)
            return acc

    next_num = len(accounts) + 1
    t_idx = tab_index if tab_index is not None else (next_num + 1)
    r_offset = row_offset if row_offset is not None else ((next_num - 2) * 61)

    new_acc = {
        "email": norm_email,
        "name": name or f"Cuenta {next_num} ({norm_email.split('@')[0]})",
        "tier": tier,
        "tab_index": t_idx,
        "row_offset": r_offset
    }
    accounts.append(new_acc)
    save_accounts_config(accounts)

    # Initialize memory entry
    try:
        from token_memory import load_memory, save_memory, _init_empty_account_record
        mem = load_memory()
        if norm_email not in mem.get("accounts", {}):
            mem.setdefault("accounts", {})[norm_email] = _init_empty_account_record()
            save_memory(mem)
    except Exception:
        pass

    return new_acc

def remove_account(email: str) -> bool:
    """Removes an account by email from the local configuration."""
    accounts = load_accounts_config()
    norm_email = email.strip().lower()
    filtered = [acc for acc in accounts if acc.get("email", "").strip().lower() != norm_email]
    if len(filtered) != len(accounts):
        save_accounts_config(filtered)
        return True
    return False

def interactive_add_wizard():
    """CLI wizard to effortlessly add a new Google account."""
    print("==========================================================")
    print("   ✦ Asistente para Agregar Cuenta de Google AI / Antigravity")
    print("==========================================================")
    email = input("  ▸ Correo de Google (ej. micuenta@gmail.com): ").strip()
    if not email or "@" not in email:
        print("  [X] Error: Correo inválido.")
        return

    name = input(f"  ▸ Nombre para mostrar (Enter para '{email.split('@')[0]}'): ").strip()
    if not name:
        name = email.split('@')[0].capitalize()

    pro_ans = input("  ▸ ¿Es cuenta Pro / Ultra con cuotas altas? (S/n): ").strip().lower()
    tier = "👑 Pro" if pro_ans in ["", "s", "si", "y", "yes"] else "Standard"

    acc = add_account(email, name=name, tier=tier)
    print("----------------------------------------------------------")
    print(f"  [OK] ¡Cuenta agregada exitosamente!")
    print(f"       Email:  {acc['email']}")
    print(f"       Nombre: {acc['name']}")
    print(f"       Nivel:  {acc['tier']}")
    print("==========================================================")

if __name__ == "__main__":
    import sys
    import argparse

    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Gestor de Cuentas para Antigravity Token Dock")
    parser.add_argument("--add", help="Correo de la cuenta a agregar")
    parser.add_argument("--name", help="Nombre descriptivo de la cuenta", default=None)
    parser.add_argument("--tier", help="Nivel de la cuenta (default: '👑 Pro')", default="👑 Pro")
    parser.add_argument("--remove", help="Correo de la cuenta a eliminar")
    parser.add_argument("--list", action="store_true", help="Listar todas las cuentas configuradas")
    parser.add_argument("--interactive", action="store_true", help="Iniciar asistente interactivo por consola")

    args = parser.parse_args()

    if args.interactive:
        interactive_add_wizard()
    elif args.add:
        acc = add_account(args.add, name=args.name, tier=args.tier)
        print(f"[OK] Cuenta {acc['email']} ({acc['tier']}) configurada exitosamente.")
    elif args.remove:
        ok = remove_account(args.remove)
        if ok:
            print(f"[OK] Cuenta {args.remove} eliminada.")
        else:
            print(f"[!] No se encontró la cuenta {args.remove}.")
    elif args.list:
        accs = get_authorized_accounts()
        print(f"Cuentas configuradas ({len(accs)}):")
        for i, a in enumerate(accs, 1):
            print(f" {i}. {a.get('email')} - {a.get('name', 'Sin nombre')} [{a.get('tier', 'Standard')}]")
    else:
        parser.print_help()


