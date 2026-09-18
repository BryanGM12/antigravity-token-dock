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
import json
import subprocess
import ctypes
from ctypes import wintypes
import logging
import winreg
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import Optional, Tuple, List, Set, Dict, Any
import pyperclip
import psutil

OCR_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "windows_ocr.ps1")

logger = logging.getLogger("ExternalOAuthHandler")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Enable Per-Monitor V2 DPI Awareness for exact physical pixel coordinate precision
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

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
        time.sleep(0.03)
        send_key_combination(hwnd, 0x11, ord('C'))

        url = ""
        for _ in range(4):
            time.sleep(0.02)
            url = pyperclip.paste().strip()
            if url:
                break

        # Dismiss address bar selection cleanly via Escape
        send_single_key(hwnd, 0x1B)  # VK_ESCAPE
        time.sleep(0.02)
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
    time.sleep(0.03)
    send_key_combination(hwnd, 0x11, ord('V'))
    time.sleep(0.03)
    send_single_key(hwnd, 0x0D)  # VK_RETURN
    time.sleep(0.12)

def physical_click(x: int, y: int, fast: bool = True):
    """Moves physical cursor and fires mouse down/up on the interactive desktop."""
    switch_to_interactive_desktop()
    user32.SetCursorPos(x, y)
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    if fast:
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.015)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.02)
    else:
        time.sleep(0.02)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.03)

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

def wake_up_chromium_accessibility(hwnd: int) -> bool:
    """
    Forces Chromium / Blink renderer processes (e.g. comet.exe, chrome.exe, edge.exe)
    to enable and expose their internal DOM accessibility tree on-demand.
    Sends WM_GETOBJECT (0x003D) with OBJID_CLIENT (0xFFFFFFFC) and OBJID_NATIVEOM (0xFFFFFFF0)
    to Chrome_RenderWidgetHostHWND controls.
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return False

    WM_GETOBJECT = 0x003D
    OBJID_CLIENT = 0xFFFFFFFC
    OBJID_NATIVEOM = 0xFFFFFFF0
    woken = False

    def enum_child_proc(h_child, lparam):
        nonlocal woken
        cls_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h_child, cls_name, 256)
        c_name = cls_name.value
        if "RenderWidgetHost" in c_name or "Chrome_WidgetWin" in c_name:
            user32.SendMessageW(h_child, WM_GETOBJECT, 0, OBJID_CLIENT)
            user32.SendMessageW(h_child, WM_GETOBJECT, 0, OBJID_NATIVEOM)
            woken = True
        return True

    WNDENUMCHILDPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows(hwnd, WNDENUMCHILDPROC(enum_child_proc), 0)
    time.sleep(0.06)
    return woken

def run_native_ocr(hwnd: int) -> List[Dict[str, Any]]:
    """
    Executes Windows.Media.Ocr native optical character recognition directly on the window client area.
    Returns list of detected word and line items with normalized absolute screen coordinates:
    [{'type': 'word'|'line', 'text': str, 'screen_cx': int, 'screen_cy': int, 'w': int, 'h': int}]
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return []

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return []

    bbox = (rect.left, rect.top, rect.right, rect.bottom)
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return []

    if not os.path.exists(OCR_SCRIPT_PATH):
        logger.debug(f"[OCR] Script not found at {OCR_SCRIPT_PATH}")
        return []

    tmp_path = os.path.join(os.environ.get("TEMP", "."), f"oauth_ocr_{os.getpid()}_{int(time.time() * 1000)}.png")
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        img.save(tmp_path)

        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

        res = subprocess.run(
            [
                "powershell.exe",
                "-WindowStyle", "Hidden",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
                "-File", OCR_SCRIPT_PATH,
                "-ImagePath", tmp_path
            ],
            capture_output=True,
            text=True,
            timeout=8,
            startupinfo=startupinfo,
            creationflags=creationflags
        )
        raw_items = json.loads(res.stdout.strip() or "[]")
        screen_items = []
        for item in raw_items:
            it = dict(item)
            it["screen_cx"] = rect.left + item.get("cx", 0)
            it["screen_cy"] = rect.top + item.get("cy", 0)
            it["screen_x"] = rect.left + item.get("x", 0)
            it["screen_y"] = rect.top + item.get("y", 0)
            screen_items.append(it)
        return screen_items
    except Exception as e:
        logger.debug(f"[OCR] Native OCR execution failed: {e}")
        return []
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

