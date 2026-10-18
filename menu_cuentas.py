#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
menu_cuentas.py
===============
Menu interactivo de Antigravity:
1. Ver estado de las 7 cuentas Google AI Pro, tokens y cuotas en tiempo real.
2. Cambiar de cuenta manualmente de forma instantanea (consola o API HTTP).
3. Servidor de soporte para el boton inyectado en la app Antigravity.
"""

import sys
import os
import time
import json
import io
import http.server
import socketserver
import urllib.parse
from pathlib import Path

# Proteccion total ante ejecucion en background con pythonw.exe
class SafeDevNull(io.StringIO):
    def write(self, s): pass
    def flush(self): pass

if sys.stdout is None:
    sys.stdout = SafeDevNull()
if sys.stderr is None:
    sys.stderr = SafeDevNull()

# Agregar rutas al path
GEMINI_DIR = Path.home() / ".gemini"
SYS_PATHS = [
    str(GEMINI_DIR),
    str(GEMINI_DIR / "antigravity_account_controller"),
]
for p in SYS_PATHS:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import accounts_tokens_menu
except ImportError:
    accounts_tokens_menu = None

try:
    import auto_account_pool
except ImportError:
    auto_account_pool = None

import threading
_last_quota_probe = 0.0
_probe_lock = threading.Lock()

def maybe_refresh_quotas_async(force: bool = False) -> None:
    global _last_quota_probe
    now = time.time()
    if force or (now - _last_quota_probe > 60.0):
        with _probe_lock:
            if force or (now - _last_quota_probe > 60.0):
                _last_quota_probe = now
                def _do_probe():
                    try:
                        if auto_account_pool is not None:
                            auto_account_pool.update_pool_status(force_probe=True)
                    except Exception:
                        pass
                t = threading.Thread(target=_do_probe, daemon=True)
                t.start()

ACCOUNTS_LIST = [
    ("1", "primary_dev", "primary.dev@gmail.com"),
    ("2", "backup_worker", "backup.worker@gmail.com"),
    ("3", "ai_architect", "ai.architect@gmail.com"),
    ("4", "reviewer_pro", "reviewer.pro@gmail.com"),
    ("5", "qa_engineer", "qa.engineer@gmail.com"),
    ("6", "devops_runner", "devops.runner@gmail.com"),
    ("7", "data_analyst", "data.analyst@gmail.com"),
]

def show_menu():
    if accounts_tokens_menu is not None:
        state = accounts_tokens_menu.resolve_accounts_state()
        print(accounts_tokens_menu.render_console_table(state))
    else:
        print("==========================================================================================")
        print("                           ANTIGRAVITY ACCOUNTS MENU                                      ")
        print("==========================================================================================")
        for num, alias, email in ACCOUNTS_LIST:
            print(f" [{num}] {alias:<12} ({email})")
        print("==========================================================================================")

import time

def switch_account(target):
    target_clean = str(target).strip().lower()
    chosen_alias = None
    chosen_email = None

    # Verificar si es un numero 1-7, alias o email
    for num, alias, email in ACCOUNTS_LIST:
        if target_clean == num or target_clean == alias or target_clean == email:
            chosen_alias = alias
            chosen_email = email
            break

    if not chosen_alias:
        print(f"\n[ERROR] Opcion no valida: '{target}'. Debe ser un numero del 1 al 7 o un alias.")
        return False, "Opcion no valida", "", ""

    print(f"\nCambiando a cuenta: {chosen_alias} ({chosen_email})...")

    # 1. Inyectar en Windows Credential Manager 'gemini:antigravity'
    try:
        import inject_wincred
        inject_wincred.inject_profile_token(chosen_alias)
        print(f"[OK] Credenciales inyectadas en Windows Credential Manager para {chosen_alias}")
    except Exception as e:
        print(f"[ADVERTENCIA] Error en inject_wincred: {e}")

    # 2. Actualizar app_storage.json de Antigravity
    storage_path = os.path.expandvars(r"%APPDATA%\Antigravity\app_storage.json")
    if os.path.exists(storage_path):
        try:
            with open(storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["jetski.onboarding.lastLoginUsername"] = chosen_email
            data["jetski.onboarding.lastLoginIsGcpTos"] = "false"
            data["ide-install-wizard-shown"] = "true"
            with open(storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[OK] app_storage.json actualizado con {chosen_email}")
        except Exception as e:
            print(f"[ADVERTENCIA] Error actualizando app_storage.json: {e}")

    # 3. Aplicar perfil en auto_account_pool
    if auto_account_pool is not None:
        try:
            prof_path = auto_account_pool.apply_active_account(chosen_alias)
            print(f"[OK] Perfil local sincronizado: {prof_path}")
        except Exception as e:
            print(f"[ADVERTENCIA] Error auto_account_pool: {e}")

    # 4. Asegurar active_account.json
    try:
        active_file = GEMINI_DIR / "active_account.json"
        with open(active_file, "w", encoding="utf-8") as f:
            json.dump({
                "active_alias": chosen_alias,
                "active_email": chosen_email,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
            }, f, indent=2)
        print(f"[OK] active_account.json actualizado con {chosen_alias}")
    except Exception as e:
        print(f"[ADVERTENCIA] Error en active_account.json: {e}")

    # 5. Sincronizar token_memory.json para reflejo inmediato en lecturas de cuota
    token_mem_path = GEMINI_DIR / "token_memory.json"
    if token_mem_path.exists():
        try:
            with open(token_mem_path, "r", encoding="utf-8") as f:
                mem = json.load(f)
            mem["active_account"] = chosen_email
            with open(token_mem_path, "w", encoding="utf-8") as f:
                json.dump(mem, f, indent=2)
            print(f"[OK] token_memory.json sincronizado con {chosen_email}")
        except Exception as e:
            print(f"[ADVERTENCIA] Error en token_memory: {e}")

    # 6. Sincronizar language_server.exe en tiempo real (Hot Reload de identidad)
    # Al senalizar a language_server.exe, el supervisor nativo de Antigravity lo
    # respawnea inmediatamente (~1.5s) cargando las nuevas credenciales de Google
    # en memoria sin reiniciar la ventana de Electron ni perder workspaces o terminales.
    try:
        os.system("taskkill /F /IM language_server.exe >nul 2>&1")
        print("[OK] language_server.exe senalizado para recarga de credenciales")
    except Exception as e:
        print(f"[ADVERTENCIA] Error senalizando language_server: {e}")

    print(f"[OK] Cambio completado exitosamente a {chosen_alias} ({chosen_email}) - Cero reinicios de ventana.")
    return True, f"Cuenta {chosen_alias} activada", chosen_alias, chosen_email

class InteractiveHUDHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")
            if path == "/api/switch":
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
                target = ""
                if body:
                    try:
                        data = json.loads(body)
                        target = data.get("account") or data.get("target") or ""
                    except Exception:
                        pass
                if not target:
                    qs = urllib.parse.parse_qs(parsed.query)
                    target = qs.get("account", [""])[0] or qs.get("target", [""])[0]
                if target:
                    ok, msg, chosen_alias, chosen_email = switch_account(target)
                else:
                    ok, msg, chosen_alias, chosen_email = False, "no_target", "", ""
                resp = json.dumps({
                    "ok": ok,
                    "target": chosen_alias or target,
                    "active_email": chosen_email,
                    "message": msg
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            self.send_response(404)
            self.end_headers()
        except Exception as e:
            err_resp = json.dumps({"ok": False, "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(err_resp)))
            self.end_headers()
            self.wfile.write(err_resp)

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")
            if path == "": path = "/"

            if path in ("/api/tokens", "/api/status"):
                qs = urllib.parse.parse_qs(parsed.query)
                is_force = qs.get("refresh", ["0"])[0] in ("1", "true")
                if is_force and auto_account_pool is not None:
                    try:
                        auto_account_pool.update_pool_status(force_probe=True)
                    except Exception:
                        pass
                else:
                    maybe_refresh_quotas_async(force=False)

                state = accounts_tokens_menu.resolve_accounts_state() if accounts_tokens_menu else {}
                content = json.dumps(state, indent=2, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

            if path == "/api/switch":
                qs = urllib.parse.parse_qs(parsed.query)
                target = qs.get("account", [""])[0] or qs.get("target", [""])[0]
                if target:
                    ok, msg, chosen_alias, chosen_email = switch_account(target)
                else:
                    ok, msg, chosen_alias, chosen_email = False, "no_target", "", ""
                resp = json.dumps({
                    "ok": ok,
                    "target": chosen_alias or target,
                    "active_email": chosen_email,
                    "message": msg
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return

            if path in ("/", "/index.html"):
                if accounts_tokens_menu:
                    state = accounts_tokens_menu.resolve_accounts_state()
                    content = accounts_tokens_menu.build_hud_html(state).encode("utf-8")
                else:
                    content = b"<h1>Antigravity Accounts Menu</h1>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

            self.send_response(404)
            self.end_headers()
        except Exception as e:
            err_resp = json.dumps({"ok": False, "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(err_resp)))
            self.end_headers()
            self.wfile.write(err_resp)

def run_server(port=59123):
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), InteractiveHUDHandler) as httpd:
        print(f"Servidor HUD interactivo activo en http://127.0.0.1:{port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass

def interactive_prompt():
    print("\n------------------------------------------------------------------------------------------")
    print(" CAMBIO MANUAL DE CUENTA:")
    for num, alias, email in ACCOUNTS_LIST:
        print(f"  [{num}] {alias:<11} -> {email}")
    print("  [0] Salir sin realizar cambios")
    print("------------------------------------------------------------------------------------------")

    try:
        choice = input(" Seleccione el numero de cuenta a activar [1-7] (Enter para salir): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nOperacion cancelada.")
        return

    if not choice or choice in ("0", "q", "exit", "salir"):
        print("Sin cambios. Cuenta activa conservada.")
        return

    switch_account(choice)

def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg in ("--serve", "-s", "--server"):
            port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 59123
            run_server(port)
            return
        elif arg in ("--help", "-h"):
            print("Uso: python menu_cuentas.py [NUMERO_O_ALIAS | --serve | --view]")
            print("Ejemplos:")
            print("  python menu_cuentas.py          (Muestra menu interactivo)")
            print("  python menu_cuentas.py 4        (Cambia directamente a tom12)")
            print("  python menu_cuentas.py --serve  (Inicia servidor HUD en puerto 59123)")
            return
        elif arg in ("--view", "-v", "--tokens", "-t"):
            show_menu()
            return
        else:
            show_menu()
            switch_account(arg)
            return

    # Modo interactivo por defecto
    show_menu()
    if sys.stdin.isatty():
        interactive_prompt()
    else:
        print("\nPara cambiar de cuenta ejecute: python menu_cuentas.py [1-7]")

if __name__ == "__main__":
    main()
