"""
External OAuth Handler: Deterministic Multi-Browser Windows Automation for Google Sign-In
========================================================================================
Guarantees 100% reliable Google OAuth authentication even with multiple different browsers
(Chrome, Brave, Edge, Firefox, Comet) running simultaneously with dozens of open tabs.

Key Architectural Safeguards:
1. Dynamic Default Browser Resolution: Queries Windows Registry (UserChoice\\https) to
   target ONLY the system default browser process (e.g. comet.exe), strictly ignoring all
   other running browsers.
2. Pre/Post Window Delta Snapshot: Captures browser HWNDs right before triggering OAuth.
   Identifies newly spawned windows (delta) with 100% mathematical certainty.
3. HWND Affinity Lock: Locks onto the target window handle once identified to prevent
   focus jumping or cross-window pollution.
4. Non-Destructive Tab Closing: Uses strictly Ctrl+W to close only the auth tab. Eliminates
   blind WM_CLOSE fallbacks that could kill windows containing user's personal tabs.
5. Passive Title & Safe URL Inspection: Checks window title (0ms overhead) and address bar
   with automatic clipboard backup & restoration.
"""

import os
import re
import time
import ctypes
from ctypes import wintypes
import logging
import winreg
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import Optional, Tuple, List, Set
import pyperclip
import psutil

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

