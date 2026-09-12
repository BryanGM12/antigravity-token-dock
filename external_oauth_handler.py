"""
External OAuth Handler: Windows Desktop Automation for Google Sign-In
Handles Google Sign-In and OAuth 2.0 flow when opened in external browsers (Comet, Chrome, Edge).
Uses Alt-key bypass, direct login_hint OAuth URL injection,
passive title inspection, safe web margin focusing, calibrated centered clicks,
and deterministic Tab account selection.
"""

import os
import re
import time
import ctypes
from ctypes import wintypes
import logging
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import pyperclip
import psutil
from typing import Optional, Tuple

logger = logging.getLogger("ExternalOAuthHandler")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:
    from config_manager import get_account_tab_map, get_account_row_offset, get_account_index
except Exception:
    def get_account_tab_map():
        return {}
    def get_account_row_offset(email: str):
        return 0
    def get_account_index(email: str):
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
    CRITICAL: Only calls SW_RESTORE (9) if window is minimized (IsIconic).
    Maximized windows are left untouched to prevent window resize shifts.
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return False
        
    switch_to_interactive_desktop()
    
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.AllowSetForegroundWindow(-1)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE only if minimized
    res = user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.08)
    return bool(res)

def send_key_combination(hwnd: int, vk_ctrl: int, vk_key: int):
    """Sends Ctrl + Key combination to the browser window."""
    activate_browser_window(hwnd)
    time.sleep(0.05)
    
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(vk_ctrl, 0, 0, 0)
    user32.keybd_event(vk_key, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk_key, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(vk_ctrl, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.08)

def send_single_key(hwnd: int, vk_code: int):
    """Sends a single key event (press and release)."""
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)

def close_browser_tab(hwnd: int):
    """Closes auth window/tab cleanly via Ctrl+W with WM_CLOSE fallback."""
    try:
        activate_browser_window(hwnd)
        VK_CONTROL = 0x11
        VK_W = ord('W')
        send_key_combination(hwnd, VK_CONTROL, VK_W)
        time.sleep(0.3)
        if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
            return
    except Exception:
        pass
    try:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE fallback
    except Exception:
        pass

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

def build_direct_oauth_url(url: str, target_email: str) -> str:
    """
    Transforms Google OAuth authorization URL into a direct account selection URL:
    1. Removes 'prompt=select_account' so Google does not force the Account Chooser.
    2. Injects 'login_hint={target_email}' to target the exact signed-in profile.
    3. Injects 'authuser={target_email}' and 'Email={target_email}'.
    """
    try:
        parsed = urlparse(url)
        if "accounts.google.com" not in parsed.netloc:
            return url
            
        params = parse_qs(parsed.query, keep_blank_values=True)
        # Remove prompt=select_account so Google doesn't force the chooser screen
        if "prompt" in params:
            prompts = [p for p in params["prompt"] if p != "select_account"]
            if prompts:
                params["prompt"] = prompts
            else:
                del params["prompt"]
                
        clean_email = target_email.strip()
        params["login_hint"] = [clean_email]
        params["authuser"] = [clean_email]
        params["Email"] = [clean_email]
        
        flat_params = []
        for k, v_list in params.items():
            for v in v_list:
                flat_params.append((k, v))
                
        new_query = urlencode(flat_params)
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
    except Exception as e:
        logger.warning(f"Error transforming OAuth URL: {e}")
        return url

def get_browser_url(hwnd: int) -> str:
    """Reads current tab URL via Ctrl+L / Ctrl+C without breaking page focus or erasing user clipboard."""
    old_clip = None
    try:
        old_clip = pyperclip.paste()
    except Exception:
        pass
        
    try:
        activate_browser_window(hwnd)
        pyperclip.copy("")
        send_key_combination(hwnd, 0x11, ord('L'))
        time.sleep(0.06)
        send_key_combination(hwnd, 0x11, ord('C'))
        
        url = ""
        for _ in range(4):
            time.sleep(0.05)
            url = pyperclip.paste().strip()
            if url:
                break
                
        # Return focus to web contents cleanly via F6
        send_single_key(hwnd, 0x75)  # VK_F6
        time.sleep(0.04)
        return url
    except Exception as e:
        logger.debug(f"Failed to copy browser URL: {e}")
        return ""
    finally:
        if old_clip is not None:
            try:
                pyperclip.copy(old_clip)
            except Exception:
                pass

def inject_url_in_browser(hwnd: int, new_url: str):
    """Navigates browser directly to new_url via address bar."""
    activate_browser_window(hwnd)
    pyperclip.copy(new_url)
    send_key_combination(hwnd, 0x11, ord('L'))
    time.sleep(0.06)
    send_key_combination(hwnd, 0x11, ord('V'))
    time.sleep(0.06)
    send_single_key(hwnd, 0x0D)  # VK_RETURN
    time.sleep(0.6)

def physical_click(x: int, y: int):
    """Moves physical cursor and fires mouse down/up on the interactive desktop."""
    switch_to_interactive_desktop()
    user32.SetCursorPos(x, y)
    time.sleep(0.04)
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.06)

def focus_web_contents_safely(hwnd: int):
    """
    Clicks in the empty margin on the far left of the browser window.
    Safely focuses the web contents document WITHOUT clicking any account button.
    """
    switch_to_interactive_desktop()
    rect = wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        safe_x = rect.left + 50
        safe_y = rect.top + 200
        physical_click(safe_x, safe_y)
        time.sleep(0.08)

