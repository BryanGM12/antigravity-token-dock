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
    Finds any lingering 'Google Antigravity Auth Success' tabs in Comet and closes them.
    Returns the number of cleaned tabs.
    """
    switch_to_interactive_desktop()
    closed_count = 0
    
    matching_hwnds = []
    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            cls_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buff, 256)
            if cls_buff.value == "Chrome_WidgetWin_1":
                length = user32.GetWindowTextLengthW(hwnd)
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                if "Google Antigravity Auth Success" in title or "auth-success" in title:
                    matching_hwnds.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    
    for hwnd in matching_hwnds:
        try:
            logger.info(f"Closing leftover Comet auth window: HWND {hwnd}...")
            # Post WM_CLOSE directly to close window cleanly in background without focus stealing
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
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