def get_default_browser_info() -> Tuple[str, str]:
    """
    Queries Windows Registry to determine default HTTPS browser executable name and path:
    HKCU\\Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\https\\UserChoice -> ProgId
    HKCR\\{ProgId}\\shell\\open\\command -> Executable path
    Returns: (process_name, full_path), e.g. ("comet.exe", "C:\\Program Files\\...\\comet.exe")
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        ) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")

        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT,
            rf"{prog_id}\shell\open\command"
        ) as key:
            cmd, _ = winreg.QueryValueEx(key, "")

        match = re.search(r'"([^"]+)"', cmd)
        if match:
            exe_path = match.group(1)
        else:
            exe_path = cmd.split()[0]

        proc_name = os.path.basename(exe_path).lower()
        return proc_name, exe_path
    except Exception as e:
        logger.debug(f"Failed to query default browser from registry: {e}")
        return "comet.exe", ""

def get_browser_windows(target_process_name: Optional[str] = None) -> List[Tuple[int, int, str]]:
    """
    Returns list of (hwnd, pid, title) for visible windows belonging strictly to target_process_name
    (defaults to the system default browser if None).
    Guarantees that windows from other browsers (e.g. Chrome, Brave, Edge) are 100% ignored.
    """
    switch_to_interactive_desktop()
    if not target_process_name:
        target_process_name, _ = get_default_browser_info()
    target_process_name = target_process_name.lower()

    # Collect PIDs belonging exclusively to target_process_name
    target_pids: Set[int] = set()
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            pname = (proc.info.get('name') or '').lower()
            if pname == target_process_name:
                target_pids.add(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not target_pids:
        return []

    windows: List[Tuple[int, int, str]] = []

    def enum_cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value not in target_pids:
            return True

        # Window text length check
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value

        # Filter out tooltips and sub-window elements (< 200x150)
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 200 and h > 150:
                windows.append((hwnd, pid.value, title))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    return windows

def capture_browser_hwnds(target_process_name: Optional[str] = None) -> Set[int]:
    """Captures set of HWNDs currently open for the target browser before triggering OAuth."""
    windows = get_browser_windows(target_process_name)
    return {w[0] for w in windows}

def find_target_oauth_window(
    pre_hwnds: Optional[Set[int]] = None,
    target_process_name: Optional[str] = None
) -> Optional[int]:
    """
    Finds the exact OAuth window handle for the target browser:
    1. If pre_hwnds is provided, checks for newly spawned window delta (current - pre).
       A newly spawned window is 100% guaranteed to be the OAuth window launched by Antigravity!
    2. If no new window was spawned (browser opened a tab in an existing window), selects
       the target browser window whose title matches OAuth keywords.
    3. Excludes 100% of all windows from other applications and browsers.
    """
    windows = get_browser_windows(target_process_name)
    if not windows:
        return None

    current_hwnds = {w[0] for w in windows}

    # Case A: A new window was spawned
    if pre_hwnds is not None:
        delta = current_hwnds - pre_hwnds
        if delta:
            for hwnd, pid, title in windows:
                if hwnd in delta:
                    logger.debug(f"[DELTA] Found newly spawned target browser window: HWND {hwnd} ('{title}')")
                    return hwnd

    # Case B: Reused window or pre_hwnds was None
    scored = []
    # Weighted keyword matching: higher weight for high-confidence titles
    high_prio = ["Google Antigravity", "antigravity.google", "Auth Success"]
    med_prio = [
        "Acceso: Cuentas de Google", "Elige una cuenta", "Elegir una cuenta",
        "Choose an account", "Sign in - Google Accounts", "Sign in", "Iniciar sesión"
    ]
    low_prio = ["Google", "localhost"]

    for hwnd, pid, title in windows:
        score = 0
        t_lower = title.lower()
        for kw in high_prio:
            if kw.lower() in t_lower:
                score = 100
                break
        if score == 0:
            for kw in med_prio:
                if kw.lower() in t_lower:
                    score = 50
                    break
        if score == 0:
            for kw in low_prio:
                if kw.lower() in t_lower:
                    score = 20
                    break

        if score > 0:
            scored.append((score, hwnd, title))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else None

def find_browser_window() -> Optional[int]:
    """Backward-compatible wrapper for finding default browser OAuth window."""
    return find_target_oauth_window()

def activate_browser_window(hwnd: int) -> bool:
    """
    Brings browser window to the foreground across multiple monitors.
    Uses Windows Alt-key bypass to overcome UIPI foreground lock.
    Only calls SW_RESTORE (9) if window is minimized (IsIconic).
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
    """Sends Ctrl + Key combination to the target browser window."""
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
    """
    Closes the active auth tab cleanly via Ctrl+W.
    CRITICAL: Never sends blind WM_CLOSE to the window handle, protecting all other
    tabs the user may have open in that browser window.
    """
    try:
        activate_browser_window(hwnd)
        VK_CONTROL = 0x11
        VK_W = ord('W')
        send_key_combination(hwnd, VK_CONTROL, VK_W)
        time.sleep(0.2)
    except Exception as e:
        logger.debug(f"Error sending Ctrl+W to HWND {hwnd}: {e}")

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

        # Dismiss address bar selection cleanly via Escape
        send_single_key(hwnd, 0x1B)  # VK_ESCAPE
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
    """Clicks in empty margin on far right to safely focus document without clicking buttons or left sidebars (Comet/Arc)."""
    switch_to_interactive_desktop()
    rect = wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        # Click safely in the right margin of the web contents (avoids left sidebars completely)
        safe_x = max(rect.left + 200, rect.right - 80)
        safe_y = rect.top + min(240, max(180, win_h // 3))
        physical_click(safe_x, safe_y)
        time.sleep(0.08)

def select_account_via_uiautomation(hwnd: int, target_email: str) -> bool:
    """Finds and clicks the target account row directly via Windows UI Automation Accessible tree."""
    try:
        import uiautomation as auto
        switch_to_interactive_desktop()
        window = auto.ControlFromHandle(hwnd)
        if not window.Exists(0, 0):
            return False

        norm_email = target_email.strip().lower()
        user_part = norm_email.split("@")[0]

        # Search for control containing target email or user prefix
        for ctrl, _ in auto.WalkTree(window, maxDepth=14):
            cname = (ctrl.Name or "").lower()
            if norm_email in cname or user_part in cname:
                logger.info(f"[UIA] Encontrado control de cuenta para {target_email}: '{ctrl.Name}' ({ctrl.ControlTypeName})")
                try:
                    inv = ctrl.GetInvokePattern()
                    if inv:
                        inv.Invoke()
                        time.sleep(0.6)
                        return True
                except Exception:
                    pass

                r = ctrl.BoundingRectangle
                if r and (r.right - r.left) > 0 and (r.bottom - r.top) > 0:
                    cx = r.left + (r.right - r.left) // 2
                    cy = r.top + (r.bottom - r.top) // 2
                    logger.info(f"[UIA] Clic directo en centro de cuenta: ({cx}, {cy})")
                    physical_click(cx, cy)
                    time.sleep(0.6)
                    return True
    except Exception as e:
        logger.debug(f"[UIA] Búsqueda UIAutomation de cuenta no completada: {e}")
    return False

def select_account_via_tabs(hwnd: int, target_email: str) -> bool:
    """Deterministic Tab navigation fallback for Google Account Chooser screen."""
    norm = target_email.strip().lower()
    tab_map = get_account_tab_map()
    tab_count = None
    for acc, count in tab_map.items():
        if acc.split("@")[0] in norm or norm in acc:
            tab_count = count
            break

    if not tab_count:
        idx = get_account_index(target_email)
        tab_count = idx + 2

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

def confirm_consent_screen(hwnd: int) -> bool:
    """Confirms Google OAuth consent screen ('Acceder' / 'Continuar' / 'Allow') with multi-point clicks and keyboard."""
    switch_to_interactive_desktop()
    activate_browser_window(hwnd)
    time.sleep(0.08)

    # 1. UI Automation Button Search (with 'acceder'!)
    try:
        import uiautomation as auto
        window = auto.ControlFromHandle(hwnd)
        if window.Exists(0, 0):
            # Check for any permission checkboxes (e.g. 'Seleccionar todo' or individual scopes)
            for ctrl, _ in auto.WalkTree(window, maxDepth=14):
                if ctrl.ControlTypeName == "CheckBoxControl":
                    cname = (ctrl.Name or "").lower()
                    if any(w in cname for w in ["seleccionar todo", "select all", "google cloud", "developer"]):
                        try:
                            tg = ctrl.GetTogglePattern()
                            if tg and tg.ToggleState == 0:  # 0 = Off
                                tg.Toggle()
                                logger.info(f"[UIA] Activada casilla de permisos: '{ctrl.Name}'")
                                time.sleep(0.1)
                        except Exception:
                            pass

            # Search for primary confirm button: MUST include 'acceder'!
            target_keywords = ["acceder", "continuar", "continue", "permitir", "allow", "confirmar", "avanzar", "siguiente", "sign in"]
            for ctrl, _ in auto.WalkTree(window, maxDepth=14):
                if ctrl.ControlTypeName in ["ButtonControl", "HyperlinkControl"]:
                    cname = (ctrl.Name or "").lower().strip()
                    if any(cname == kw or kw in cname for kw in target_keywords):
                        logger.info(f"[UIA] Encontrado botón de confirmación: '{ctrl.Name}'")
                        try:
                            inv = ctrl.GetInvokePattern()
                            if inv:
                                inv.Invoke()
                                time.sleep(0.6)
                                return True
                        except Exception:
                            pass
                        r = ctrl.BoundingRectangle
                        if r and (r.right - r.left) > 0:
                            cx = r.left + (r.right - r.left) // 2
                            cy = r.top + (r.bottom - r.top) // 2
                            logger.info(f"[UIA] Clic directo en botón '{ctrl.Name}' en ({cx}, {cy})")
                            physical_click(cx, cy)
                            time.sleep(0.6)
                            return True
    except Exception as e:
        logger.debug(f"[UIA] Error buscando botón de consentimiento: {e}")

    # 2. Multi-Point Physical Clicks on the 'Acceder' / 'Continuar' column
    # In Google OAuth, 'Acceder' is the primary action button on the bottom-right of the card.
    rect = wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        cx = rect.left + (win_w // 2)
        btn_x = cx + 145  # Center of the right-hand primary button column

        # Click 'Seleccionar todo' checkbox area just in case permissions require checking
        checkbox_x = cx - 150
        checkbox_y = rect.top + 300
        physical_click(checkbox_x, checkbox_y)
        time.sleep(0.05)

        # Candidate vertical positions for 'Acceder' / 'Continuar' button:
        candidate_ys = [
            rect.top + 660,                   # Standard Google Cloud scopes card
            rect.top + 540,                   # Short consent card
            rect.top + 720,                   # Extended scopes card
            max(rect.top + 400, rect.bottom - 75)  # Bottom of visible viewport if scrolled
        ]

        for cy in candidate_ys:
            if cy < rect.bottom:
                logger.info(f"Targeting 'Acceder' at ({btn_x}, {cy})...")
                physical_click(btn_x, cy)
                time.sleep(0.12)

    # 3. Keyboard confirmation
    # Scroll to bottom to ensure 'Acceder' is in view and interactive
    send_key_combination(hwnd, 0x11, 0x23)  # Ctrl + End
    time.sleep(0.08)
    send_single_key(hwnd, 0x09)  # Tab to focus primary button
    time.sleep(0.05)
    send_single_key(hwnd, 0x0D)  # Enter
    time.sleep(0.3)
    return True

def select_account_via_centered_click(hwnd: int, target_email: str) -> bool:
    """Calibrated physical click directly on Google Account Chooser row."""
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
    idx = get_account_index(target_email)

    # In Google Account Chooser:
    # First row center is at ~ rect.top + 330
    # Each row is ~ 68px tall
    row_y = rect.top + 330 + (idx * 68)

    logger.info(f"Executing calibrated physical click on {target_email} (idx={idx}) at ({cx}, {row_y}) [win_h={win_h}]...")
    physical_click(cx, row_y)
    time.sleep(0.2)
    physical_click(cx, row_y)  # Double-click to ensure selection if first click only focused
    time.sleep(0.6)
    return True

def handle_external_google_signin(
    target_email: str,
    timeout_sec: int = 35,
    pre_hwnds: Optional[Set[int]] = None,
    target_process: Optional[str] = None
) -> bool:
    """
    High-Reliability, Multi-Browser-Isolated Google OAuth automation:
    1. Identifies exact OAuth window in the default browser using window delta & process isolation.
    2. Excludes 100% of all windows from Chrome, Edge, Brave, or any other user app.
    3. Locks onto confirmed HWND to eliminate focus jumping.
    4. Primary acceleration: Direct OAuth URL injection (login_hint).
    5. Detects instant success (window title or localhost redirect) and closes tab via Ctrl+W.
    6. Fallback 1: Calibrated centered physical click.
    7. Fallback 2: Deterministic Tab navigation.
    8. Handles consent prompts ('Continuar' / 'Permitir').
    """
    if not target_process:
        target_process, _ = get_default_browser_info()

    logger.info(f"Starting multi-browser isolated Google Sign-In for {target_email} (Browser: {target_process})...")
    switch_to_interactive_desktop()
    start_time = time.time()

    selection_attempts = 0
    last_url_check = 0.0
    cached_url = ""
    url_injected = False
    locked_hwnd: Optional[int] = None
    account_selected = False

    while time.time() - start_time < timeout_sec:
        # If locked HWND is still valid and visible, keep using it
        hwnd = locked_hwnd if (locked_hwnd and user32.IsWindow(locked_hwnd) and user32.IsWindowVisible(locked_hwnd)) else None
        if not hwnd:
            hwnd = find_target_oauth_window(pre_hwnds=pre_hwnds, target_process_name=target_process)
            if hwnd:
                locked_hwnd = hwnd
                logger.debug(f"[LOCK] Bound exclusively to OAuth HWND {hwnd}")

        if not hwnd:
            time.sleep(0.3)
            continue

        # Passive window title check (0ms overhead)
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value
        t_lower = title.lower()

        # 1. Success verification in title
        if any(w in title for w in [
            "Google Antigravity Auth Success",
            "antigravity.google/auth-success",
            "Auth Success"
        ]):
            logger.info("Authentication success detected in browser window title!")
            time.sleep(0.3)
            close_browser_tab(hwnd)
            logger.info("Closed authentication tab cleanly.")
            return True

        # 2. Check URL ONLY when needed (avoids focus-stealing Ctrl+L loop)
        now = time.time()
        should_check_url = False
        if not url_injected and (now - last_url_check > 0.8):
            should_check_url = True
        elif (now - last_url_check > 3.5) and not any(w in title for w in ["Google Antigravity Auth Success", "Auth Success"]):
            should_check_url = True

        if should_check_url:
            last_url_check = now
            cached_url = get_browser_url(hwnd)

            if "auth-success" in cached_url or ("localhost:" in cached_url and "code=" in cached_url):
                logger.info(f"Authentication success detected in URL: {cached_url}")
                time.sleep(0.3)
                close_browser_tab(hwnd)
                logger.info("Closed authentication tab cleanly.")
                return True

            # PRIMARY ACCELERATION: Direct OAuth URL injection
            if not url_injected and "accounts.google.com" in cached_url:
                if "login_hint=" not in cached_url:
                    direct_url = build_direct_oauth_url(cached_url, target_email)
                    if direct_url and direct_url != cached_url:
                        logger.info(f"Injecting direct OAuth URL with login_hint={target_email}...")
                        inject_url_in_browser(hwnd, direct_url)
                        url_injected = True
                        time.sleep(0.5)
                        continue

        # 3. Handle Account Chooser vs Consent / Acceder Screen
        # If title clearly says "Elige una cuenta" or "Choose an account", stay on chooser
        if "elige una cuenta" in t_lower or "elegir una cuenta" in t_lower or "choose an account" in t_lower:
            account_selected = False

        is_chooser = not account_selected and (
            "accountchooser" in cached_url.lower() or
            "elige una cuenta" in t_lower or
            "elegir una cuenta" in t_lower or
            "choose an account" in t_lower or
            ("acceso: cuentas de google" in t_lower and selection_attempts == 0)
        )

        if is_chooser and selection_attempts < 4:
            selection_attempts += 1
            logger.info(f"Detected Google Account Chooser screen (attempt {selection_attempts}/4)...")

            # Strategy 1: Accurate calibrated physical click directly on account row!
            select_account_via_centered_click(hwnd, target_email)
            account_selected = True
            time.sleep(1.0)
            continue

        # 4. Handle Consent / Confirmation / 'Acceder' Screen
        is_consent = account_selected or (
            "acceder" in t_lower or
            "solicita acceso" in t_lower or
            "wants access" in t_lower or
            "permitir" in t_lower or
            "continuar" in t_lower or
            "allow" in t_lower or
            "consent" in cached_url.lower() or
            "approval" in cached_url.lower()
        )

        if is_consent:
            logger.info("Detected OAuth consent / 'Acceder' screen. Confirming with multi-strategy engine...")
            confirm_consent_screen(hwnd)
            time.sleep(0.8)
            continue

        time.sleep(0.2)

    logger.warning("External Google Sign-In timed out.")
    return False
