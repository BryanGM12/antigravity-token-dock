#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Docked Token Hub & Account Switcher (Animated Minimalist Edition)
=============================================================================
Features:
- Native Antigravity Design System:
    - Deep Obsidian surfaces (#14161b / #181b22) with Antigravity Blue (#528bff) and Gemini Violet (#c084fc).
    - Google AI signature top gradient line (#528bff -> #818cf8 -> #c084fc -> #f472b6).
    - Ultra-thin 4px progress bars, micro-badges, and clean monospace countdowns.
- Fluid Animations & Micro-Interactions:
    - Smooth slide expand / collapse transition (QVariantAnimation with OutCubic easing).
    - Breathing live-heartbeat pulsing glow on the active account badge.
    - Animated rotating sync icon during live CDP extraction.
- Zero-Lag Win32 Tracking Engine:
    - SetWinEventHook listening on EVENT_OBJECT_LOCATIONCHANGE for instantaneous drag sync.
    - Adaptive 25ms/80ms heartbeat timer with MonitorFromWindow taskbar exclusion.
    - Direct user32.SetWindowPos hardware repositioning.
    - Smart docking: Outside right -> Outside left -> Inside top-right when maximized.
- Privacy-Hardened Multi-Account Swarm:
    - Loads accounts dynamically via config_manager without exposing private credentials.
    - Dedicated "⇄ Cambiar a esta cuenta" switcher with live status banner.
"""

import os
import sys
import json
import time
import math
import ctypes
import subprocess
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

# Ensure connection to interactive desktop
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

try:
    hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
    if hdesk:
        user32.SetThreadDesktop(hdesk)
except Exception:
    pass

import winsound
import webbrowser
import psutil
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QSize, QPoint, QRect,
    QVariantAnimation, QEasingCurve, QAbstractAnimation
)
from PyQt6.QtGui import (
    QColor, QFont, QCursor, QPainter, QBrush, QPen, QPainterPath, QIcon, QPixmap
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QScrollArea, QFrame, QGraphicsDropShadowEffect,
    QDialog, QLineEdit, QCheckBox, QSystemTrayIcon, QMenu, QFileDialog, QMessageBox,
    QGraphicsOpacityEffect
)

from config_manager import (
    get_authorized_accounts, load_accounts_config, add_account,
    is_windows_startup_enabled, set_windows_startup,
    export_accounts_backup, import_accounts_backup
)
from token_memory import (
    is_auto_switch_enabled, set_auto_switch_enabled,
    get_pinned_account, set_pinned_account,
    is_sound_enabled, set_sound_enabled,
    load_memory, get_effective_account_status
)
from notification_service import notify_auto_switch_toggled, send_windows_toast

class AudioChimeEngine:
    """Discreet, elegant synthesized sound feedback using native Windows sound aliases."""
    @staticmethod
    def play_switch_success():
        if is_sound_enabled():
            try:
                winsound.PlaySound('SystemAsterisk', winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass

    @staticmethod
    def play_refresh():
        if is_sound_enabled():
            try:
                winsound.PlaySound('DeviceConnect', winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass

    @staticmethod
    def play_toggle():
        if is_sound_enabled():
            try:
                winsound.PlaySound('SystemDefault', winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass

    @staticmethod
    def play_alert():
        if is_sound_enabled():
            try:
                winsound.PlaySound('SystemExclamation', winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass

class GlobalHotkeyThread(QThread):
    """Listens for global Windows hotkey Ctrl+Alt+T across all running applications."""
    hotkey_triggered = pyqtSignal()
    def __init__(self):
        super().__init__()
        self._running = True

    def run(self):
        HOTKEY_ID = 0x9001
        MOD_CONTROL = 0x0002
        MOD_ALT = 0x0001
        VK_T = ord('T')
        user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_T)
        msg = wintypes.MSG()
        while self._running:
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:
                    self.hotkey_triggered.emit()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.04)
        user32.UnregisterHotKey(None, HOTKEY_ID)

    def stop(self):
        self._running = False

# Paths & Win32 constants
BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".openclaw" / "workspace" / "state" / "antigravity_controller"
MEMORY_FILE = STATE_DIR / "token_memory.json"
DAEMON_SCRIPT = BASE_DIR / "daemon_service.py"

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
WINEVENT_OUTOFCONTEXT = 0x0000

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('rcMonitor', wintypes.RECT),
        ('rcWork', wintypes.RECT),
        ('dwFlags', wintypes.DWORD)
    ]

def find_antigravity_hwnd() -> Optional[int]:
    """Finds the primary active HWND of Antigravity.exe."""
    antigravity_pids = set()
    for p in psutil.process_iter(['pid', 'name']):
        try:
            if 'antigravity' in (p.info.get('name') or '').lower():
                antigravity_pids.add(p.info['pid'])
        except Exception:
            pass

    if not antigravity_pids:
        return None

    best_hwnd = None
    best_area = 0

    def enum_cb(hwnd, lparam):
        nonlocal best_hwnd, best_area
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in antigravity_pids:
            rect = wintypes.RECT()
            hr = dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
            if hr != 0:
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 400 and h > 300:
                area = w * h
                if area > best_area:
                    best_area = area
                    best_hwnd = hwnd
        return True

    WNDENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUM(enum_cb), 0)
    return best_hwnd

class WorkerSwitchAccount(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, target_email: str):
        super().__init__()
        self.target_email = target_email

    def run(self):
        try:
            cmd = [sys.executable, str(DAEMON_SCRIPT), "--switch-to", self.target_email]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=80,
                cwd=str(BASE_DIR)
            )
            if res.returncode == 0:
                self.finished.emit(True, f"Sesión activa: {self.target_email}")
            else:
                err = res.stderr or res.stdout or "Error desconocido"
                self.finished.emit(False, f"Fallo: {err[-120:]}")
        except Exception as e:
            self.finished.emit(False, f"Error: {str(e)}")

class WorkerRefreshQuota(QThread):
    finished = pyqtSignal(bool, str)

    def run(self):
        try:
            cmd = [sys.executable, str(DAEMON_SCRIPT), "--status"]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=25,
                cwd=str(BASE_DIR)
            )
            self.finished.emit(res.returncode == 0, "Tokens sincronizados en vivo")
        except Exception as e:
            self.finished.emit(False, f"Error al actualizar: {e}")

class AddAccountDialog(QDialog):
    """Clean minimalist dialog to add a Google account."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✦ Agregar Cuenta")
        self.setFixedWidth(330)
        self.setStyleSheet("""
            QDialog {
                background-color: #141414;
                border: 1px solid #282828;
                border-radius: 10px;
            }
            QLabel {
                color: #e5e7eb;
            }
            QLineEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #2a2a2a;
                border-radius: 5px;
                padding: 6px 8px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
            QPushButton {
                background-color: #202020;
                color: #e5e7eb;
                border: 1px solid #2c2c2c;
                border-radius: 5px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #282828;
                color: #ffffff;
                border-color: #3b82f6;
            }
            QCheckBox {
                color: #c084fc;
                font-weight: bold;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("✦ Agregar Cuenta de Google AI")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title.setStyleSheet("color: #f3f4f6; padding-bottom: 2px;")
        layout.addWidget(title)

        lbl_e = QLabel("Correo Electrónico de Google:")
        lbl_e.setFont(QFont("Segoe UI", 8))
        layout.addWidget(lbl_e)
        self.edit_email = QLineEdit()
        self.edit_email.setPlaceholderText("ejemplo@gmail.com")
        layout.addWidget(self.edit_email)

        lbl_n = QLabel("Nombre para Mostrar:")
        lbl_n.setFont(QFont("Segoe UI", 8))
        layout.addWidget(lbl_n)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Nombre de cuenta")
        layout.addWidget(self.edit_name)

        self.chk_pro = QCheckBox("✦ Cuenta Pro / Ultra")
        self.chk_pro.setChecked(True)
        layout.addWidget(self.chk_pro)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("Guardar Cuenta")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: 1px solid #3b82f6;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.btn_save.clicked.connect(self.on_save)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def on_save(self):
        email = self.edit_email.text().strip().lower()
        if not email or "@" not in email:
            self.edit_email.setFocus()
            return
        name = self.edit_name.text().strip() or email.split("@")[0].capitalize()
        tier = "✦ Pro" if self.chk_pro.isChecked() else "Standard"
        try:
            add_account(email, name=name, tier=tier)
            self.accept()
        except Exception:
            self.reject()

DAYS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

def format_eta_day_spanish(eta_iso: Optional[str], raw_text: Optional[str] = None) -> str:
    """
    Formats quota ETA into an explicit, human-friendly Spanish reset day string.
    Examples: 'Hoy 22:30 (en 2h 15m)', 'Mañana 04:15 (en 7h 40m)', 'Jueves 18:00 (en 4d 6h)'.
    """
    now = datetime.now()
    target_dt = None
    if eta_iso:
        try:
            target_dt = datetime.fromisoformat(eta_iso)
        except Exception:
            pass

    if not target_dt and raw_text:
        try:
            from token_memory import parse_refresh_delta
            d = parse_refresh_delta(raw_text)
            if d:
                target_dt = now + d
        except Exception:
            pass

    if not target_dt:
        return raw_text or "--"

    if now >= target_dt:
        return "¡Recargado al 100%!"

    diff = target_dt - now
    total_sec = max(0, int(diff.total_seconds()))
    day_name = DAYS_ES[target_dt.weekday()]
    time_str = target_dt.strftime("%H:%M")

    if total_sec < 86400:
        rem_str = f"en {total_sec // 3600}h {(total_sec % 3600) // 60}m"
    else:
        rem_str = f"en {total_sec // 86400}d {(total_sec % 86400) // 3600}h"

    if target_dt.date() == now.date():
        return f"Hoy {time_str} ({rem_str})"
    elif target_dt.date() == (now + timedelta(days=1)).date():
        return f"Mañana {time_str} ({rem_str})"
    elif diff.days < 7:
        return f"{day_name} {time_str} ({rem_str})"
    else:
        return f"{day_name} {target_dt.strftime('%d/%m')} {time_str} ({rem_str})"


class MinimalistAccountCard(QFrame):
    """Ultra-clean, compact account card with authentic Antigravity dark design and reset day countdown."""
    request_switch = pyqtSignal(str)

    def __init__(self, account_info: dict, parent=None):
        super().__init__(parent)
        self.account_info = account_info
        self.email = account_info["email"]
        self.init_ui()

    def init_ui(self):
        self.setObjectName("MinimalCard")
        self.setStyleSheet("""
            QFrame#MinimalCard {
                background-color: #161616;
                border: 1px solid #242424;
                border-radius: 8px;
            }
            QFrame#MinimalCard:hover {
                background-color: #1c1c1c;
                border: 1px solid #333333;
            }
            QFrame#MinimalCard[active="true"] {
                background-color: #141822;
                border: 1px solid #3b82f6;
            }
            QFrame#MinimalCard[exhausted="true"] {
                background-color: #121212;
                border: 1px solid #221c1c;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header Row: Email + Pin + Chips
        h_row = QHBoxLayout()
        h_row.setSpacing(5)

        self.lbl_email = QLabel(self.email)
        self.lbl_email.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lbl_email.setStyleSheet("color: #f3f4f6;")

        self.btn_pin = QPushButton("⚑")
        self.btn_pin.setFixedSize(22, 20)
        self.btn_pin.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_pin.setToolTip("Fijar esta cuenta (Evita que el sistema rote automáticamente)")
        self.btn_pin.setStyleSheet("background: transparent; color: #555555; border: none; font-size: 11px;")
        self.btn_pin.clicked.connect(self.on_toggle_pin)

        self.lbl_tier = QLabel(self.account_info.get("tier", "✦ Pro"))
        self.lbl_tier.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        self.lbl_tier.setStyleSheet("""
            background-color: rgba(168, 85, 247, 0.12);
            color: #c084fc;
            border: 1px solid rgba(168, 85, 247, 0.25);
            border-radius: 4px;
            padding: 1px 5px;
        """)

        self.lbl_badge = QLabel("EN ESPERA")
        self.lbl_badge.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        self.lbl_badge.setStyleSheet("""
            background-color: #202020;
            color: #71717a;
            border-radius: 4px;
            padding: 1px 5px;
        """)

        # Hardware-accelerated opacity for breathing active glow (zero style sheet parsing)
        self.badge_opacity = QGraphicsOpacityEffect(self.lbl_badge)
        self.lbl_badge.setGraphicsEffect(self.badge_opacity)

        h_row.addWidget(self.lbl_email, 1)
        h_row.addWidget(self.btn_pin)
        h_row.addWidget(self.lbl_tier)
        h_row.addWidget(self.lbl_badge)
        layout.addLayout(h_row)

        # High-visibility Reset Day Banner (Tells the user EXACTLY what day it resets)
        self.lbl_reset_banner = QLabel()
        self.lbl_reset_banner.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        self.lbl_reset_banner.setStyleSheet("""
            background-color: rgba(59, 130, 246, 0.08);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.2);
            border-radius: 4px;
            padding: 2px 6px;
        """)
        self.lbl_reset_banner.setVisible(False)
        layout.addWidget(self.lbl_reset_banner)

        # Metric 1: Gemini 5h
        m1_layout = QHBoxLayout()
        m1_layout.setContentsMargins(0, 2, 0, 0)
        lbl_5h_name = QLabel("Gemini 5h:")
        lbl_5h_name.setFont(QFont("Segoe UI", 8))
        lbl_5h_name.setStyleSheet("color: #888888;")

        self.lbl_5h_val = QLabel("100%")
        self.lbl_5h_val.setFont(QFont("Segoe UI", 8))
        self.lbl_5h_val.setStyleSheet("color: #e5e7eb;")
        self.lbl_5h_val.setAlignment(Qt.AlignmentFlag.AlignRight)

        m1_layout.addWidget(lbl_5h_name)
        m1_layout.addWidget(self.lbl_5h_val)
        layout.addLayout(m1_layout)

        self.bar_5h = QProgressBar()
        self.bar_5h.setFixedHeight(4)
        self.bar_5h.setTextVisible(False)
        layout.addWidget(self.bar_5h)

        # Metric 2: Gemini Semanal
        m2_layout = QHBoxLayout()
        m2_layout.setContentsMargins(0, 2, 0, 0)
        lbl_wk_name = QLabel("Semanal:")
        lbl_wk_name.setFont(QFont("Segoe UI", 8))
        lbl_wk_name.setStyleSheet("color: #888888;")

        self.lbl_wk_val = QLabel("--")
        self.lbl_wk_val.setFont(QFont("Segoe UI", 8))
        self.lbl_wk_val.setStyleSheet("color: #e5e7eb;")
        self.lbl_wk_val.setAlignment(Qt.AlignmentFlag.AlignRight)

        m2_layout.addWidget(lbl_wk_name)
        m2_layout.addWidget(self.lbl_wk_val)
        layout.addLayout(m2_layout)

        self.bar_wk = QProgressBar()
        self.bar_wk.setFixedHeight(4)
        self.bar_wk.setTextVisible(False)
        layout.addWidget(self.bar_wk)

        # Metric 3: Claude / GPT info
        self.lbl_claude = QLabel("Claude/GPT: 5h: -- | Semanal: --")
        self.lbl_claude.setFont(QFont("Segoe UI", 7))
        self.lbl_claude.setStyleSheet("color: #a78bfa; padding-top: 2px;")
        layout.addWidget(self.lbl_claude)

        # Model details accordion toggle button
        self.btn_details = QPushButton("▸ Modelos")
        self.btn_details.setFont(QFont("Segoe UI", 7))
        self.btn_details.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_details.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #60a5fa;
                border: none;
                text-align: left;
                padding: 1px 0px;
            }
            QPushButton:hover {
                color: #93c5fd;
            }
        """)
        self.btn_details.clicked.connect(self.toggle_details)
        layout.addWidget(self.btn_details)

        # Expandable model details sub-frame
        self.details_frame = QFrame()
        self.details_frame.setObjectName("DetailsSubFrame")
        self.details_frame.setStyleSheet("""
            QFrame#DetailsSubFrame {
                background-color: #111111;
                border: 1px solid #222222;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        self.details_layout = QVBoxLayout(self.details_frame)
        self.details_layout.setContentsMargins(6, 4, 6, 4)
        self.details_layout.setSpacing(3)
        self.details_frame.setVisible(False)
        layout.addWidget(self.details_frame)

        # Live model chips row
        self.lbl_chips = QLabel()
        self.lbl_chips.setFont(QFont("Segoe UI", 7))
        self.lbl_chips.setStyleSheet("color: #71717a; padding-bottom: 2px;")
        self.lbl_chips.setVisible(False)
        layout.addWidget(self.lbl_chips)

        # Action Switch Button (Minimalist Ghost Pill)
        self.btn_switch = QPushButton("⇄ Cambiar a esta cuenta")
        self.btn_switch.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.btn_switch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_switch.setFixedHeight(24)
        self.btn_switch.clicked.connect(lambda: self.request_switch.emit(self.email))
        layout.addWidget(self.btn_switch)

    def on_toggle_pin(self):
        pinned = get_pinned_account()
        if pinned and pinned.split("@")[0].lower() in self.email.lower():
            set_pinned_account(None)
            AudioChimeEngine.play_toggle()
        else:
            set_pinned_account(self.email)
            AudioChimeEngine.play_refresh()
        parent_w = self.window()
        if hasattr(parent_w, "refresh_memory_data"):
            parent_w.refresh_memory_data()

    def toggle_details(self):
        is_vis = not self.details_frame.isVisible()
        self.details_frame.setVisible(is_vis)
        self.btn_details.setText("▾ Ocultar modelos" if is_vis else "▸ Modelos")
        AudioChimeEngine.play_toggle()

    def _set_bar_color(self, bar: QProgressBar, pct: int):
        if pct > 50:
            color = "#3b82f6"  # Signature Google Antigravity Blue
        elif pct >= 20:
            color = "#f59e0b"  # Amber
        else:
            color = "#ef4444"  # Red

        bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #202020;
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 2px;
            }}
        """)

    def _animate_bar(self, bar: QProgressBar, target_val: int):
        """Animates progress bar smoothly with easing curve."""
        target_val = max(0, min(100, int(target_val)))
        if not hasattr(bar, "_anim"):
            anim = QVariantAnimation(self)
            anim.setDuration(240)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(lambda v: bar.setValue(int(v)))
            bar._anim = anim
        bar._anim.stop()
        bar._anim.setStartValue(bar.value())
        bar._anim.setEndValue(target_val)
        bar._anim.start()

    def set_pulse_alpha(self, alpha: float):
        """Hardware-accelerated breathing opacity with zero CSS re-parsing overhead."""
        if self.property("active") and hasattr(self, "badge_opacity"):
            self.badge_opacity.setOpacity(0.65 + 0.35 * alpha)

    def update_data(self, status_data: dict, is_active: bool):
        gem = status_data.get("gemini", {})
        p_5h = gem.get("five_hour_remaining_pct")
        p_wk = gem.get("weekly_remaining_pct")
        is_exhausted = status_data.get("is_exhausted", False) or (p_5h is not None and p_5h <= 0) or (p_wk is not None and p_wk <= 0)
        is_recharged = (p_5h is not None and p_5h >= 100 and "Recargado" in str(gem.get("five_hour_refresh_text", "")))

        # Update Pin Button State
        pinned = get_pinned_account()
        is_pinned = bool(pinned and pinned.split("@")[0].lower() in self.email.lower())
        if is_pinned:
            self.btn_pin.setStyleSheet("background-color: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; border-radius: 3px; font-size: 11px;")
            self.btn_pin.setToolTip("Cuenta FIJADA ⚑ (Clic para desfijar)")
        else:
            self.btn_pin.setStyleSheet("background-color: transparent; color: #555555; border: none; font-size: 11px;")
            self.btn_pin.setToolTip("Fijar esta cuenta (Evita auto-rotación)")

        self.setProperty("active", is_active)
        self.setProperty("exhausted", is_exhausted and not is_active)
        self.style().unpolish(self)
        self.style().polish(self)

        # Calculate exact Reset Day strings for 5h and Weekly
        reset_5h_str = format_eta_day_spanish(gem.get("five_hour_refresh_eta"), gem.get("five_hour_refresh_text"))
        reset_wk_str = format_eta_day_spanish(gem.get("weekly_refresh_eta"), gem.get("weekly_refresh_text"))

        if is_active:
            self.lbl_email.setStyleSheet("color: #60a5fa;")
            badge_txt = "● ACTIVA" if not is_pinned else "⚑ ACTIVA"
            self.lbl_badge.setText(badge_txt)
            self.lbl_badge.setStyleSheet("""
                background-color: rgba(34, 197, 94, 0.12);
                color: #22c55e;
                border: 1px solid rgba(34, 197, 94, 0.28);
                border-radius: 4px;
                padding: 1px 5px;
            """)
            self.btn_switch.setText("✓ Sesión Activa")
            self.btn_switch.setEnabled(False)
            self.btn_switch.setStyleSheet("""
                QPushButton {
                    background-color: rgba(59, 130, 246, 0.08);
                    color: #93c5fd;
                    border: 1px solid rgba(59, 130, 246, 0.22);
                    border-radius: 5px;
                }
            """)
        elif is_exhausted:
            self.lbl_email.setStyleSheet("color: #71717a;")
            self.lbl_badge.setText("✕ AGOTADA")
            self.lbl_badge.setStyleSheet("""
                background-color: rgba(239, 68, 68, 0.12);
                color: #f87171;
                border: 1px solid rgba(239, 68, 68, 0.28);
                border-radius: 4px;
                padding: 1px 5px;
            """)
            self.btn_switch.setText("⇄ Cambiar (Agotada)")
            self.btn_switch.setEnabled(True)
            self.btn_switch.setStyleSheet("""
                QPushButton {
                    background-color: #161616;
                    color: #71717a;
                    border: 1px solid #222222;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #202020;
                    color: #e5e7eb;
                    border-color: #333333;
                }
            """)
        elif is_recharged:
            self.lbl_email.setStyleSheet("color: #f3f4f6;")
            self.lbl_badge.setText("✦ RECARGADA")
            self.lbl_badge.setStyleSheet("""
                background-color: rgba(59, 130, 246, 0.12);
                color: #60a5fa;
                border: 1px solid rgba(59, 130, 246, 0.28);
                border-radius: 4px;
                padding: 1px 5px;
            """)
            self.btn_switch.setText("⇄ Cambiar a esta cuenta")
            self.btn_switch.setEnabled(True)
            self.btn_switch.setStyleSheet("""
                QPushButton {
                    background-color: #1e1e1e;
                    color: #e5e7eb;
                    border: 1px solid #2a2a2a;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #262626;
                    color: #ffffff;
                    border-color: #3b82f6;
                }
            """)
        else:
            self.lbl_email.setStyleSheet("color: #f3f4f6;")
            badge_txt = "DISPONIBLE" if not is_pinned else "⚑ FIJADA"
            self.lbl_badge.setText(badge_txt)
            self.lbl_badge.setStyleSheet("""
                background-color: #1e1e1e;
                color: #71717a;
                border: 1px solid #27272a;
                border-radius: 4px;
                padding: 1px 5px;
            """)
            self.btn_switch.setText("⇄ Cambiar a esta cuenta")
            self.btn_switch.setEnabled(True)
            self.btn_switch.setStyleSheet("""
                QPushButton {
                    background-color: #1e1e1e;
                    color: #a1a1aa;
                    border: 1px solid #27272a;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #262626;
                    color: #ffffff;
                    border-color: #3b82f6;
                }
                QPushButton:pressed {
                    background-color: #1a1a1a;
                }
            """)

        # High-visibility Reset Day Banner
        if is_exhausted:
            primary_reset = reset_5h_str if (p_5h is not None and p_5h <= 0) else reset_wk_str
            self.lbl_reset_banner.setText(f"✦ Restablece: {primary_reset}")
            self.lbl_reset_banner.setStyleSheet("""
                background-color: rgba(239, 68, 68, 0.10);
                color: #fca5a5;
                border: 1px solid rgba(239, 68, 68, 0.25);
                border-radius: 4px;
                padding: 2px 6px;
                font-weight: bold;
            """)
            self.lbl_reset_banner.setVisible(True)
        elif p_5h is not None and p_5h <= 30:
            self.lbl_reset_banner.setText(f"✦ Restablece: {reset_5h_str}")
            self.lbl_reset_banner.setStyleSheet("""
                background-color: rgba(245, 158, 11, 0.10);
                color: #fcd34d;
                border: 1px solid rgba(245, 158, 11, 0.25);
                border-radius: 4px;
                padding: 2px 6px;
                font-weight: bold;
            """)
            self.lbl_reset_banner.setVisible(True)
        elif reset_wk_str and reset_wk_str != "--":
            self.lbl_reset_banner.setText(f"✦ Restablece: {reset_wk_str}")
            self.lbl_reset_banner.setStyleSheet("""
                background-color: rgba(59, 130, 246, 0.08);
                color: #93c5fd;
                border: 1px solid rgba(59, 130, 246, 0.2);
                border-radius: 4px;
                padding: 2px 6px;
            """)
            self.lbl_reset_banner.setVisible(True)
        else:
            self.lbl_reset_banner.setVisible(False)

        # Gemini 5h
        if p_5h is not None:
            val = int(p_5h)
            self._animate_bar(self.bar_5h, val)
            self._set_bar_color(self.bar_5h, val)
            self.lbl_5h_val.setText(f"{val}% • {reset_5h_str}")
        else:
            self._animate_bar(self.bar_5h, 100)
            self._set_bar_color(self.bar_5h, 100)
            self.lbl_5h_val.setText("100% • Lista")

        # Gemini Semanal
        if p_wk is not None:
            val_w = int(p_wk)
            self._animate_bar(self.bar_wk, val_w)
            self._set_bar_color(self.bar_wk, val_w)
            self.lbl_wk_val.setText(f"{val_w}% • {reset_wk_str}")
        else:
            self._animate_bar(self.bar_wk, 100)
            self._set_bar_color(self.bar_wk, 100)
            self.lbl_wk_val.setText("--")

        # Claude / GPT
        cgpt = status_data.get("claude_gpt", {})
        c_5h = cgpt.get("five_hour_remaining_pct")
        c_wk = cgpt.get("weekly_remaining_pct")
        c_reset = format_eta_day_spanish(cgpt.get("weekly_refresh_eta"), cgpt.get("weekly_refresh_text"))
        c_5h_s = f"{c_5h}%" if c_5h is not None else "--"
        c_wk_s = f"{c_wk}%" if c_wk is not None else "--"
        self.lbl_claude.setText(f"Claude/GPT: 5h: {c_5h_s} • Semanal: {c_wk_s} • Restablece: {c_reset}")

        # Re-populate details accordion
        models = status_data.get("models", {})
        while self.details_layout.count() > 0:
            item = self.details_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count() > 0:
                    sub = item.layout().takeAt(0)
                    if sub.widget(): sub.widget().deleteLater()

        detail_items = []
        if isinstance(models, dict) and models:
            for m_key, m_val in models.items():
                if isinstance(m_val, dict) and m_val.get("remaining_fraction") is not None:
                    pct = int(round(m_val["remaining_fraction"] * 100))
                    lbl = m_val.get("label", m_key)
                    short = lbl.replace("Gemini ", "g-").replace("Claude ", "c-").replace(" (Thinking)", " Think")
                    detail_items.append((short, pct))

        if not detail_items:
            detail_items = [
                ("Gemini Flash / Pro (5h)", p_5h if p_5h is not None else 100),
                ("Gemini Semanal", p_wk if p_wk is not None else 100),
                ("Claude / GPT (Semanal)", c_wk if c_wk is not None else 100)
            ]

        for name, pct in detail_items[:5]:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            nl = QLabel(name)
            nl.setFont(QFont("Segoe UI", 7))
            nl.setStyleSheet("color: #888888;")
            vl = QLabel(f"{pct}%")
            vl.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            vl.setStyleSheet("color: #e5e7eb;")
            row.addWidget(nl)
            row.addStretch()
            row.addWidget(vl)
            self.details_layout.addLayout(row)

            mb = QProgressBar()
            mb.setFixedHeight(3)
            mb.setTextVisible(False)
            mb.setValue(pct)
            self._set_bar_color(mb, pct)
            self.details_layout.addWidget(mb)

        # Live model chips
        chips = [f"{n}:{p}%" for n, p in detail_items[:3]]
        if chips:
            self.lbl_chips.setText(" • ".join(chips))
            self.lbl_chips.setVisible(True)
        else:
            self.lbl_chips.setVisible(False)


class MinimalistPillHandle(QFrame):
    """Ultra-slim (28px x 110px) minimalist tab pinned to Antigravity window."""
    clicked = pyqtSignal()
    right_clicked = pyqtSignal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(28)
        self.setFixedHeight(110)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("✦ Antigravity Tokens (Clic izquierdo: abrir/cerrar • Clic derecho: opciones)")
        self.is_expanded = False
        self.is_hovered = False
        self.pulse_val = 0.0

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def set_expanded(self, expanded: bool):
        self.is_expanded = expanded
        self.update()

    def set_pulse(self, val: float):
        self.pulse_val = val
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        bg_color = QColor("#1c1c1c") if self.is_hovered else QColor("#141414")
        border_color = QColor("#3b82f6") if self.is_hovered else QColor("#282828")

        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, 1))

        # Rounded outer edge
        path = QPainterPath()
        r = 8.0
        path.moveTo(0, 0)
        path.lineTo(w - r, 0)
        path.arcTo(w - 2 * r, 0, 2 * r, 2 * r, 90, -90)
        path.lineTo(w, h - r)
        path.arcTo(w - 2 * r, h - 2 * r, 2 * r, 2 * r, 0, -90)
        path.lineTo(0, h)
        path.closeSubpath()
        painter.drawPath(path)

        # Gemini Star Icon ✦ (with subtle breathing glow)
        glow_b = int(180 + 75 * self.pulse_val)
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.setPen(QColor(59, 130, glow_b) if not self.is_hovered else QColor("#60a5fa"))
        painter.drawText(QRect(0, 8, w, 20), Qt.AlignmentFlag.AlignCenter, "✦")

        # Vertical Divider Micro Line
        painter.setPen(QPen(QColor(59, 130, 246, 140 if self.is_hovered else 60), 1.5))
        painter.drawLine(w // 2, 36, w // 2, h - 32)

        # Chevron Arrow › / ‹
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.setPen(QColor("#ffffff" if self.is_hovered else "#888888"))
        arrow = "‹" if self.is_expanded else "›"
        painter.drawText(QRect(0, h - 26, w, 18), Qt.AlignmentFlag.AlignCenter, arrow)


def make_tray_icon(is_active: bool = True) -> QIcon:
    """Creates a high-DPI procedural Antigravity tray icon with status indicator."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg_color = QColor("#3b82f6") if is_active else QColor("#383838")
    p.setBrush(QBrush(bg_color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 28, 28, 7, 7)
    p.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
    p.setPen(QColor("#ffffff"))
    p.drawText(QRect(0, 0, 32, 30), Qt.AlignmentFlag.AlignCenter, "✦")
    p.end()
    return QIcon(pix)


class AntigravityDockedOverlay(QWidget):
    """
    Ultra-responsive native desktop widget docked to Antigravity.
    Smooth 60 FPS slide-in / slide-out animations and zero-lag Win32 tracking.
    """
    def __init__(self):
        super().__init__()
        self.is_expanded = False
        self.PANEL_TARGET_WIDTH = 410
        self.current_panel_w = 0
        self.antigravity_hwnd: Optional[int] = None
        self.last_rect = None
        self.switching = False
        self.last_memory_mtime = 0
        self.win_event_hook = None
        self._hook_cb_ref = None
        self.sync_spin_step = 0
        self.last_toggle_time = 0.0
        self.is_dialog_active = False

        self.init_window_flags()
        self.init_ui()
        self.init_animations()
        self.init_tracking_engine()
        self.init_tray()
        self.init_hotkey()
        self.refresh_memory_data()

    def init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Antigravity Token Dock")

    def contextMenuEvent(self, event):
        """Right-click anywhere on the overlay displays the quick actions context menu."""
        self.show_dock_context_menu(event.globalPos())

    def show_dock_context_menu(self, pos: QPoint):
        """Displays right-click context menu with options to close menu, rotate, auto-switch, etc."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #141414;
                color: #f3f4f6;
                border: 1px solid #282828;
                border-radius: 8px;
                padding: 4px;
                font-family: 'Segoe UI';
                font-size: 11px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1f1f1f;
                color: #3b82f6;
            }
            QMenu::separator {
                height: 1px;
                background-color: #242424;
                margin: 4px 8px;
            }
        """)

        if self.is_expanded:
            act_close = menu.addAction("✕ Cerrar menú (Ocultar panel)")
            act_close.triggered.connect(self.toggle_expanded)
        else:
            act_open = menu.addAction("✦ Abrir menú de tokens")
            act_open.triggered.connect(self.toggle_expanded)

        menu.addSeparator()

        act_rotate = menu.addAction("⇄ Rotar a la siguiente cuenta")
        act_rotate.triggered.connect(self.on_tray_rotate_requested)

        act_refresh = menu.addAction("↻ Actualizar tokens en vivo")
        act_refresh.triggered.connect(self.on_manual_refresh)

        menu.addSeparator()

        act_auto = menu.addAction("✦ Auto-rotación activa")
        act_auto.setCheckable(True)
        act_auto.setChecked(is_auto_switch_enabled())
        act_auto.triggered.connect(self.toggle_auto_switch)

        act_sound = menu.addAction("♪ Efectos de sonido")
        act_sound.setCheckable(True)
        act_sound.setChecked(is_sound_enabled())
        act_sound.triggered.connect(self.toggle_sound)

        act_startup = menu.addAction("✦ Iniciar con Windows")
        act_startup.setCheckable(True)
        act_startup.setChecked(is_windows_startup_enabled())
        act_startup.triggered.connect(self.toggle_startup)

        menu.addSeparator()

        act_hud = menu.addAction("✦ Abrir Web HUD")
        act_hud.triggered.connect(self.open_hud_browser)

        act_backup = menu.addAction("✦ Exportar copia de respaldo")
        act_backup.triggered.connect(self.on_backup_dialog)

        menu.addSeparator()

        act_exit = menu.addAction("✕ Cerrar y salir de la app")
        act_exit.triggered.connect(self.on_exit_app)

        self.is_dialog_active = True
        try:
            menu.exec(pos)
        finally:
            self.is_dialog_active = False
            self.last_toggle_time = time.time()

    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 1. Minimalist Pill Handle
        self.pill_handle = MinimalistPillHandle(self)
        self.pill_handle.clicked.connect(self.toggle_expanded)
        self.pill_handle.right_clicked.connect(self.show_dock_context_menu)

        # 2. Minimalist Expanded Container (360px target)
        self.panel_container = QFrame()
        self.panel_container.setObjectName("PanelContainer")
        self.panel_container.setFixedWidth(0)
        self.panel_container.setStyleSheet("""
            QFrame#PanelContainer {
                background-color: #101010;
                border: 1px solid #242424;
                border-radius: 10px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 4)
        self.panel_container.setGraphicsEffect(shadow)

        panel_layout = QVBoxLayout(self.panel_container)
        panel_layout.setContentsMargins(12, 10, 12, 10)
        panel_layout.setSpacing(5)

        # Antigravity Signature Gradient Line
        grad_line = QFrame()
        grad_line.setFixedHeight(2)
        grad_line.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 #3b82f6, stop:0.35 #6366f1, stop:0.7 #a855f7, stop:1 #ec4899);
            border-radius: 1px;
            border: none;
        """)
        panel_layout.addWidget(grad_line)

        # Top Bar (Header)
        top_bar = QHBoxLayout()
        top_bar.setSpacing(4)

        icon_star = QLabel("✦")
        icon_star.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        icon_star.setStyleSheet("color: #4a88ff; cursor: pointer;")
        icon_star.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon_star.setToolTip("Clic izquierdo para ocultar • Clic derecho para opciones")
        icon_star.mousePressEvent = lambda e: self.show_dock_context_menu(e.globalPosition().toPoint()) if e.button() == Qt.MouseButton.RightButton else self.toggle_expanded()

        title_lbl = QLabel("Tokens")
        title_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #f3f4f6; cursor: pointer;")
        title_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        title_lbl.setToolTip("Clic izquierdo para ocultar • Clic derecho para opciones")
        title_lbl.mousePressEvent = lambda e: self.show_dock_context_menu(e.globalPosition().toPoint()) if e.button() == Qt.MouseButton.RightButton else self.toggle_expanded()

        # Auto-switch toggle button
        self.btn_auto = QPushButton()
        self.btn_auto.setFixedHeight(22)
        self.btn_auto.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_auto.clicked.connect(self.toggle_auto_switch)
        self.update_auto_button_ui()

        # Sound toggle button
        self.btn_sound = QPushButton()
        self.btn_sound.setFixedSize(22, 22)
        self.btn_sound.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_sound.clicked.connect(self.toggle_sound)
        self.update_sound_button_ui()

        # Search toggle button
        self.btn_search = QPushButton("⌕")
        self.btn_search.setFixedSize(22, 22)
        self.btn_search.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_search.setToolTip("Filtrar cuentas")
        self.btn_search.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: none;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #1c1c1c;
                color: #3b82f6;
            }
        """)
        self.btn_search.clicked.connect(self.toggle_search)

        self.btn_add = QPushButton("+")
        self.btn_add.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.btn_add.setFixedSize(22, 22)
        self.btn_add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_add.setToolTip("Agregar nueva cuenta de Google")
        self.btn_add.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #3b82f6;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1c1c1c;
                color: #60a5fa;
            }
        """)
        self.btn_add.clicked.connect(self.on_add_account_dialog)

        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFont(QFont("Segoe UI", 11))
        self.btn_refresh.setFixedSize(22, 22)
        self.btn_refresh.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_refresh.setToolTip("Actualizar tokens en vivo vía CDP")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1c1c1c;
                color: #3b82f6;
            }
        """)
        self.btn_refresh.clicked.connect(self.on_manual_refresh)

        btn_close = QPushButton("✕")
        btn_close.setFont(QFont("Segoe UI", 9))
        btn_close.setFixedSize(22, 22)
        btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close.setToolTip("Cerrar menú (Ocultar panel)")
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1c1c1c;
                color: #f3f4f6;
            }
        """)
        btn_close.clicked.connect(self.toggle_expanded)

        top_bar.addWidget(icon_star)
        top_bar.addWidget(title_lbl)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_auto)
        top_bar.addWidget(self.btn_sound)
        top_bar.addWidget(self.btn_search)
        top_bar.addWidget(self.btn_add)
        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(btn_close)
        panel_layout.addLayout(top_bar)

        # Micro Search Bar
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("⌕ Filtrar cuentas...")
        self.search_bar.setFixedHeight(24)
        self.search_bar.setStyleSheet("""
            QLineEdit {
                background-color: #161616;
                color: #f3f4f6;
                border: 1px solid #262626;
                border-radius: 5px;
                padding: 2px 8px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
        """)
        self.search_bar.textChanged.connect(self.on_search_text_changed)
        self.search_bar.setVisible(False)
        panel_layout.addWidget(self.search_bar)

        # Micro Status Line
        self.status_line = QLabel("● Monitoreo continuo activo")
        self.status_line.setFont(QFont("Segoe UI", 7))
        self.status_line.setStyleSheet("color: #71717a; padding-bottom: 2px;")
        panel_layout.addWidget(self.status_line)

        # Scrollable Cards Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 4px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: #242424;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3b82f6;
            }
        """)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 2, 0)
        self.cards_layout.setSpacing(6)

        # Load accounts dynamically via config_manager
        configured_accounts = get_authorized_accounts()
        self.account_cards: Dict[str, MinimalistAccountCard] = {}
        for acc in configured_accounts:
            card = MinimalistAccountCard(acc, self.cards_container)
            card.request_switch.connect(self.on_switch_account_requested)
            self.account_cards[acc["email"]] = card
            self.cards_layout.addWidget(card)

        self.scroll_area.setWidget(self.cards_container)
        panel_layout.addWidget(self.scroll_area, 1)

        # Minimal Footer with quick tools
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(6)

        self.footer_lbl = QLabel("✦ Auto-rotación activa • Sondeo 20s")
        self.footer_lbl.setFont(QFont("Segoe UI", 7))
        self.footer_lbl.setStyleSheet("color: #52525b;")

        btn_hud = QPushButton("✦ HUD")
        btn_hud.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        btn_hud.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_hud.setToolTip("Abrir HUD Web Dashboard en navegador (http://127.0.0.1:59123)")
        btn_hud.setStyleSheet("background: transparent; color: #3b82f6; border: none; padding: 0 4px;")
        btn_hud.clicked.connect(self.open_hud_browser)

        btn_backup = QPushButton("✦ Backup")
        btn_backup.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        btn_backup.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_backup.setToolTip("Exportar copia de seguridad de cuentas a Escritorio")
        btn_backup.setStyleSheet("background: transparent; color: #818cf8; border: none; padding: 0 4px;")
        btn_backup.clicked.connect(self.on_backup_dialog)

        footer_layout.addWidget(self.footer_lbl, 1)
        footer_layout.addWidget(btn_hud)
        footer_layout.addWidget(btn_backup)
        panel_layout.addLayout(footer_layout)

        # Add to main layout (pin pill_handle to top so it never drifts vertically)
        self.main_layout.addWidget(self.pill_handle, 0, Qt.AlignmentFlag.AlignTop)
        self.main_layout.addWidget(self.panel_container, 1)
        self.panel_container.setVisible(False)

        self.set_collapsed_geometry()

    def init_animations(self):
        """Initializes 60 FPS hardware-accelerated slide animation with easing curve and opacity fade."""
        # 1. Slide Animation for Expand / Collapse
        self.slide_anim = QVariantAnimation(self)
        self.slide_anim.setDuration(240)
        self.slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.slide_anim.valueChanged.connect(self.on_slide_value)
        self.slide_anim.finished.connect(self.on_slide_finished)

        # Smooth Opacity Transition for Panel Content
        self.panel_opacity = QGraphicsOpacityEffect(self.panel_container)
        self.panel_container.setGraphicsEffect(self.panel_opacity)
        self.panel_opacity.setOpacity(0.0)

        # 2. Breathing / Pulse Heartbeat Timer (80ms interval)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(80)
        self.pulse_timer.timeout.connect(self.on_pulse_tick)
        self.pulse_timer.start()

        # 3. Rotating Sync Icon Timer
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(120)
        self.sync_timer.timeout.connect(self.on_sync_spin)

    def on_pulse_tick(self):
        # Never waste frame cycles during slide animation
        if self.slide_anim.state() == QAbstractAnimation.State.Running:
            return
        val = 0.5 + 0.5 * math.sin(time.time() * 3.2)
        self.pill_handle.set_pulse(val)
        if self.is_expanded:
            for card in self.account_cards.values():
                card.set_pulse_alpha(val)

    def on_sync_spin(self):
        spinner_chars = ["◐", "◓", "◑", "◒"]
        self.sync_spin_step = (self.sync_spin_step + 1) % len(spinner_chars)
        self.btn_refresh.setText(spinner_chars[self.sync_spin_step])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.is_expanded:
                self.toggle_expanded()
                event.accept()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.is_expanded:
                self.toggle_expanded()
                event.accept()
                return
            elif event.pos().x() <= 28:
                self.toggle_expanded()
                event.accept()
                return
        super().mousePressEvent(event)

    def init_tracking_engine(self):
        """Zero-lag Win32 tracking with SetWinEventHook + adaptive timer."""
        self.antigravity_hwnd = find_antigravity_hwnd()

        if self.antigravity_hwnd:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(self.antigravity_hwnd, ctypes.byref(pid))
            if pid.value:
                def win_event_cb(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
                    if hwnd == self.antigravity_hwnd and idObject == 0:
                        self.update_dock_position()

                WINEVENTPROC = ctypes.WINFUNCTYPE(
                    None,
                    wintypes.HANDLE,
                    wintypes.DWORD,
                    wintypes.HWND,
                    wintypes.LONG,
                    wintypes.LONG,
                    wintypes.DWORD,
                    wintypes.DWORD
                )
                self._hook_cb_ref = WINEVENTPROC(win_event_cb)
                self.win_event_hook = user32.SetWinEventHook(
                    EVENT_OBJECT_LOCATIONCHANGE,
                    EVENT_OBJECT_LOCATIONCHANGE,
                    0,
                    self._hook_cb_ref,
                    pid.value,
                    0,
                    WINEVENT_OUTOFCONTEXT
                )

        # High-speed heartbeat timer (25ms)
        self.dock_timer = QTimer(self)
        self.dock_timer.setInterval(25)
        self.dock_timer.timeout.connect(self.update_dock_position)
        self.dock_timer.start()

        # Token memory check timer (2s)
        self.data_timer = QTimer(self)
        self.data_timer.setInterval(2000)
        self.data_timer.timeout.connect(self.check_memory_file)
        self.data_timer.start()

    def set_collapsed_geometry(self):
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setFixedSize(28, 110)

    def prepare_expanded_window_geometry(self):
        """Pre-sizes top-level window to target expanded dimensions ONCE, preventing DWM reallocation hitching."""
        if not self.antigravity_hwnd or not user32.IsWindow(self.antigravity_hwnd):
            return

        ag_rect = wintypes.RECT()
        hr = dwmapi.DwmGetWindowAttribute(self.antigravity_hwnd, 9, ctypes.byref(ag_rect), ctypes.sizeof(ag_rect))
        if hr != 0:
            user32.GetWindowRect(self.antigravity_hwnd, ctypes.byref(ag_rect))

        ag_h = ag_rect.bottom - ag_rect.top

        hmon = user32.MonitorFromWindow(self.antigravity_hwnd, 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        work_r = mi.rcWork

        is_maximized = bool(user32.IsZoomed(self.antigravity_hwnd))
        widget_w = 28 + self.PANEL_TARGET_WIDTH
        widget_h = min(680, max(460, ag_h - 40))

        space_right = work_r.right - ag_rect.right
        space_left = ag_rect.left - work_r.left

        if is_maximized:
            target_x = ag_rect.right - widget_w - 12
            target_y = ag_rect.top + 38
        elif space_right >= widget_w:
            target_x = ag_rect.right
            target_y = ag_rect.top + 48
        elif space_left >= widget_w:
            target_x = ag_rect.left - widget_w
            target_y = ag_rect.top + 48
        else:
            target_x = ag_rect.right - widget_w - 8
            target_y = ag_rect.top + 42

        if target_y + widget_h > work_r.bottom:
            target_y = max(work_r.top, work_r.bottom - widget_h - 8)

        self.last_rect = (target_x, target_y, widget_w, widget_h)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setFixedSize(widget_w, widget_h)

        user32.SetWindowPos(
            int(self.winId()),
            0,
            target_x, target_y, widget_w, widget_h,
            SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOOWNERZORDER
        )

    def toggle_expanded(self):
        self.last_toggle_time = time.time()
        self.is_expanded = not self.is_expanded
        self.pill_handle.set_expanded(self.is_expanded)

        self.slide_anim.stop()
        if self.is_expanded:
            self.prepare_expanded_window_geometry()
            self.panel_container.setVisible(True)
            self.slide_anim.setDuration(240)
            self.slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.slide_anim.setStartValue(self.current_panel_w)
            self.slide_anim.setEndValue(self.PANEL_TARGET_WIDTH)
            self.slide_anim.start()
        else:
            self.slide_anim.setDuration(190)
            self.slide_anim.setEasingCurve(QEasingCurve.Type.InQuad)
            self.slide_anim.setStartValue(self.current_panel_w)
            self.slide_anim.setEndValue(0)
            self.slide_anim.start()

    def on_slide_value(self, val):
        self.current_panel_w = int(val)
        self.panel_container.setFixedWidth(self.current_panel_w)
        fade = min(1.0, max(0.0, self.current_panel_w / 240.0))
        self.panel_opacity.setOpacity(fade)

    def on_slide_finished(self):
        if not self.is_expanded:
            self.panel_container.setVisible(False)
            self.current_panel_w = 0
            self.panel_opacity.setOpacity(0.0)
            self.set_collapsed_geometry()
            self.update_dock_position(force=True)
        else:
            self.current_panel_w = self.PANEL_TARGET_WIDTH
            self.panel_opacity.setOpacity(1.0)
            QTimer.singleShot(40, self.refresh_memory_data)

    def update_dock_position(self, force: bool = False):
        """Positions widget cleanly with zero lag and hardware acceleration."""
        if self.slide_anim.state() == QAbstractAnimation.State.Running and not force:
            return

        if not self.antigravity_hwnd or not user32.IsWindow(self.antigravity_hwnd):
            self.antigravity_hwnd = find_antigravity_hwnd()
            if not self.antigravity_hwnd:
                if self.isVisible():
                    self.hide()
                return

        # Hide on minimize
        if not user32.IsWindowVisible(self.antigravity_hwnd) or user32.IsIconic(self.antigravity_hwnd):
            if self.isVisible():
                self.hide()
            return

        if not self.isVisible():
            self.show()

        # Auto-collapse if user clicks outside the dock while expanded
        if self.is_expanded and not force and not self.is_dialog_active:
            if time.time() - self.last_toggle_time > 0.35:
                if (user32.GetAsyncKeyState(0x01) & 0x8000) != 0:
                    if self.last_rect:
                        lx, ly, lw, lh = self.last_rect
                        pt = wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(pt))
                        if not (lx <= pt.x <= lx + lw and ly <= pt.y <= ly + lh):
                            self.toggle_expanded()
                            return

        ag_rect = wintypes.RECT()
        hr = dwmapi.DwmGetWindowAttribute(self.antigravity_hwnd, 9, ctypes.byref(ag_rect), ctypes.sizeof(ag_rect))
        if hr != 0:
            user32.GetWindowRect(self.antigravity_hwnd, ctypes.byref(ag_rect))

        ag_h = ag_rect.bottom - ag_rect.top

        # Monitor work area
        hmon = user32.MonitorFromWindow(self.antigravity_hwnd, 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        work_r = mi.rcWork

        is_maximized = bool(user32.IsZoomed(self.antigravity_hwnd))

        if self.is_expanded:
            widget_w = 28 + self.PANEL_TARGET_WIDTH
            widget_h = min(680, max(460, ag_h - 40))
        else:
            widget_w = 28
            widget_h = 110

        space_right = work_r.right - ag_rect.right
        space_left = ag_rect.left - work_r.left

        if is_maximized:
            target_x = ag_rect.right - widget_w - 12
            target_y = ag_rect.top + 38
        elif space_right >= widget_w:
            target_x = ag_rect.right
            target_y = ag_rect.top + 48
        elif space_left >= widget_w:
            target_x = ag_rect.left - widget_w
            target_y = ag_rect.top + 48
        else:
            target_x = ag_rect.right - widget_w - 8
            target_y = ag_rect.top + 42

        if target_y + widget_h > work_r.bottom:
            target_y = max(work_r.top, work_r.bottom - widget_h - 8)

        current_geometry = (target_x, target_y, widget_w, widget_h)
        if self.last_rect != current_geometry:
            self.last_rect = current_geometry
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.setFixedSize(widget_w, widget_h)

            user32.SetWindowPos(
                int(self.winId()),
                0,
                target_x, target_y, widget_w, widget_h,
                SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOOWNERZORDER
            )

    def check_memory_file(self):
        if not MEMORY_FILE.exists():
            return
        try:
            mtime = os.path.getmtime(MEMORY_FILE)
            if mtime != self.last_memory_mtime:
                self.last_memory_mtime = mtime
                self.refresh_memory_data()
        except Exception:
            pass

    def refresh_memory_data(self):
        if not MEMORY_FILE.exists():
            return
        try:
            from token_memory import get_effective_account_status, load_memory
            mem = load_memory()
            active_acc = mem.get("active_account", "")

            # 1. Update data for all cards
            account_statuses = {}
            for email, card in self.account_cards.items():
                st = get_effective_account_status(email)
                account_statuses[email] = st
                is_active = (email.split("@")[0].lower() in active_acc.lower())
                card.update_data(st, is_active)

            # 2. Dynamic Smart Sorting:
            # - Cuenta en uso actualmente: HASTA ARRIBA (rank 0)
            # - Cuentas con cuota disponible: EN MEDIO (rank 1, mayor cuota primero)
            # - Cuentas con cuota agotada: HASTA ABAJO (rank 2, menor tiempo de recarga primero)
            def sort_rank(email: str):
                is_active = (email.split("@")[0].lower() in active_acc.lower())
                if is_active:
                    return (0, 0)

                st = account_statuses.get(email, {})
                gem = st.get("gemini", {})
                p_5h = gem.get("five_hour_remaining_pct")
                p_wk = gem.get("weekly_remaining_pct")
                is_exhausted = (
                    st.get("is_exhausted", False)
                    or (p_5h is not None and p_5h <= 0)
                    or (p_wk is not None and p_wk <= 0)
                )

                if is_exhausted:
                    rem_sec = gem.get("five_hour_remaining_seconds") or gem.get("weekly_remaining_seconds") or 999999
                    return (2, rem_sec)
                else:
                    p5 = p_5h if p_5h is not None else 100
                    pw = p_wk if p_wk is not None else 100
                    return (1, -(p5 + pw))

            sorted_emails = sorted(self.account_cards.keys(), key=sort_rank)

            # Check if order needs updating
            current_order = []
            for i in range(self.cards_layout.count()):
                w = self.cards_layout.itemAt(i).widget()
                if w and hasattr(w, "email"):
                    current_order.append(w.email)

            if current_order != sorted_emails:
                for email in sorted_emails:
                    card = self.account_cards[email]
                    self.cards_layout.removeWidget(card)
                for email in sorted_emails:
                    card = self.account_cards[email]
                    self.cards_layout.addWidget(card)

            updated_at = mem.get("updated_at", "")
            pinned = get_pinned_account()
            auto_enabled = is_auto_switch_enabled()
            pinned_str = f" • ⚑ {pinned.split('@')[0]}" if pinned else ""
            auto_str = "" if auto_enabled else " • [PAUSA]"
            if updated_at and not self.switching:
                from datetime import datetime
                dt = datetime.fromisoformat(updated_at)
                self.status_line.setText(f"● Sincronizado: {dt.strftime('%H:%M:%S')} • Activa: {active_acc.split('@')[0]}{pinned_str}{auto_str}")
                self.status_line.setStyleSheet("color: #64748b;" if auto_enabled else "color: #fbbf24;")

            if hasattr(self, "tray_icon"):
                self.tray_icon.setToolTip(f"Antigravity Token Dock\nActiva: {active_acc.split('@')[0]}\nAuto: {'Sí' if auto_enabled else 'Pausado'}")
        except Exception as e:
            self.status_line.setText(f"Error memoria: {e}")

    def init_tray(self):
        """Initializes system tray icon with rich context menu."""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(make_tray_icon(is_auto_switch_enabled()))
        self.tray_icon.setToolTip("Antigravity Token Dock")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #14161b;
                color: #f1f5f9;
                border: 1px solid #282c37;
                border-radius: 6px;
                padding: 4px;
                font-family: 'Segoe UI';
                font-size: 11px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #21252b;
                color: #528bff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #282c37;
                margin: 4px 8px;
            }
        """)

        act_toggle = menu.addAction("✦ Mostrar / Ocultar Dock (Ctrl+Alt+T)")
        act_toggle.triggered.connect(self.toggle_expanded)

        act_rotate = menu.addAction("⇄ Rotar a la Siguiente Cuenta")
        act_rotate.triggered.connect(self.on_tray_rotate_requested)

        menu.addSeparator()

        self.tray_act_auto = menu.addAction("✦ Auto-rotación de Cuentas")
        self.tray_act_auto.setCheckable(True)
        self.tray_act_auto.setChecked(is_auto_switch_enabled())
        self.tray_act_auto.triggered.connect(self.toggle_auto_switch)

        self.tray_act_sound = menu.addAction("♪ Efectos de Sonido")
        self.tray_act_sound.setCheckable(True)
        self.tray_act_sound.setChecked(is_sound_enabled())
        self.tray_act_sound.triggered.connect(self.toggle_sound)

        self.tray_act_startup = menu.addAction("✦ Iniciar con Windows")
        self.tray_act_startup.setCheckable(True)
        self.tray_act_startup.setChecked(is_windows_startup_enabled())
        self.tray_act_startup.triggered.connect(self.toggle_startup)

        menu.addSeparator()

        act_hud = menu.addAction("✦ Abrir Web HUD")
        act_hud.triggered.connect(self.open_hud_browser)

        act_backup = menu.addAction("✦ Exportar Copia de Respaldo")
        act_backup.triggered.connect(self.on_backup_dialog)

        menu.addSeparator()

        act_exit = menu.addAction("✕ Salir de Antigravity Dock")
        act_exit.triggered.connect(self.on_exit_app)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def init_hotkey(self):
        """Starts global hotkey listener thread for Ctrl+Alt+T."""
        self.hotkey_thread = GlobalHotkeyThread()
        self.hotkey_thread.hotkey_triggered.connect(self.on_hotkey_triggered)
        self.hotkey_thread.start()

    def on_hotkey_triggered(self):
        AudioChimeEngine.play_toggle()
        self.toggle_expanded()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_expanded()

    def on_tray_rotate_requested(self):
        mem = load_memory()
        active = mem.get("active_account", "").lower()
        accounts = get_authorized_accounts()
        for acc in accounts:
            email = acc.get("email", "")
            if email.lower() != active:
                self.on_switch_account_requested(email)
                break

    def toggle_auto_switch(self):
        new_state = not is_auto_switch_enabled()
        set_auto_switch_enabled(new_state)
        self.update_auto_button_ui()
        if hasattr(self, "tray_act_auto"):
            self.tray_act_auto.setChecked(new_state)
        if hasattr(self, "tray_icon"):
            self.tray_icon.setIcon(make_tray_icon(new_state))
        notify_auto_switch_toggled(new_state)
        AudioChimeEngine.play_toggle()
        self.refresh_memory_data()

    def update_auto_button_ui(self):
        enabled = is_auto_switch_enabled()
        if enabled:
            self.btn_auto.setText("✦ Auto")
            self.btn_auto.setToolTip("Auto-rotación ACTIVADA (Clic para pausar)")
            self.btn_auto.setStyleSheet("""
                QPushButton {
                    background-color: rgba(16, 185, 129, 0.15);
                    color: #34d399;
                    border: 1px solid rgba(16, 185, 129, 0.35);
                    border-radius: 4px;
                    padding: 1px 6px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(16, 185, 129, 0.25);
                }
            """)
            if hasattr(self, "footer_lbl"):
                self.footer_lbl.setText("✦ Auto-rotación activa • Sondeo 20s")
        else:
            self.btn_auto.setText("⏸ Pausa")
            self.btn_auto.setToolTip("Auto-rotación PAUSADA (Clic para reactivar)")
            self.btn_auto.setStyleSheet("""
                QPushButton {
                    background-color: rgba(245, 158, 11, 0.15);
                    color: #fbbf24;
                    border: 1px solid rgba(245, 158, 11, 0.35);
                    border-radius: 4px;
                    padding: 1px 6px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(245, 158, 11, 0.25);
                }
            """)
            if hasattr(self, "footer_lbl"):
                self.footer_lbl.setText("⏸ Auto-rotación en pausa")

    def toggle_sound(self):
        new_state = not is_sound_enabled()
        set_sound_enabled(new_state)
        self.update_sound_button_ui()
        if hasattr(self, "tray_act_sound"):
            self.tray_act_sound.setChecked(new_state)
        if new_state:
            AudioChimeEngine.play_refresh()

    def update_sound_button_ui(self):
        enabled = is_sound_enabled()
        self.btn_sound.setText("♪" if enabled else "♪✕")
        self.btn_sound.setToolTip("Sonidos activados (Clic para silenciar)" if enabled else "Sonidos silenciados (Clic para activar)")
        self.btn_sound.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: none;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #21252b;
                color: #528bff;
            }
        """)

    def toggle_search(self):
        is_vis = not self.search_bar.isVisible()
        self.search_bar.setVisible(is_vis)
        if is_vis:
            self.search_bar.setFocus()
        else:
            self.search_bar.clear()
        AudioChimeEngine.play_toggle()

    def on_search_text_changed(self, text: str):
        query = text.strip().lower()
        for email, card in self.account_cards.items():
            if not query or query in email.lower():
                card.setVisible(True)
            else:
                card.setVisible(False)

    def toggle_startup(self):
        cur = is_windows_startup_enabled()
        set_windows_startup(not cur)
        if hasattr(self, "tray_act_startup"):
            self.tray_act_startup.setChecked(not cur)
        AudioChimeEngine.play_toggle()

    def open_hud_browser(self):
        webbrowser.open("http://127.0.0.1:59123")
        AudioChimeEngine.play_toggle()

    def on_backup_dialog(self):
        self.is_dialog_active = True
        try:
            path = export_accounts_backup()
            AudioChimeEngine.play_refresh()
            QMessageBox.information(
                self,
                "Backup Creado",
                f"Copia de seguridad guardada exitosamente en:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error al crear backup", str(e))
        finally:
            self.is_dialog_active = False
            self.last_toggle_time = time.time()

    def on_exit_app(self):
        if hasattr(self, "hotkey_thread"):
            self.hotkey_thread.stop()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        QApplication.quit()

    def on_manual_refresh(self):
        self.btn_refresh.setEnabled(False)
        self.sync_timer.start()
        self.status_line.setText("● Sincronizando vía CDP...")
        self.status_line.setStyleSheet("color: #528bff;")

        self.refresh_worker = WorkerRefreshQuota()
        self.refresh_worker.finished.connect(self.on_manual_refresh_done)
        self.refresh_worker.start()

    def on_manual_refresh_done(self, success: bool, msg: str):
        self.sync_timer.stop()
        self.btn_refresh.setText("↻")
        self.btn_refresh.setEnabled(True)
        self.status_line.setText(f"● {msg}")
        self.refresh_memory_data()

    def on_switch_account_requested(self, target_email: str):
        if self.switching:
            return
        self.switching = True
        self.status_line.setText(f"● Cambiando a {target_email}...")
        self.status_line.setStyleSheet("color: #528bff;")

        for card in self.account_cards.values():
            card.btn_switch.setEnabled(False)

        self.switch_worker = WorkerSwitchAccount(target_email)
        self.switch_worker.finished.connect(self.on_switch_account_done)
        self.switch_worker.start()

    def on_switch_account_done(self, success: bool, msg: str):
        self.switching = False
        color = "#10b981" if success else "#ef4444"
        self.status_line.setText(f"● {msg}")
        self.status_line.setStyleSheet(f"color: {color};")
        if success:
            AudioChimeEngine.play_switch_success()
        else:
            AudioChimeEngine.play_alert()
        self.refresh_memory_data()

    def on_add_account_dialog(self):
        self.is_dialog_active = True
        try:
            dlg = AddAccountDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.reload_accounts_ui()
        finally:
            self.is_dialog_active = False
            self.last_toggle_time = time.time()

    def reload_accounts_ui(self):
        # Clear existing cards
        for card in list(self.account_cards.values()):
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        self.account_cards.clear()

        # Re-populate cards from configuration
        configured_accounts = get_authorized_accounts()
        for acc in configured_accounts:
            card = MinimalistAccountCard(acc, self.cards_container)
            card.request_switch.connect(self.on_switch_account_requested)
            self.account_cards[acc["email"]] = card
            self.cards_layout.addWidget(card)

        self.refresh_memory_data()

    def closeEvent(self, event):
        if hasattr(self, "hotkey_thread"):
            self.hotkey_thread.stop()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        if self.win_event_hook:
            user32.UnhookWinEvent(self.win_event_hook)
        super().closeEvent(event)

def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    overlay = AntigravityDockedOverlay()
    overlay.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