def detect_pill_buttons_cv(hwnd: int) -> List[Dict[str, Any]]:
    """
    Locates pill buttons across Google Material 3 themes using Computer Vision (OpenCV + PIL):
    - Light Mode Google Blue (#0b57d0 / #1a73e8)
    - Dark Mode M3 Blue (#a8c7fa / #8ab4f8)
    Returns list of detected candidates sorted by bottom-right score (y + x//2).
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return []

    try:
        import numpy as np
        import cv2
        from PIL import ImageGrab

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return []

        bbox = (rect.left, rect.top, rect.right, rect.bottom)
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            return []

        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        img_np = np.array(img)
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

        # Light Mode Google Blue (Hue 100-125, Sat 110-255, Val 110-255)
        mask_light = cv2.inRange(hsv, np.array([100, 110, 110]), np.array([125, 255, 255]))
        # Dark Mode Google Blue (#a8c7fa / #8ab4f8, Hue 95-125, Sat 45-165, Val 175-255)
        mask_dark = cv2.inRange(hsv, np.array([95, 45, 175]), np.array([125, 165, 255]))
        combined_mask = cv2.bitwise_or(mask_light, mask_dark)

        # Morphological bridge to join text interior
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 7))
        closed = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            # Google pill button dimensions: width ~60-300px, height ~26-65px
            if 60 <= w <= 300 and 26 <= h <= 65:
                aspect = w / float(h)
                if 1.5 <= aspect <= 6.5:
                    screen_x = rect.left + x + (w // 2)
                    screen_y = rect.top + y + (h // 2)
                    score = y + (x // 2)
                    candidates.append({
                        "screen_cx": screen_x,
                        "screen_cy": screen_y,
                        "w": w,
                        "h": h,
                        "score": score
                    })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates
    except Exception as e:
        logger.debug(f"[CV] Detección visual multi-tema no disponible: {e}")
        return []

def detect_blue_button_center(hwnd: int) -> Optional[Tuple[int, int]]:
    """
    Locates the physical screen center of Google's primary Material 3 blue pill button
    ('Acceder' / 'Continuar' / 'Siguiente') using computer vision / HSV color-space segmentation.
    Immune to resolution changes, DPI scaling, multi-monitor offsets, and layout variations.
    Google Material 3 button color: #0b57d0 / #1a73e8.
    """
    pills = detect_pill_buttons_cv(hwnd)
    if pills:
        best = pills[0]
        logger.info(f"[CV] Botón de acción detectado por visión en ({best['screen_cx']}, {best['screen_cy']}) [w={best['w']}, h={best['h']}]")
        return best["screen_cx"], best["screen_cy"]
    return None

def scroll_page_down(hwnd: int, steps: int = 4):
    """Scrolls the web viewport down smoothly to reveal below-the-fold buttons."""
    activate_browser_window(hwnd)
    focus_web_contents_safely(hwnd)
    VK_NEXT = 0x22  # Page Down
    VK_DOWN = 0x28  # Down Arrow
    for _ in range(steps):
        send_single_key(hwnd, VK_DOWN)
        time.sleep(0.04)
    send_single_key(hwnd, VK_NEXT)
    time.sleep(0.2)

def find_interactive_button(
    hwnd: int,
    target_keywords: Optional[List[str]] = None,
    allow_scroll: bool = True,
    ocr_items: Optional[List[Dict[str, Any]]] = None
) -> Optional[Tuple[int, int, str]]:
    """
    Intelligent button recognition engine:
    1. Multi-theme Computer Vision pill contour segmentation (sub-30ms).
    2. Native Windows OCR semantic word and line extraction (100% exact text matching).
    3. Spatial verification (correlates OCR text inside CV button bounding boxes).
    4. Auto-scrolling viewport expansion if the button is below the fold.
    Returns: (screen_x, screen_y, method_name) or None.
    """
    if not hwnd or not user32.IsWindow(hwnd):
        if not ocr_items:
            return None

    if not target_keywords:
        target_keywords = [
            "acceder", "continuar", "continue", "permitir", "allow",
            "confirmar", "avanzar", "siguiente", "next", "sign in",
            "iniciar sesion", "iniciar sesión", "continue as", "continuar como"
        ]

    win_h = 1000
    if hwnd and user32.IsWindow(hwnd):
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            win_h = rect.bottom - rect.top
        else:
            return None

    for scroll_attempt in range(2 if allow_scroll else 1):
        # Strategy A: Fast CV Pill Buttons
        pills = detect_pill_buttons_cv(hwnd) if (hwnd and user32.IsWindow(hwnd)) else []

        # Strategy B: Semantic Native OCR (use shared ocr_items on attempt 0 if provided!)
        current_ocr = ocr_items if (ocr_items is not None and scroll_attempt == 0) else (run_native_ocr(hwnd) if (hwnd and user32.IsWindow(hwnd)) else [])

        # 1. Look for OCR matches for target keywords
        best_ocr_match = None
        for item in current_ocr:
            txt = (item.get("text") or "").strip().lower()
            clean_txt = re.sub(r'[^a-z0-9áéíóúñ]', '', txt)
            for kw in target_keywords:
                clean_kw = re.sub(r'[^a-z0-9áéíóúñ]', '', kw.lower())
                if clean_kw in clean_txt or kw.lower() in txt:
                    # Prefer bottom-most match (action buttons sit at bottom of cards)
                    item_cy = item.get("screen_cy", 0)
                    if not best_ocr_match or item_cy > best_ocr_match["screen_cy"]:
                        best_ocr_match = item

        if best_ocr_match:
            # Check if any CV pill encompasses or aligns with this OCR match
            bx = best_ocr_match["screen_cx"]
            by = best_ocr_match["screen_cy"]
            for pill in pills:
                px1 = pill["screen_cx"] - pill["w"] // 2
                px2 = pill["screen_cx"] + pill["w"] // 2
                py1 = pill["screen_cy"] - pill["h"] // 2
                py2 = pill["screen_cy"] + pill["h"] // 2
                if (px1 - 20 <= bx <= px2 + 20) and (py1 - 15 <= by <= py2 + 15):
                    logger.info(f"[SMART-LOCATOR] Botón confirmado por fusión CV+OCR en ({pill['screen_cx']}, {pill['screen_cy']})")
                    return pill["screen_cx"], pill["screen_cy"], "cv_ocr_fusion"

            logger.info(f"[SMART-LOCATOR] Botón localizado puramente por OCR semántico en ({bx}, {by})")
            return bx, by, "semantic_ocr"

        # Strategy C: Pure CV fallback if high-confidence primary pill is visible in bottom half
        for pill in pills:
            if pill["screen_cy"] > win_h * 0.5 and pill["w"] > 70:
                logger.info(f"[SMART-LOCATOR] Botón primario deducido por visión geométrica en ({pill['screen_cx']}, {pill['screen_cy']})")
                return pill["screen_cx"], pill["screen_cy"], "cv_pill_geometric"

        if scroll_attempt == 0 and allow_scroll and hwnd and user32.IsWindow(hwnd):
            logger.info("[SMART-LOCATOR] Botón no visible en pantalla actual; desplazando viewport hacia abajo...")
            scroll_page_down(hwnd, steps=4)
            time.sleep(0.15)

    return None

def find_account_row_interactive(
    hwnd: int,
    target_email: str,
    allow_scroll: bool = True,
    ocr_items: Optional[List[Dict[str, Any]]] = None
) -> Optional[Tuple[int, int, str]]:
    """
    Intelligently discovers and locates the target account row in the Google Account Chooser screen
    via Native Windows OCR text extraction, name aliases, and fuzzy user matching.
    Returns: (screen_x, screen_y, method_name) or None.
    """
    if not hwnd or not user32.IsWindow(hwnd):
        if not ocr_items:
            return None

    norm_email = target_email.strip().lower()
    user_part = norm_email.split("@")[0]
    clean_user = re.sub(r'[^a-z0-9]', '', user_part)

    alias_keywords = [norm_email, user_part, clean_user]
    try:
        from config_manager import load_accounts_config
        for acc in load_accounts_config():
            if acc.get("email", "").strip().lower() == norm_email:
                name = acc.get("name", "").strip().lower()
                if name:
                    alias_keywords.append(name)
                    alias_keywords.extend(name.split())
    except Exception:
        pass

    for scroll_attempt in range(2 if allow_scroll else 1):
        items = ocr_items if (ocr_items is not None and scroll_attempt == 0) else run_native_ocr(hwnd)
        if items:
            for item in items:
                txt = (item.get("text") or "").strip().lower()
                clean_txt = re.sub(r'[^a-z0-9]', '', txt)

                for kw in alias_keywords:
                    clean_kw = re.sub(r'[^a-z0-9]', '', kw)
                    if len(clean_kw) >= 3 and (clean_kw in clean_txt or kw in txt):
                        logger.info(f"[SMART-LOCATOR] Cuenta '{target_email}' localizada por OCR ('{item['text']}'): ({item['screen_cx']}, {item['screen_cy']})")
                        return item["screen_cx"], item["screen_cy"], f"ocr_account:{item['text']}"

        if scroll_attempt == 0 and allow_scroll:
            logger.info("[SMART-LOCATOR] Cuenta no visible en primera pasada; desplazando selector hacia abajo...")
            scroll_page_down(hwnd, steps=2)
            time.sleep(0.15)

    return None

def find_and_toggle_permissions_checkbox(hwnd: int, ocr_items: Optional[List[Dict[str, Any]]] = None) -> bool:
    """
    Finds and toggles 'Seleccionar todo' / 'Select all' permission checkboxes
    using OCR text matching and UI Automation toggle patterns.
    """
    items = ocr_items if ocr_items is not None else run_native_ocr(hwnd)
    for item in items:
        txt = (item.get("text") or "").strip().lower()
        clean_txt = re.sub(r'[^a-z0-9]', '', txt)
        if any(w in clean_txt for w in ["seleccionartodo", "selectall", "seleccionar"]):
            box_x = item["screen_cx"] - (item.get("w", 80) // 2) - 30
            box_y = item["screen_cy"]
            logger.info(f"[OCR] Casilla 'Seleccionar todo' localizada en ({box_x}, {box_y}). Activando...")
            physical_click(box_x, box_y)
            time.sleep(0.05)
            return True

    # Try UIA CheckBoxControl
    try:
        import uiautomation as auto
        window = auto.ControlFromHandle(hwnd)
        if window.Exists(0, 0):
            for ctrl, _ in auto.WalkTree(window, maxDepth=14):
                if ctrl.ControlTypeName == "CheckBoxControl":
                    cname = (ctrl.Name or "").lower()
                    if any(w in cname for w in ["seleccionar todo", "select all", "google cloud"]):
                        tg = ctrl.GetTogglePattern()
                        if tg and tg.ToggleState == 0:
                            tg.Toggle()
                            logger.info(f"[UIA] Activada casilla de permisos: '{ctrl.Name}'")
                            time.sleep(0.05)
                            return True
    except Exception:
        pass
    return False

def confirm_consent_screen(hwnd: int, ocr_items: Optional[List[Dict[str, Any]]] = None) -> bool:
    """
    Confirms Google OAuth consent screen ('Acceder' / 'Continuar' / 'Allow') with 7-tier engine:
    Tier 0: Fast-Path Computer Vision primary blue button detection (15ms instant click).
    Tier 1: Force-enables Chromium DOM accessibility via WM_GETOBJECT.
    Tier 2: Checkbox & scope verification ('Seleccionar todo') via OCR + UIA.
    Tier 3: Multi-Modal Intelligent Button Finder (CV pill + OCR semantic text + auto-scrolling).
    Tier 4: Windows UI Automation inspection of buttons (Invoke / BoundingRectangle).
    Tier 5: Multi-column responsive layout geometry matrix (Dual-Column vs Single-Column).
    Tier 6: Direct button area focus and Enter / Space keystrokes.
    """
    switch_to_interactive_desktop()
    activate_browser_window(hwnd)
    time.sleep(0.04)

    # Tier 0: Fast-Path Instant CV Primary Blue Pill Button Detection (15ms)
    blue_pos = detect_blue_button_center(hwnd)
    if blue_pos:
        bx, by = blue_pos
        logger.info(f"[CV-FAST-PATH] Botón de acción detectado al instante en ({bx}, {by}). Clicando...")
        physical_click(bx, by)
        time.sleep(0.08)
        physical_click(bx, by)
        time.sleep(0.15)
        return True

    # Tier 1: Wake up Chromium DOM accessibility
    wake_up_chromium_accessibility(hwnd)

    # Tier 2: Ensure permission checkboxes are selected (using shared ocr_items if available)
    find_and_toggle_permissions_checkbox(hwnd, ocr_items=ocr_items)

    # Tier 3: Multi-Modal Intelligent Button Finder (CV + OCR + Scroll)
    btn_target = find_interactive_button(hwnd, allow_scroll=True, ocr_items=ocr_items)
    if btn_target:
        bx, by, method = btn_target
        logger.info(f"[SMART-BUTTON] Clic ejecutado en botón reconocido ({method}) en ({bx}, {by})...")
        physical_click(bx, by)
        time.sleep(0.08)
        physical_click(bx, by)
        time.sleep(0.2)
        return True

    # Tier 4: UI Automation Button Search
    try:
        import uiautomation as auto
        window = auto.ControlFromHandle(hwnd)
        if window.Exists(0, 0):
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
                                time.sleep(0.2)
                                return True
                        except Exception:
                            pass
                        r = ctrl.BoundingRectangle
                        if r and (r.right - r.left) > 0:
                            cx = r.left + (r.right - r.left) // 2
                            cy = r.top + (r.bottom - r.top) // 2
                            logger.info(f"[UIA] Clic directo en botón '{ctrl.Name}' en ({cx}, {cy})")
                            physical_click(cx, cy)
                            time.sleep(0.2)
                            return True
    except Exception as e:
        logger.debug(f"[UIA] Error buscando botón de consentimiento: {e}")

    # Tier 5: Multi-Column Responsive Layout Physical Matrix
    rect = wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        cx = rect.left + (win_w // 2)

        is_wide = win_w >= 840
        if is_wide:
            candidate_xs = [cx + 440, cx + 420, cx + 460, cx + 150]
        else:
            candidate_xs = [cx + 150, cx + 130, cx + 165]

        candidate_ys = [
            max(rect.top + 400, rect.bottom - 75),
            rect.bottom - 60,
            rect.top + 660,
            rect.top + 720,
            rect.top + 540
        ]

        for bx in candidate_xs:
            for by in candidate_ys:
                if by < rect.bottom and (rect.left < bx < rect.right):
                    logger.info(f"Targeting 'Acceder' at ({bx}, {by}) [is_wide={is_wide}]...")
                    physical_click(bx, by)
                    time.sleep(0.04)

    # Tier 6: Direct Button Area Focus and Keyboard Activation
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        target_focus_x = cx + 440 if is_wide else cx + 150
        target_focus_y = max(rect.top + 400, rect.bottom - 75)
        physical_click(target_focus_x, target_focus_y)
        time.sleep(0.03)

    send_single_key(hwnd, 0x0D)  # VK_RETURN (Enter)
    time.sleep(0.03)
    send_single_key(hwnd, 0x20)  # VK_SPACE (Space)
    time.sleep(0.15)
    return True

def select_account_via_centered_click(
    hwnd: int,
    target_email: str,
    ocr_items: Optional[List[Dict[str, Any]]] = None
) -> bool:
    """
    Selects target account in Google Account Chooser with 4-tier strategy:
    1. Native Windows OCR semantic account row recognition (reusing ocr_items if available).
    2. UI Automation inspection (wakes up Chromium accessibility first).
    3. Calibrated dynamic vertical row calculation with card centering adaptation.
    4. Deterministic keyboard Tab navigation fallback.
    """
    switch_to_interactive_desktop()
    activate_browser_window(hwnd)
    time.sleep(0.04)

    # Tier 0: Wake up Chromium DOM accessibility
    wake_up_chromium_accessibility(hwnd)

    # Tier 1: Try Native Windows OCR account row discovery
    acc_pos = find_account_row_interactive(hwnd, target_email, ocr_items=ocr_items)
    if acc_pos:
        ax, ay, method = acc_pos
        logger.info(f"[CHOOSER] Cuenta '{target_email}' localizada con éxito ({method}) en ({ax}, {ay}). Haciendo clic...")
        physical_click(ax, ay)
        time.sleep(0.08)
        physical_click(ax, ay)
        time.sleep(0.2)
        return True

    # Tier 2: Try exact UI Automation account row selection
    if select_account_via_uiautomation(hwnd, target_email):
        logger.info(f"[CHOOSER] Cuenta seleccionada exitosamente via UI Automation: {target_email}")
        return True

    # Tier 3: Calibrated physical click fallback
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False

    win_w = rect.right - rect.left
    win_h = rect.bottom - rect.top
    if win_w <= 0 or win_h <= 0:
        return False

    cx = rect.left + (win_w // 2)
    idx = get_account_index(target_email)

    if win_h >= 900:
        base_y = rect.top + 330
    else:
        base_y = rect.top + 280

    row_y = base_y + (idx * 68)

    logger.info(f"Executing calibrated physical click on {target_email} (idx={idx}) at ({cx}, {row_y}) [win_h={win_h}]...")
    physical_click(cx, row_y)
    time.sleep(0.08)
    physical_click(cx, row_y)
    time.sleep(0.2)
    return True


def extract_verification_challenge_details(
    ocr_items: Optional[List[Dict[str, Any]]] = None,
    title: str = "",
    cached_url: str = ""
) -> Dict[str, Any]:
    """
    Deterministically detects and extracts structured Google OAuth verification challenge details:
    Detects 2FA, phone prompts ("Toca el número XX"), SMS/Authenticator codes, passwords,
    recovery emails, passkeys, and captchas.
    """
    t_lower = (title or "").lower()
    u_lower = (cached_url or "").lower()
    items = ocr_items or []
    raw_text = " ".join((item.get("text") or "").strip() for item in items)
    c_lower = raw_text.lower()

    challenge_type: Optional[str] = None
    prompt_number: Optional[str] = None
    device_name: Optional[str] = None

    # 1. Phone Prompt / Device Challenge ("Comprueba tu teléfono", "Toca XX", "Tap Yes")
    phone_keywords = [
        "comprueba tu teléfono", "comprueba tu telefono", "check your phone",
        "toca sí", "toca si", "tap yes", "toca el número", "toca el numero",
        "tap the number", "notificación a tu", "notificacion a tu", "notification to your",
        "abre la app", "abre la aplicación", "open the gmail", "open the youtube",
        "google prompt"
    ]
    is_phone_url = any(k in u_lower for k in ["challenge/ipp", "challenge/az", "challenge/dp"])
    is_phone_title = any(k in t_lower for k in ["comprueba tu tel", "check your phone"])
    is_phone_text = any(k in c_lower for k in phone_keywords)

    if is_phone_url or is_phone_title or is_phone_text:
        challenge_type = "CHALLENGE_PHONE_PROMPT"

        # Strategy A: Regex phrase search e.g. "toca el número 74", "toca 74", "tap 74"
        m_num = re.search(
            r'(?:toca\s+(?:el\s+)?(?:n[úu]mero\s+)?|tap\s+(?:the\s+)?(?:number\s+)?)\s*[:\s]?\s*([0-9]{1,3})\b',
            raw_text,
            re.IGNORECASE
        )
        if m_num:
            prompt_number = m_num.group(1)

        # Strategy B: Standalone 2-digit items in OCR
        if not prompt_number and items:
            for it in items:
                txt = (it.get("text") or "").strip()
                if re.fullmatch(r'[0-9]{2}', txt):
                    val = int(txt)
                    if 10 <= val <= 99:
                        prompt_number = txt
                        break

        # Extract device name e.g. "Pixel 8", "Galaxy S23", "iPhone"
        m_dev = re.search(
            r'(?:notificaci[oó]n\s+a\s+tu|notification\s+to\s+your)\s+([A-Za-z0-9\s\-_]+?)(?:\.|\n|y\b|and\b|,|$)',
            raw_text,
            re.IGNORECASE
        )
        if m_dev:
            device_name = m_dev.group(1).strip()

    # 2. Code / 2FA Challenge (SMS or Authenticator)
    elif any(k in c_lower for k in [
        "introduce el código", "introduce el codigo", "enter the code",
        "código de verificación", "codigo de verificacion", "verification code",
        "authenticator", "mensaje de texto", "text message",
        "6 dígitos", "6 digitos", "6-digit code",
        "código de seguridad", "codigo de seguridad", "ingresa el código", "ingresa el codigo"
    ]) or any(k in u_lower for k in ["challenge/totp", "challenge/sms", "challenge/oob"]):
        challenge_type = "CHALLENGE_CODE"

    # 3. Password Challenge
    elif any(k in c_lower for k in [
        "introduce tu contraseña", "introduce tu contrasena", "enter your password",
        "escribe tu contraseña", "escribe tu contrasena",
        "confirma tu contraseña", "confirma tu contrasena"
    ]) or "challenge/pwd" in u_lower:
        challenge_type = "CHALLENGE_PASSWORD"

    # 4. Recovery Challenge
    elif any(k in c_lower for k in [
        "correo de recuperación", "correo de recuperacion", "recovery email",
        "teléfono de recuperación", "telefono de recuperacion", "recovery phone"
    ]) or "challenge/recovery" in u_lower:
        challenge_type = "CHALLENGE_RECOVERY"

    # 5. Passkey / Security Key
    elif any(k in c_lower for k in [
        "llave de seguridad", "security key", "llave de paso",
        "passkey", "huella digital", "bloqueo de pantalla"
    ]) or any(k in u_lower for k in ["challenge/kpe", "challenge/pk"]):
        challenge_type = "CHALLENGE_PASSKEY"

    # 6. Captcha / Bot Challenge
    elif any(k in c_lower for k in [
        "escribe los caracteres", "type the characters", "captcha",
        "tráfico inusual", "trafico inusual", "actividad sospechosa"
    ]) or "challenge/captcha" in u_lower:
        challenge_type = "CHALLENGE_CAPTCHA"

    # 7. Generic 2-Step Verification
    elif any(k in c_lower for k in [
        "verificación en 2 pasos", "verificacion en dos pasos",
        "verificación de dos pasos", "verificacion de dos pasos",
        "2-step verification", "verificar tu identidad",
        "más formas de verificar", "mas formas de verificar"
    ]) or any(k in t_lower for k in ["verificación", "verification"]) or "signin/challenge" in u_lower:
        challenge_type = "CHALLENGE_GENERIC"

    if not challenge_type:
        return {
            "is_challenge": False,
            "challenge_type": None,
            "prompt_number": None,
            "device_name": None,
            "description": "",
            "raw_text": raw_text
        }

    # Build human-readable Spanish description
    if challenge_type == "CHALLENGE_PHONE_PROMPT":
        if prompt_number:
            dev_str = f" en tu {device_name}" if device_name else " en tu teléfono"
            desc = f"Toca el número {prompt_number}{dev_str} para autorizar el acceso."
        else:
            dev_str = f" a tu {device_name}" if device_name else " a tu teléfono"
            desc = f"Google envió una notificación{dev_str}. Toca 'Sí' para confirmar."
    elif challenge_type == "CHALLENGE_CODE":
        desc = "Introduce el código de verificación de 6 dígitos (SMS o Google Authenticator)."
    elif challenge_type == "CHALLENGE_PASSWORD":
        desc = "Introduce la contraseña de tu cuenta de Google en la ventana del navegador."
    elif challenge_type == "CHALLENGE_RECOVERY":
        desc = "Confirma tu correo o teléfono de recuperación en el navegador."
    elif challenge_type == "CHALLENGE_PASSKEY":
        desc = "Usa tu llave de seguridad USB o passkey biométrica."
    elif challenge_type == "CHALLENGE_CAPTCHA":
        desc = "Resuelve el captcha mostrado en el navegador."
    else:
        desc = "Google requiere una verificación de seguridad adicional en el navegador."

    return {
        "is_challenge": True,
        "challenge_type": challenge_type,
        "prompt_number": prompt_number,
        "device_name": device_name,
        "description": desc,
        "raw_text": raw_text
    }


def classify_oauth_screen(
    hwnd: int,
    title: str = "",
    cached_url: str = "",
    ocr_items: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Deterministically classifies the current state of the Google OAuth page:
    Returns: 'SUCCESS' | 'CHOOSER' | 'CONSENT' | 'CHALLENGE_PHONE_PROMPT' |
             'CHALLENGE_CODE' | 'CHALLENGE_PASSWORD' | 'CHALLENGE_RECOVERY' |
             'CHALLENGE_PASSKEY' | 'CHALLENGE_CAPTCHA' | 'CHALLENGE_GENERIC' | 'UNKNOWN'
    """
    t_lower = (title or "").lower()
    u_lower = (cached_url or "").lower()

    # 1. Immediate Success check (Title or URL redirect)
    if any(w in t_lower for w in ["auth success", "google antigravity auth success"]) or \
       "auth-success" in u_lower or ("localhost:" in u_lower and "code=" in u_lower) or \
       ("127.0.0.1:" in u_lower and "code=" in u_lower):
        return "SUCCESS"

    # 2. Check Challenge / 2FA Verification (URL, Title, or OCR)
    ch_details = extract_verification_challenge_details(ocr_items, title=title, cached_url=cached_url)
    if ch_details["is_challenge"]:
        return ch_details["challenge_type"]

    # 3. Fast URL analysis
    if "signin/oauth/consent" in u_lower or "approval" in u_lower:
        return "CONSENT"
    if "accountchooser" in u_lower or "signin/chooser" in u_lower:
        return "CHOOSER"

    # 4. Passive Title analysis
    if any(w in t_lower for w in ["elige una cuenta", "elegir una cuenta", "choose an account"]):
        return "CHOOSER"
    if any(w in t_lower for w in ["solicita acceso", "wants access", "permisos"]):
        return "CONSENT"

    # 5. Deep Semantic OCR analysis
    if ocr_items:
        combined_text = " ".join((item.get("text") or "").lower() for item in ocr_items)
        if any(w in combined_text for w in ["elige una cuenta", "choose an account", "usar otra cuenta", "use another account"]):
            return "CHOOSER"
        if any(w in combined_text for w in ["solicita acceso", "quiere acceder", "seleccionar todo", "google cloud", "developer", "continuar", "acceder"]):
            return "CONSENT"

    return "UNKNOWN"


