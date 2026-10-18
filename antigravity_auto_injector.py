#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
antigravity_auto_injector.py
============================
Servicio autonomo de inyeccion continua para Antigravity:
1. Monitorea el inicio y la ejecucion de la aplicacion de escritorio Antigravity.
2. Inyecta automaticamente el boton 'Cuentas' y el menu desplegable en la barra de titulos.
3. Se auto-recupera ante reinicios de la app, reloads (Ctrl+R/F5) o cambios de ventana.
4. CERO EMOJIS: Diseno estricto con texto limpio y simbolos tipograficos nativos.
5. Blindado con socket lock en puerto 59124: nunca permite instancias duplicadas.
"""

import asyncio
import json
import os
import sys
import time
import socket
import urllib.request
import urllib.error
import websockets
from pathlib import Path

# Candado de instancia unica para prevenir procesos duplicados y colisiones CDP
_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    _lock_socket.bind(("127.0.0.1", 59124))
    _lock_socket.listen(1)
except Exception:
    print("[INFO] Otra instancia de antigravity_auto_injector ya esta en ejecucion en el puerto 59124. Saliendo limpiamente.")
    sys.exit(0)

CDP_PORT_FILE = os.path.expandvars(r"%APPDATA%\Antigravity\DevToolsActivePort")

def load_injection_js():
    js_file = Path.home() / ".gemini" / "antigravity_accounts_injector.js"
    if js_file.exists():
        try:
            return js_file.read_text(encoding="utf-8")
        except Exception:
            pass
    return ""

def get_cdp_port():
    if os.path.exists(CDP_PORT_FILE):
        try:
            with open(CDP_PORT_FILE, "r") as pf:
                line = pf.readline().strip()
                if line and line.isdigit():
                    return int(line)
        except Exception:
            pass
    return None

def get_page_ws_url(port):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json", headers={"User-Agent": "AntigravityAutoInjector/1.0"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            targets = json.loads(resp.read().decode())
            for t in targets:
                if t.get("type") == "page":
                    return t.get("webSocketDebuggerUrl")
    except Exception:
        pass
    return None

async def run_injector_loop():
    print("[INIT] Antigravity Continuous Auto-Injector Service iniciado.")
    print("[INIT] Vigilando inicio y ejecucion de Antigravity...")

    while True:
        port = get_cdp_port()
        if not port:
            await asyncio.sleep(2)
            continue

        ws_url = get_page_ws_url(port)
        if not ws_url:
            await asyncio.sleep(2)
            continue

        try:
            async with websockets.connect(ws_url, ping_interval=10, ping_timeout=10) as ws:
                print(f"[CONECTADO] Enlace CDP establecido en ws://127.0.0.1:{port}/")

                while True:
                    # 1. Comprobar si hay exactamente 1 boton Cuentas en el DOM
                    check_msg = {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": "document.querySelectorAll('#antigravity-accounts-menu-item').length",
                            "returnByValue": True
                        }
                    }
                    await ws.send(json.dumps(check_msg))
                    resp = json.loads(await ws.recv())
                    btn_count = resp.get("result", {}).get("result", {}).get("value", 0)

                    if btn_count != 1:
                        # 2. Inyectar o normalizar a exactamente un menu
                        js_to_run = load_injection_js()
                        if not js_to_run:
                            await asyncio.sleep(2)
                            continue

                        inject_msg = {
                            "id": 2,
                            "method": "Runtime.evaluate",
                            "params": {
                                "expression": js_to_run,
                                "returnByValue": True
                            }
                        }
                        await ws.send(json.dumps(inject_msg))
                        inj_resp = json.loads(await ws.recv())
                        val = inj_resp.get("result", {}).get("result", {}).get("value", {})
                        if val.get("status") == "injected_successfully":
                            print(f"[{time.strftime('%H:%M:%S')}] [AUTO-INJECT] Boton 'Cuentas' inyectado exitosamente en Antigravity.")
                        elif val.get("error") == "menu_bar_not_ready":
                            # Esperar a que la UI de Antigravity termine de renderizar
                            pass

                    # Heartbeat pasivo y ligero cada 5 segundos
                    await asyncio.sleep(5)

        except (websockets.exceptions.ConnectionClosed, OSError, asyncio.TimeoutError) as e:
            # La aplicacion Antigravity se cerro, reinicio o recargo; esperar a que reaparezca
            await asyncio.sleep(5)
        except Exception as e:
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run_injector_loop())
    except KeyboardInterrupt:
        print("\n[STOP] Auto-injector detenido.")
