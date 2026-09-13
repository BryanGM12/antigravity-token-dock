"""
Watchdog Service: Health Monitoring, Self-Healing, and Orphan Cleanup
Monitors language_server health, CDP responsiveness, Comet orphan tabs,
and permanently enforces Dark Theme integrity.
"""

import os
import time
import ctypes
from ctypes import wintypes
import logging
import urllib.request
import json
import psutil
from typing import Dict, Any, List, Optional
from playwright.async_api import Page

logger = logging.getLogger("WatchdogService")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PORT_FILE = os.path.expandvars(r"%APPDATA%\Antigravity\DevToolsActivePort")

def get_cdp_health() -> Dict[str, Any]:
    """Tests responsiveness of Antigravity DevTools CDP endpoint."""
    if not os.path.exists(PORT_FILE):
        return {"healthy": False, "error": "DevToolsActivePort file does not exist"}
        
    try:
        with open(PORT_FILE, "r", encoding="utf-8") as f:
            port = int(f.readline().strip())
            
        url = f"http://127.0.0.1:{port}/json/version"
        req = urllib.request.Request(url, headers={"User-Agent": "AntigravityWatchdog"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode())
            return {
                "healthy": True,
                "port": port,
                "browser": data.get("Browser"),
                "protocol": data.get("Protocol-Version")
            }
    except Exception as e:
        return {"healthy": False, "error": str(e)}

def is_language_server_alive() -> bool:
    """Checks if language_server.exe is running."""
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info.get('name') or ''
            if 'language_server.exe' in name.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def switch_to_interactive_desktop() -> bool:
    """Ensures thread is bound to 'default' desktop for window operations."""
    try:
        h_desk = user32.OpenDesktopW('default', 0, False, 0x01FF)
        if h_desk:
            return bool(user32.SetThreadDesktop(h_desk))
    except Exception:
        pass
    return False

def cleanup_orphan_comet_auth_tabs() -> int:
    """
    Finds any lingering 'Google Antigravity Auth Success' tabs in the default browser and closes them cleanly.
    Returns the number of cleaned tabs.
    """
    switch_to_interactive_desktop()
    closed_count = 0

    # Never close auth tabs if a rotation is actively in progress
    lock_file = os.path.expandvars(r"%USERPROFILE%\.openclaw\workspace\state\antigravity_controller\rotation.lock")
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            lock_time = data.get("time", 0)
            if (time.time() - lock_time) < 90:
                logger.debug("[Watchdog] Rotación activa detectada en lockfile. Omitiendo limpieza de pestañas.")
                return 0
        except Exception:
            pass

    try:
        from external_oauth_handler import get_default_browser_info, close_browser_tab
        target_proc, _ = get_default_browser_info()
    except Exception:
        target_proc = "comet.exe"
        close_browser_tab = None

    target_pids = set()
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            pname = (proc.info.get('name') or '').lower()
            if pname == target_proc.lower():
                target_pids.add(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not target_pids:
        return 0
        
    matching_hwnds = []
    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value or pid.value not in target_pids:
                return True
                
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            if "Google Antigravity Auth Success" in title or "antigravity.google/auth-success" in title:
                matching_hwnds.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    
    for hwnd in matching_hwnds:
        try:
            logger.info(f"Closing leftover auth tab in {target_proc}: HWND {hwnd}...")
            if close_browser_tab:
                close_browser_tab(hwnd)
            else:
                # Safe fallback: send Ctrl+W directly, NEVER send WM_CLOSE
                VK_CONTROL = 0x11
                VK_W = ord('W')
                KEYEVENTF_KEYUP = 0x0002
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.04)
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_W, 0, 0, 0)
                time.sleep(0.04)
                user32.keybd_event(VK_W, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            closed_count += 1
            time.sleep(0.1)
        except Exception as e:
            logger.warning(f"Error closing orphan tab {hwnd}: {e}")
            
    return closed_count

async def ensure_dark_theme(page: Page) -> bool:
    """
    Verifies that Antigravity remains in Dark Theme.
    If light theme is accidentally active, restores dark mode immediately.
    """
    try:
        is_dark = await page.evaluate(r'''() => {
            const body = document.body;
            const style = window.getComputedStyle(body);
            const isDark = body.classList.contains('dark') || style.backgroundColor.includes('16, 16, 16');
            if (!isDark) {
                body.classList.add('dark');
                // Try clicking Dark button if settings is open
                const darkBtn = document.querySelector('button[aria-label="Dark"]');
                if (darkBtn) darkBtn.click();
            }
            return isDark;
        }''')
        return is_dark
    except Exception as e:
        logger.debug(f"Dark theme check: {e}")
        return True

def run_health_audit() -> Dict[str, Any]:
    """Runs a complete health audit of all Antigravity subsystems."""
    cdp = get_cdp_health()
    ls_alive = is_language_server_alive()
    orphans = cleanup_orphan_comet_auth_tabs()
    
    status = "OK" if (cdp.get("healthy") and ls_alive) else "DEGRADED"
    
    return {
        "status": status,
        "cdp": cdp,
        "language_server_alive": ls_alive,
        "orphan_tabs_cleaned": orphans
    }

if __name__ == "__main__":
    audit = run_health_audit()
    print("Health Audit:", json.dumps(audit, indent=2))