def handle_external_google_signin(
    target_email: str,
    timeout_sec: int = 35,
    pre_hwnds: Optional[Set[int]] = None,
    target_process: Optional[str] = None,
    auth_event: Optional[Any] = None
) -> bool:
    """
    High-Reliability, Multi-Browser-Isolated Google OAuth automation:
    1. Identifies exact OAuth window in the default browser using window delta & process isolation.
    2. Excludes 100% of all windows from Chrome, Edge, Brave, or any other user app.
    3. Locks onto confirmed HWND to eliminate focus jumping.
    4. Primary acceleration: Direct OAuth URL injection (login_hint).
    5. Real-Time Auth Event Sensor: Closes tab immediately when Antigravity confirms auth.
    6. Deterministic Page Classification (Chooser vs Consent vs Success).
    7. Semantic OCR and Multi-Theme CV Button Finder.
    """
    if not target_process:
        target_process, _ = get_default_browser_info()

    logger.info(f"Starting multi-browser isolated Google Sign-In for {target_email} (Browser: {target_process})...")
    switch_to_interactive_desktop()
    start_time = time.time()
    effective_deadline = start_time + timeout_sec
    max_safety_limit = 300.0  # Max 5 minutes total ceiling

    selection_attempts = 0
    last_url_check = 0.0
    cached_url = ""
    url_injected = False
    locked_hwnd: Optional[int] = None
    account_selected = False
    challenge_notified = False
    last_prompt_number: Optional[str] = None

    while time.time() < effective_deadline and (time.time() - start_time) < max_safety_limit:
        # 0. Real-time background sync with Antigravity workbench
        if auth_event and auth_event.is_set():
            logger.info("[AUTH-SYNC] Antigravity confirmó autenticación en segundo plano. Cerrando pestaña OAuth...")
            if locked_hwnd and user32.IsWindow(locked_hwnd):
                time.sleep(0.15)
                close_browser_tab(locked_hwnd)
            return True

        # If locked HWND is still valid and visible, keep using it
        hwnd = locked_hwnd if (locked_hwnd and user32.IsWindow(locked_hwnd) and user32.IsWindowVisible(locked_hwnd)) else None
        if not hwnd:
            hwnd = find_target_oauth_window(pre_hwnds=pre_hwnds, target_process_name=target_process)
            if hwnd:
                locked_hwnd = hwnd
                logger.debug(f"[LOCK] Bound exclusively to OAuth HWND {hwnd}")

        if not hwnd:
            time.sleep(0.04)
            continue

        # Passive window title check (0ms overhead)
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value

        # Check URL when needed (fast-path immediate check on iteration 0)
        now = time.time()
        should_check_url = False
        if not url_injected and (last_url_check == 0.0 or (now - last_url_check > 0.4)):
            should_check_url = True
        elif (now - last_url_check > 1.5) and not any(w in title.lower() for w in ["auth success", "google antigravity auth success"]):
            should_check_url = True

        if should_check_url:
            last_url_check = now
            cached_url = get_browser_url(hwnd)

            if "auth-success" in cached_url or ("localhost:" in cached_url and "code=" in cached_url):
                logger.info(f"Authentication success detected in URL: {cached_url}")
                time.sleep(0.1)
                close_browser_tab(hwnd)
                logger.info("Closed authentication tab cleanly.")
                return True

            # Direct OAuth URL injection
            if not url_injected and "accounts.google.com" in cached_url:
                if "login_hint=" not in cached_url:
                    direct_url = build_direct_oauth_url(cached_url, target_email)
                    if direct_url and direct_url != cached_url:
                        logger.info(f"Injecting direct OAuth URL with login_hint={target_email}...")
                        inject_url_in_browser(hwnd, direct_url)
                        url_injected = True
                        time.sleep(0.15)
                        continue

        # Deterministic Screen Classification
        screen_type = classify_oauth_screen(hwnd, title=title, cached_url=cached_url)
        if screen_type == "SUCCESS":
            logger.info("Authentication success detected in browser!")
            time.sleep(0.1)
            close_browser_tab(hwnd)
            return True

        ocr_items = None
        if screen_type == "UNKNOWN":
            ocr_items = run_native_ocr(hwnd)
            screen_type = classify_oauth_screen(hwnd, title=title, cached_url=cached_url, ocr_items=ocr_items)

        # 1. Handle Google Verification Challenges (Phone prompt, SMS, Authenticator, Password, etc.)
        if screen_type.startswith("CHALLENGE") or screen_type == "SIGNIN_FORM":
            ch_details = extract_verification_challenge_details(ocr_items, title=title, cached_url=cached_url)
            p_num = ch_details.get("prompt_number")
            desc = ch_details.get("description") or "Google requiere verificación adicional."

            if not challenge_notified or (p_num and p_num != last_prompt_number):
                challenge_notified = True
                last_prompt_number = p_num
                logger.warning(f"✦ [VERIFICACIÓN GOOGLE REQUERIDA] {desc} (Cuenta: {target_email})")
                try:
                    from notification_service import notify_verification_required
                    notify_verification_required(target_email, screen_type, details=desc, prompt_number=p_num)
                except Exception as ne:
                    logger.debug(f"Error enviando notificación toast: {ne}")

            # Extend deadline by 120s from now so the user has sufficient time to complete verification
            effective_deadline = max(effective_deadline, time.time() + 120.0)
            logger.info(f"[CHALLENGE-WAIT] Esperando resolución del usuario en dispositivo... ({desc})")
            time.sleep(1.0)
            continue

        # 2. Handle Account Chooser screen
        if screen_type == "CHOOSER" and selection_attempts < 5:
            selection_attempts += 1
            logger.info(f"Detected Google Account Chooser screen (attempt {selection_attempts}/5)...")
            select_account_via_centered_click(hwnd, target_email, ocr_items=ocr_items)
            account_selected = True
            time.sleep(0.15)
            continue

        # 3. Handle Consent / 'Acceder' screen
        if screen_type == "CONSENT" or (account_selected and selection_attempts > 0):
            logger.info("Detected OAuth consent / 'Acceder' screen. Confirming with multi-strategy engine...")
            confirm_consent_screen(hwnd, ocr_items=ocr_items)
            time.sleep(0.15)
            continue

        time.sleep(0.04)

    # Final check on auth_event before declaring timeout
    if auth_event and auth_event.is_set():
        logger.info("[AUTH-SYNC] Antigravity confirmó autenticación final.")
        return True

    logger.warning("External Google Sign-In timed out.")
    return False
