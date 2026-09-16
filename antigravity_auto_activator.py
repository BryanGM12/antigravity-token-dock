#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
✦ Antigravity Auto-Activator & Lifecycle Supervisor
===================================================
Automatically activates the Account Rotation Daemon and Docked Widget
whenever Google Antigravity is active/opened, and automatically shuts them
down cleanly when Antigravity is closed to free CPU and memory.

Features:
- Sub-2s detection of Antigravity.exe lifecycle.
- Autonomous startup of daemon_service.py and antigravity_docked_overlay.py.
- Auto-healing watchdog: revives widget/daemon if closed while Antigravity is running.
- Graceful deactivation when Antigravity terminates.
- Pure symbol-based logging without emojis.
"""

import os
import sys
import time
import subprocess
import logging
import psutil
from pathlib import Path
from typing import Optional, List

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".openclaw" / "workspace" / "state" / "antigravity_controller"
STATE_DIR.mkdir(parents=True, exist_ok=True)

ACTIVATOR_PID_FILE = STATE_DIR / "activator.pid"
DAEMON_PID_FILE = STATE_DIR / "daemon.pid"
WIDGET_PID_FILE = STATE_DIR / "widget.pid"
LOG_FILE = STATE_DIR / "activator.log"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AutoActivator")

def get_pythonw_executable() -> str:
    """Finds the best pythonw.exe path for background execution."""
    current_python = Path(sys.executable)
    pythonw = current_python.parent / "pythonw.exe"
    if pythonw.exists():
        return str(pythonw)
    return sys.executable

def is_antigravity_running() -> bool:
    """Checks if any Antigravity IDE process is running."""
    for p in psutil.process_iter(['name']):
        try:
            name = (p.info.get('name') or '').lower()
            if 'antigravity.exe' in name or name == 'antigravity':
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def get_process_by_script(script_name: str) -> Optional[psutil.Process]:
    """Finds a running python process executing the specified script."""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = (proc.info.get('name') or '').lower()
            if 'python' in name:
                cmdline = proc.info.get('cmdline') or []
                cmd_str = " ".join(cmdline).lower()
                if script_name.lower() in cmd_str:
                    return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None

def start_daemon_service() -> bool:
    """Launches daemon_service.py in the background."""
    existing = get_process_by_script("daemon_service.py")
    if existing:
        return True

    pythonw = get_pythonw_executable()
    daemon_script = str(SCRIPT_DIR / "daemon_service.py")
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        proc = subprocess.Popen(
            [pythonw, daemon_script, "--daemon"],
            cwd=str(SCRIPT_DIR),
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        with open(DAEMON_PID_FILE, "w", encoding="ascii") as f:
            f.write(str(proc.pid))
        logger.info(f"[+] Daemon de control activado (PID: {proc.pid})")
        return True
    except Exception as e:
        logger.error(f"[!] Error iniciando daemon_service: {e}")
        return False

def start_widget_overlay() -> bool:
    """Launches antigravity_docked_overlay.py in the background."""
    existing = get_process_by_script("antigravity_docked_overlay.py")
    if existing:
        return True

    pythonw = get_pythonw_executable()
    widget_script = str(SCRIPT_DIR / "antigravity_docked_overlay.py")
    try:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        proc = subprocess.Popen(
            [pythonw, widget_script],
            cwd=str(SCRIPT_DIR),
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        with open(WIDGET_PID_FILE, "w", encoding="ascii") as f:
            f.write(str(proc.pid))
        logger.info(f"[+] Widget acoplado activado (PID: {proc.pid})")
        return True
    except Exception as e:
        logger.error(f"[!] Error iniciando antigravity_docked_overlay: {e}")
        return False

def stop_process(proc: Optional[psutil.Process], name: str):
    """Safely terminates a process."""
    if not proc:
        return
    try:
        pid = proc.pid
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
        logger.info(f"[-] Proceso {name} detenido limpiamente (PID: {pid})")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

def stop_services():
    """Stops both the daemon and the widget overlay."""
    w_proc = get_process_by_script("antigravity_docked_overlay.py")
    d_proc = get_process_by_script("daemon_service.py")
    if w_proc:
        stop_process(w_proc, "Widget Overlay")
    if d_proc:
        stop_process(d_proc, "Daemon Service")

    if WIDGET_PID_FILE.exists():
        try:
            WIDGET_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
    if DAEMON_PID_FILE.exists():
        try:
            DAEMON_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

def check_single_instance() -> bool:
    """Ensures only one instance of the Auto-Activator is running."""
    if ACTIVATOR_PID_FILE.exists():
        try:
            with open(ACTIVATOR_PID_FILE, "r", encoding="ascii") as f:
                saved_pid = int(f.read().strip())
            if psutil.pid_exists(saved_pid):
                proc = psutil.Process(saved_pid)
                if "python" in (proc.name() or "").lower() and saved_pid != os.getpid():
                    logger.warning(f"[!] El Auto-Activador ya esta en ejecucion (PID: {saved_pid}).")
                    return False
        except Exception:
            pass

    with open(ACTIVATOR_PID_FILE, "w", encoding="ascii") as f:
        f.write(str(os.getpid()))
    return True

def run_activator_loop(poll_interval: float = 2.0, grace_period_sec: float = 6.0):
    """
    Main supervisory loop.
    Detects when Antigravity is active and activates daemon & widget.
    Deactivates them when Antigravity terminates.
    """
    if not check_single_instance():
        sys.exit(0)

    logger.info("=======================================================")
    logger.info("✦ Antigravity Auto-Activator & Lifecycle Supervisor ✦")
    logger.info("=======================================================")
    logger.info(f"Monitor iniciado (PID: {os.getpid()}). Intervalo: {poll_interval}s")

    was_active = False
    inactive_since: Optional[float] = None

    try:
        while True:
            ag_running = is_antigravity_running()

            if ag_running:
                inactive_since = None
                if not was_active:
                    logger.info("[✦ ACTIVADO] Antigravity detectado en ejecucion. Activando servicios...")
                    start_daemon_service()
                    time.sleep(1.0)
                    start_widget_overlay()
                    was_active = True
                else:
                    # Auto-healing watchdog: verify both services are still alive while Antigravity runs
                    d_proc = get_process_by_script("daemon_service.py")
                    if not d_proc:
                        logger.info("[✦ AUTO-HEAL] Daemon inactivo mientras Antigravity corre. Reiniciando daemon...")
                        start_daemon_service()

                    w_proc = get_process_by_script("antigravity_docked_overlay.py")
                    if not w_proc:
                        logger.info("[✦ AUTO-HEAL] Widget inactivo mientras Antigravity corre. Reiniciando widget...")
                        start_widget_overlay()

            else:
                # Antigravity is NOT running
                if was_active:
                    if inactive_since is None:
                        inactive_since = time.time()
                        logger.info(f"[✦ AVISO] Antigravity no detectado. Esperando {grace_period_sec}s de gracia...")

                    if time.time() - inactive_since >= grace_period_sec:
                        logger.info("[✦ DESACTIVADO] Antigravity cerrado. Deteniendo servicios para liberar recursos...")
                        stop_services()
                        was_active = False
                        inactive_since = None
                else:
                    # Antigravity not running and was already inactive - ensure services are not lingering
                    d_proc = get_process_by_script("daemon_service.py")
                    w_proc = get_process_by_script("antigravity_docked_overlay.py")
                    if d_proc or w_proc:
                        logger.info("[✦ LIMPIEZA] Servicios residuales detectados sin Antigravity. Deteniendo...")
                        stop_services()

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        logger.info("[✦ CIERRE] Auto-Activador detenido por el usuario.")
    finally:
        if ACTIVATOR_PID_FILE.exists():
            try:
                ACTIVATOR_PID_FILE.unlink(missing_ok=True)
            except Exception:
                pass

def print_status():
    """Prints live status of Antigravity and services to terminal."""
    sys.stdout.reconfigure(encoding='utf-8')
    ag_running = is_antigravity_running()
    act_proc = None
    if ACTIVATOR_PID_FILE.exists():
        try:
            with open(ACTIVATOR_PID_FILE, "r", encoding="ascii") as f:
                saved_pid = int(f.read().strip())
            if psutil.pid_exists(saved_pid):
                act_proc = psutil.Process(saved_pid)
        except Exception:
            pass

    d_proc = get_process_by_script("daemon_service.py")
    w_proc = get_process_by_script("antigravity_docked_overlay.py")

    print("=====================================================")
    print("✦ ESTADO DEL SISTEMA DE AUTO-ACTIVACION ANTIGRAVITY ✦")
    print("=====================================================")
    print(f" Antigravity IDE:  {'[● ACTIVO]' if ag_running else '[✕ INACTIVO]'}")
    print(f" Auto-Activador:   {f'[● ACTIVO (PID: {act_proc.pid})]' if act_proc else '[✕ INACTIVO]'}")
    print(f" Daemon Rotador:   {f'[● ACTIVO (PID: {d_proc.pid})]' if d_proc else '[✕ INACTIVO]'}")
    print(f" Widget Acoplado:  {f'[● ACTIVO (PID: {w_proc.pid})]' if w_proc else '[✕ INACTIVO]'}")
    print(f" Registro de Logs: {LOG_FILE}")
    print("=====================================================")

def start_background_activator():
    """Starts the activator in the background via pythonw."""
    existing_pid = None
    if ACTIVATOR_PID_FILE.exists():
        try:
            with open(ACTIVATOR_PID_FILE, "r", encoding="ascii") as f:
                existing_pid = int(f.read().strip())
            if psutil.pid_exists(existing_pid):
                print(f"[!] El Auto-Activador ya se encuentra activo (PID: {existing_pid}).")
                return
        except Exception:
            pass

    pythonw = get_pythonw_executable()
    script = str(SCRIPT_DIR / "antigravity_auto_activator.py")
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    proc = subprocess.Popen(
        [pythonw, script, "--daemon"],
        cwd=str(SCRIPT_DIR),
        startupinfo=startupinfo,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )
    with open(ACTIVATOR_PID_FILE, "w", encoding="ascii") as f:
        f.write(str(proc.pid))
    print(f"[OK] Auto-Activador de Antigravity iniciado en segundo plano (PID: {proc.pid}).")

def stop_background_activator():
    """Stops the activator and all managed services."""
    if ACTIVATOR_PID_FILE.exists():
        try:
            with open(ACTIVATOR_PID_FILE, "r", encoding="ascii") as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                proc.terminate()
                print(f"[OK] Auto-Activador detenido (PID: {pid}).")
        except Exception:
            pass
        ACTIVATOR_PID_FILE.unlink(missing_ok=True)

    stop_services()
    print("[OK] Todos los servicios de Antigravity han sido desactivados.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "--daemon":
            run_activator_loop()
        elif cmd in ("--status", "status"):
            print_status()
        elif cmd in ("--start", "start"):
            start_background_activator()
        elif cmd in ("--stop", "stop"):
            stop_background_activator()
        else:
            print(f"Uso: python {Path(__file__).name} [--daemon | --status | --start | --stop]")
    else:
        run_activator_loop()
