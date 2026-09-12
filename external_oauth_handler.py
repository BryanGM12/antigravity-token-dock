"""
External OAuth Handler: Windows Desktop Automation for Google Sign-In
Handles Google Sign-In and OAuth 2.0 flow when opened in external browsers (Comet, Chrome, Edge).
Uses Alt-key bypass, passive title inspection, login_hint URL injection,
safe web margin focusing, and deterministic Tab / centered click account selection.
"""

import os
import re
import time
import ctypes
from ctypes import wintypes
import logging
import pyperclip
import psutil
from typing import Optional, Tuple

logger = logging.getLogger("ExternalOAuthHandler")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:
    from config_manager import get_account_tab_map, get_account_row_offset
except Exception:
    def get_account_tab_map():
        return {}
    def get_account_row_offset(email: str):
        return 0

def switch_to_interactive_desktop() -> bool:
    """Switches current thread desktop to 'default' interactive desktop."""
    try:
        h_desk = user32.OpenDesktopW('default', 0, False, 0x01FF)
        if not h_desk:
            return False
        res = user32.SetThreadDesktop(h_desk)
        return bool(res)
    except Exception as e:
        logger.debug(f"Failed to switch thread desktop: {e}")
        return False

def activate_browser_window(hwnd: int) -> bool:
    """
    Brings browser window to the foreground across multiple monitors.
    Uses the Windows Alt-key bypass to overcome UIPI foreground lock.
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return False
        
    switch_to_interactive_desktop()
    
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.AllowSetForegroundWindow(-1)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    res = user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.15)
    return bool(res)

def send_key_combination(hwnd: int, vk_ctrl: int, vk_key: int):
    """Sends Ctrl + Key combination to the browser window."""
    activate_browser_window(hwnd)
    time.sleep(0.06)
    
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(vk_ctrl, 0, 0, 0)
    user32.keybd_event(vk_key, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk_key, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(vk_ctrl, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.1)

def send_single_key(hwnd: int, vk_code: int):
    """Sends a single key event (press and release)."""
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.06)

def close_browser_tab(hwnd: int):
    """Sends Ctrl+W to close current auth tab in browser."""
    VK_CONTROL = 0x11
    VK_W = ord('W')
    send_key_combination(hwnd, VK_CONTROL, VK_W)

def find_browser_window() -> Optional[int]:
    """
    Finds the active browser window handle (Comet, Chrome, Edge, Brave) on the interactive desktop.
    Strictly excludes Antigravity and ensures window is visible.
    """
    switch_to_interactive_desktop()
    matching_hwnds = []
    supported_browsers = {"comet.exe", "chrome.exe", "msedge.exe", "brave.exe", "firefox.exe"}
    
    def enum_cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        try:
            pname = psutil.Process(pid.value).name().lower()
        except Exception:
            return True
            
        # Ignore Antigravity process itself
        if "antigravity" in pname:
            return True
            
        if pname in supported_browsers:
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            
            # Prioritize windows matching Google / OAuth / Antigravity / Comet
            score = 1
            if any(k in title for k in ["Google", "Acceso", "Sign in", "Elegir", "Elige", "Choose", "Antigravity", "Auth"]):
                score = 10
            matching_hwnds.append((score, hwnd))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    
    if matching_hwnds:
        matching_hwnds.sort(key=lambda x: x[0], reverse=True)
        return matching_hwnds[0][1]
    return None

def get_browser_url(hwnd: int) -> str:
    """Reads current tab URL via Ctrl+L / Ctrl+C without breaking page focus."""
    try:
        activate_browser_window(hwnd)
        pyperclip.copy("")
        send_key_combination(hwnd, 0x11, ord('L'))
        time.sleep(0.08)
        send_key_combination(hwnd, 0x11, ord('C'))
        time.sleep(0.1)
        url = pyperclip.paste().strip()
        # Return focus to web contents cleanly via F6
        send_single_key(hwnd, 0x75)  # VK_F6
        time.sleep(0.05)
        return url
    except Exception as e:
        logger.debug(f"Failed to copy browser URL: {e}")
        return ""

def inject_url_in_browser(hwnd: int, new_url: str):
    """Navigates browser directly to new_url via address bar."""
    activate_browser_window(hwnd)
    pyperclip.copy(new_url)
    send_key_combination(hwnd, 0x11, ord('L'))
    time.sleep(0.08)
    send_key_combination(hwnd, 0x11, ord('V'))
    time.sleep(0.08)
    send_single_key(hwnd, 0x0D)  # VK_RETURN
    time.sleep(1.2)

def physical_click(x: int, y: int):
    """Moves physical cursor and fires mouse down/up on the interactive desktop."""
    switch_to_interactive_desktop()
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.08)

def focus_web_contents_safely(hwnd: int):
    """
    Clicks in the empty margin on the far left of the browser window.
    This safely focuses the web contents document WITHOUT clicking any account button.
    """
    switch_to_interactive_desktop()
    rect = wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        safe_x = rect.left + 50
        safe_y = rect.top + 160
        physical_click(safe_x, safe_y)
        time.sleep(0.1)

def select_account_via_tabs(hwnd: int, target_email: str) -> bool:
    """
    Selects target account on Google's Account Chooser screen using deterministic Tab navigation:
    1. Safely focuses web page body on empty margin.
    2. Resets cursor/focus to the top with Ctrl+Home.
    3. Tabs exactly N times to target account button.
    4. Triggers selection with Enter.
    """
    norm = target_email.strip().lower()
    tab_map = get_account_tab_map()
    tab_count = None
    for acc, count in tab_map.items():
        if acc.split("@")[0] in norm or norm in acc:
            tab_count = count
            break
            
    if not tab_count:
        tab_count = 2  # Default sensible fallback
        
    logger.info(f"Navigating Google Account Chooser for {target_email} with {tab_count} Tab presses...")
    activate_browser_window(hwnd)
    time.sleep(0.15)
    
    # Safely focus margin
    focus_web_contents_safely(hwnd)
    time.sleep(0.1)
    
    # Scroll to top of DOM
    send_key_combination(hwnd, 0x11, 0x24)  # Ctrl + Home
    time.sleep(0.15)
    
    VK_TAB = 0x09
    for _ in range(tab_count):
        send_single_key(hwnd, VK_TAB)
        time.sleep(0.08)
        
    time.sleep(0.1)
    send_single_key(hwnd, 0x0D)  # VK_RETURN
    time.sleep(1.0)
    return True

def select_account_via_centered_click(hwnd: int, target_email: str) -> bool:
    """
    Backup physical click directly in the center of the Google Account card.
    Google's account card is horizontally centered on all monitor resolutions.
    """
    switch_to_interactive_desktop()
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
        
    win_w = rect.right - rect.left
    win_h = rect.bottom - rect.top
    if win_w <= 0 or win_h <= 0:
        return False
        
    # Card is horizontally centered
    cx = rect.left + (win_w // 2)
    
    # Calculate row vertical offset from tab index
    tab_map = get_account_tab_map()
    tab_count = tab_map.get(target_email.lower().strip(), 2)
    row_idx = max(0, tab_count - 1)  # 0-indexed row
    
    # Estimated card row start position: ~32% from top of window or centered
    card_start_y = rect.top + int(win_h * 0.32)
    row_y = card_start_y + (row_idx * 60)
    
    logger.info(f"Executing backup centered physical click on account {target_email} at ({cx}, {row_y})...")
    physical_click(cx, row_y)
    time.sleep(0.2)
    send_single_key(hwnd, 0x0D)  # Enter confirmation
    time.sleep(1.0)
    return True

def handle_external_google_signin(target_email: str, timeout_sec: int = 35) -> bool:
    """
    High-Reliability Google OAuth automation in external browser:
    1. Finds active browser window (strictly excluding Antigravity).
    2. Detects OAuth page and injects login_hint={target_email} for instant 1-step sign-in.
    3. If Account Chooser appears, executes deterministic keyboard Tab selection + centered click.
    4. Handles permission/consent prompts ("Continuar" / "Permitir").
    5. Confirms success (antigravity.google/auth-success or window title) and closes tab.
    """
    logger.info(f"Starting high-reliability Google Sign-In for target account: {target_email}...")
    switch_to_interactive_desktop()
    start_time = time.time()
    
    login_hint_injected = False
    selection_attempts = 0
    last_url_check = 0.0
    cached_url = ""
    
    while time.time() - start_time < timeout_sec:
        hwnd = find_browser_window()
        if not hwnd:
            time.sleep(0.4)
            continue
            
        # Passive window title check (0ms overhead, does not disrupt page)
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value
        
        # 1. Success verification in title
        if any(w in title for w in [
            "Google Antigravity Auth Success",
            "antigravity.google/auth-success",
            "Auth Success"
        ]):
            logger.info("Authentication success detected in browser window title!")
            time.sleep(0.8)
            close_browser_tab(hwnd)
            logger.info("Closed authentication tab in browser.")
            return True
            
        # 2. Check URL at controlled intervals (every 2.5s maximum) to avoid focus theft
        now = time.time()
        if now - last_url_check > 2.5:
            last_url_check = now
            cached_url = get_browser_url(hwnd)
            
            if "auth-success" in cached_url or ("localhost:" in cached_url and "code=" in cached_url):
                logger.info(f"Authentication success detected in URL: {cached_url}")
                time.sleep(0.8)
                close_browser_tab(hwnd)
                logger.info("Closed authentication tab in browser.")
                return True
                
            # Instant login_hint injection on Google OAuth pages
            if "accounts.google.com" in cached_url and "login_hint=" not in cached_url and not login_hint_injected:
                logger.info(f"Injecting login_hint={target_email} into address bar for direct account selection...")
                sep = "&" if "?" in cached_url else "?"
                target_url = f"{cached_url}{sep}login_hint={target_email}&Email={target_email}"
                inject_url_in_browser(hwnd, target_url)
                login_hint_injected = True
                time.sleep(1.8)
                continue
                
        # 3. Handle Account Chooser screen
        is_chooser = (
            "accountchooser" in cached_url.lower() or
            "Acceso: Cuentas de Google" in title or
            "Elige una cuenta" in title or
            "Elegir una cuenta" in title or
            "Choose an account" in title
        )
        
        if is_chooser and selection_attempts < 4:
            selection_attempts += 1
            logger.info(f"Detected Google Account Chooser screen (attempt {selection_attempts}/4)...")
            
            # Primary strategy: Clean keyboard Tab navigation
            select_account_via_tabs(hwnd, target_email)
            time.sleep(1.5)
            
            # If still on chooser after attempt 2, execute centered click
            if selection_attempts >= 2:
                select_account_via_centered_click(hwnd, target_email)
                time.sleep(1.5)
            continue
            
        # 4. Handle Consent / Confirmation prompt ("Continuar", "Allow", "Permitir")
        is_consent = (
            "permitir" in title.lower() or
            "continuar" in title.lower() or
            "allow" in title.lower() or
            "consent" in cached_url.lower() or
            "approval" in cached_url.lower()
        )
        if is_consent:
            logger.info("Detected OAuth consent screen. Confirming...")
            activate_browser_window(hwnd)
            time.sleep(0.1)
            send_single_key(hwnd, 0x09)  # Tab to primary button
            time.sleep(0.08)
            send_single_key(hwnd, 0x0D)  # Enter
            time.sleep(1.2)
            
        time.sleep(0.5)
        
    logger.warning("External Google Sign-In timed out.")
    return False