def select_account_via_tabs(hwnd: int, target_email: str) -> bool:
    """
    Deterministic Tab navigation fallback for Google Account Chooser screen:
    1. Safely focuses web page body on empty margin.
    2. Resets DOM focus to the top with Ctrl+Home.
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
        idx = get_account_index(target_email)
        tab_count = idx + 2  # Standard Account Chooser sequence: 2, 3, 4, 5
        
    logger.info(f"Navigating Google Account Chooser for {target_email} with {tab_count} Tab presses...")
    activate_browser_window(hwnd)
    time.sleep(0.08)
    
    focus_web_contents_safely(hwnd)
    time.sleep(0.08)
    
    send_key_combination(hwnd, 0x11, 0x24)  # Ctrl + Home
    time.sleep(0.12)
    
    VK_TAB = 0x09
    for _ in range(tab_count):
        send_single_key(hwnd, VK_TAB)
        time.sleep(0.06)
        
    time.sleep(0.08)
    send_single_key(hwnd, 0x0D)  # VK_RETURN
    time.sleep(0.8)
    return True

def select_account_via_centered_click(hwnd: int, target_email: str) -> bool:
    """
    Calibrated centered physical click on Google Account Chooser row.
    Calculates viewport center accounting for the browser toolbar (~125px).
    CRITICAL: Never sends Enter after click to prevent confirming wrong accounts.
    """
    switch_to_interactive_desktop()
    activate_browser_window(hwnd)
    time.sleep(0.08)
    
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
        
    win_w = rect.right - rect.left
    win_h = rect.bottom - rect.top
    if win_w <= 0 or win_h <= 0:
        return False
        
    cx = rect.left + (win_w // 2)
    # Viewport center (accounting for browser toolbar ~125px)
    viewport_top = rect.top + 125
    viewport_height = max(300, win_h - 125)
    viewport_center_y = viewport_top + (viewport_height // 2)
    
    row_offset = get_account_row_offset(target_email)
    row_y = viewport_center_y + row_offset
    
    logger.info(f"Executing calibrated physical click on {target_email} at ({cx}, {row_y}) [offset: {row_offset}px]...")
    physical_click(cx, row_y)
    time.sleep(0.8)
    return True

def handle_external_google_signin(target_email: str, timeout_sec: int = 35) -> bool:
    """
    High-Reliability Google OAuth automation in external browser:
    1. Finds active browser window (strictly excluding Antigravity).
    2. Primary: Direct OAuth URL transformation (stripping prompt=select_account, injecting login_hint).
    3. Detects instant success (window title or redirect URL) and closes browser tab.
    4. Fallback 1: Calibrated centered physical click (without stray Enter key).
    5. Fallback 2: Deterministic Tab navigation.
    6. Handles consent prompts ('Continuar' / 'Permitir').
    """
    logger.info(f"Starting high-reliability Google Sign-In for target account: {target_email}...")
    switch_to_interactive_desktop()
    start_time = time.time()
    
    selection_attempts = 0
    last_url_check = 0.0
    cached_url = ""
    url_injected = False
    
    while time.time() - start_time < timeout_sec:
        hwnd = find_browser_window()
        if not hwnd:
            time.sleep(0.3)
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
            time.sleep(0.5)
            close_browser_tab(hwnd)
            logger.info("Closed authentication tab in browser.")
            return True
            
        # 2. Check URL at controlled intervals (every 0.5s)
        now = time.time()
        if now - last_url_check > 0.5:
            last_url_check = now
            cached_url = get_browser_url(hwnd)
            
            if "auth-success" in cached_url or ("localhost:" in cached_url and "code=" in cached_url):
                logger.info(f"Authentication success detected in URL: {cached_url}")
                time.sleep(0.5)
                close_browser_tab(hwnd)
                logger.info("Closed authentication tab in browser.")
                return True
                
            # PRIMARY ACCELERATION: Direct OAuth URL injection
            if not url_injected and "accounts.google.com" in cached_url:
                if "login_hint=" not in cached_url:
                    direct_url = build_direct_oauth_url(cached_url, target_email)
                    if direct_url and direct_url != cached_url:
                        logger.info(f"Injecting direct OAuth URL with login_hint={target_email}...")
                        inject_url_in_browser(hwnd, direct_url)
                        url_injected = True
                        time.sleep(0.6)
                        continue
                        
        # 3. Handle Account Chooser screen (Fallback if URL injection didn't bypass)
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
            
            # Fallback 1: Calibrated centered physical click
            select_account_via_centered_click(hwnd, target_email)
            time.sleep(1.0)
            
            # Fallback 2: If still on chooser after attempt 1, use deterministic Tab selection
            if selection_attempts >= 2:
                select_account_via_tabs(hwnd, target_email)
                time.sleep(1.2)
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
            time.sleep(0.08)
            send_single_key(hwnd, 0x09)  # Tab to primary button
            time.sleep(0.06)
            send_single_key(hwnd, 0x0D)  # Enter
            time.sleep(1.0)
            
        time.sleep(0.3)
        
    logger.warning("External Google Sign-In timed out.")
    return False
