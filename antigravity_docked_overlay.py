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

import psutil
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QSize, QPoint, QRect,
    QVariantAnimation, QEasingCurve
)
from PyQt6.QtGui import (
    QColor, QFont, QCursor, QPainter, QBrush, QPen, QPainterPath
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QScrollArea, QFrame, QGraphicsDropShadowEffect,
    QDialog, QLineEdit, QCheckBox
)

from config_manager import get_authorized_accounts, load_accounts_config, add_account

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
                background-color: #14161b;
                border: 1px solid #282c37;
                border-radius: 10px;
            }
            QLabel {
                color: #e2e8f0;
            }
            QLineEdit {
                background-color: #1a1d24;
                color: #ffffff;
                border: 1px solid #2d323f;
                border-radius: 5px;
                padding: 6px 8px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #528bff;
            }
            QPushButton {
                background-color: #21252b;
                color: #e2e8f0;
                border: 1px solid #2d323c;
                border-radius: 5px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #528bff;
                color: #ffffff;
                border-color: #528bff;
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
        title.setStyleSheet("color: #f1f5f9; padding-bottom: 2px;")
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

        self.chk_pro = QCheckBox("👑 Cuenta Pro / Ultra")
        self.chk_pro.setChecked(True)
        layout.addWidget(self.chk_pro)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("Guardar Cuenta")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #528bff;
                color: #ffffff;
                border: 1px solid #528bff;
            }
            QPushButton:hover {
                background-color: #3b74e6;
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
        tier = "👑 Pro" if self.chk_pro.isChecked() else "Standard"
        try:
            add_account(email, name=name, tier=tier)
            self.accept()
        except Exception:
            self.reject()

class MinimalistAccountCard(QFrame):
    """Ultra-clean, compact account card with Antigravity design aesthetics."""
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
                background-color: #181b22;
                border: 1px solid #262a35;
                border-radius: 8px;
            }
            QFrame#MinimalCard[active="true"] {
                background-color: #161e2b;
                border: 1px solid #528bff;
            }
            QFrame#MinimalCard[exhausted="true"] {
                background-color: #15161b;
                border: 1px solid #281d22;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header Row: Email + Chips
        h_row = QHBoxLayout()
        h_row.setSpacing(6)

        self.lbl_email = QLabel(self.email)
        self.lbl_email.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lbl_email.setStyleSheet("color: #f1f5f9;")

        self.lbl_tier = QLabel(self.account_info.get("tier", "👑 Pro"))
        self.lbl_tier.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        self.lbl_tier.setStyleSheet("""
            background-color: rgba(168, 85, 247, 0.15);
            color: #c084fc;
            border: 1px solid rgba(168, 85, 247, 0.3);
            border-radius: 4px;
            padding: 1px 5px;
        """)

        self.lbl_badge = QLabel("EN ESPERA")
        self.lbl_badge.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        self.lbl_badge.setStyleSheet("""
            background-color: #21252b;
            color: #64748b;
            border-radius: 4px;
            padding: 1px 5px;
        """)

        h_row.addWidget(self.lbl_email, 1)
        h_row.addWidget(self.lbl_tier)
        h_row.addWidget(self.lbl_badge)
        layout.addLayout(h_row)

        # Metric 1: Gemini 5h
        m1_layout = QHBoxLayout()
        m1_layout.setContentsMargins(0, 2, 0, 0)
        lbl_5h_name = QLabel("Gemini 5h:")
        lbl_5h_name.setFont(QFont("Segoe UI", 8))
        lbl_5h_name.setStyleSheet("color: #94a3b8;")

        self.lbl_5h_val = QLabel("100%")
        self.lbl_5h_val.setFont(QFont("Segoe UI", 8))
        self.lbl_5h_val.setStyleSheet("color: #e2e8f0;")
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
        lbl_wk_name.setStyleSheet("color: #94a3b8;")

        self.lbl_wk_val = QLabel("--")
        self.lbl_wk_val.setFont(QFont("Segoe UI", 8))
        self.lbl_wk_val.setStyleSheet("color: #cbd5e1;")
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

        # Live model chips row
        self.lbl_chips = QLabel()
        self.lbl_chips.setFont(QFont("Segoe UI", 7))
        self.lbl_chips.setStyleSheet("color: #64748b; padding-bottom: 2px;")
        self.lbl_chips.setVisible(False)
        layout.addWidget(self.lbl_chips)

        # Action Switch Button (Minimalist Ghost Pill)
        self.btn_switch = QPushButton("⇄ Cambiar a esta cuenta")
        self.btn_switch.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.btn_switch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_switch.setFixedHeight(24)
        self.btn_switch.clicked.connect(lambda: self.request_switch.emit(self.email))
        layout.addWidget(self.btn_switch)

    def _set_bar_color(self, bar: QProgressBar, pct: int):
        if pct > 50:
            color = "#528bff"  # Signature Antigravity Blue
        elif pct >= 20:
            color = "#f59e0b"  # Amber
        else:
            color = "#ef4444"  # Red

        bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #212631;
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 2px;
            }}
        """)

    def set_pulse_alpha(self, alpha: float):
        """Modulates glowing badge opacity for the active account."""
        if self.property("active"):
            bg_a = int(35 + 25 * alpha)
            border_a = int(60 + 50 * alpha)
            self.lbl_badge.setStyleSheet(f"""
                background-color: rgba(16, 185, 129, {bg_a / 255:.2f});
                color: #34d399;
                border: 1px solid rgba(16, 185, 129, {border_a / 255:.2f});
                border-radius: 4px;
                padding: 1px 5px;
            """)

    def update_data(self, status_data: dict, is_active: bool):
        gem = status_data.get("gemini", {})
        p_5h = gem.get("five_hour_remaining_pct")
        p_wk = gem.get("weekly_remaining_pct")
        is_exhausted = status_data.get("is_exhausted", False) or (p_5h is not None and p_5h <= 0) or (p_wk is not None and p_wk <= 0)

        self.setProperty("active", is_active)
        self.setProperty("exhausted", is_exhausted and not is_active)
        self.style().unpolish(self)
        self.style().polish(self)

        if is_active:
            self.lbl_email.setStyleSheet("color: #528bff;")
            self.lbl_badge.setText("● ACTIVA")
            self.lbl_badge.setStyleSheet("""
                background-color: rgba(16, 185, 129, 0.15);
                color: #34d399;
                border: 1px solid rgba(16, 185, 129, 0.3);
                border-radius: 4px;
                padding: 1px 5px;
            """)
            self.btn_switch.setText("✓ Sesión Activa")
            self.btn_switch.setEnabled(False)
            self.btn_switch.setStyleSheet("""
                QPushButton {
                    background-color: rgba(82, 139, 255, 0.1);
                    color: #93c5fd;
                    border: 1px solid rgba(82, 139, 255, 0.25);
                    border-radius: 5px;
                }
            """)
        elif is_exhausted:
            self.lbl_email.setStyleSheet("color: #94a3b8;")
            self.lbl_badge.setText("✕ AGOTADA")
            self.lbl_badge.setStyleSheet("""
                background-color: rgba(239, 68, 68, 0.12);
                color: #f87171;
                border: 1px solid rgba(239, 68, 68, 0.25);
                border-radius: 4px;
                padding: 1px 5px;
            """)
            self.btn_switch.setText("⇄ Cambiar (Agotada)")
            self.btn_switch.setEnabled(True)
            self.btn_switch.setStyleSheet("""
                QPushButton {
                    background-color: #1a1d24;
                    color: #94a3b8;
                    border: 1px solid #282c35;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #222630;
                    color: #e2e8f0;
                    border-color: #3e4453;
                }
            """)
        else:
            self.lbl_email.setStyleSheet("color: #f1f5f9;")
            self.lbl_badge.setText("DISPONIBLE")
            self.lbl_badge.setStyleSheet("""
                background-color: rgba(59, 130, 246, 0.12);
                color: #60a5fa;
                border: 1px solid rgba(59, 130, 246, 0.25);
                border-radius: 4px;
                padding: 1px 5px;
            """)
            self.btn_switch.setText("⇄ Cambiar a esta cuenta")
            self.btn_switch.setEnabled(True)
            self.btn_switch.setStyleSheet("""
                QPushButton {
                    background-color: #21252b;
                    color: #e2e8f0;
                    border: 1px solid #2d323c;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #528bff;
                    color: #ffffff;
                    border-color: #528bff;
                }
                QPushButton:pressed {
                    background-color: #3b74e6;
                }
            """)

        # Gemini 5h
        gem = status_data.get("gemini", {})
        p_5h = gem.get("five_hour_remaining_pct")
        if p_5h is not None:
            val = int(p_5h)
            self.bar_5h.setValue(val)
            self._set_bar_color(self.bar_5h, val)
            eta = gem.get("five_hour_recharge_in") or gem.get("five_hour_refresh_text") or "OK"
            clock = f" ({gem.get('five_hour_eta_clock')})" if gem.get('five_hour_eta_clock') else ""
            self.lbl_5h_val.setText(f"{val}% • {eta}{clock}")
        else:
            self.bar_5h.setValue(100)
            self._set_bar_color(self.bar_5h, 100)
            self.lbl_5h_val.setText("100% • Lista")

        # Gemini Semanal
        p_wk = gem.get("weekly_remaining_pct")
        if p_wk is not None:
            val_w = int(p_wk)
            self.bar_wk.setValue(val_w)
            self._set_bar_color(self.bar_wk, val_w)
            eta_w = gem.get("weekly_recharge_in") or "--"
            self.lbl_wk_val.setText(f"{val_w}% • {eta_w}")
        else:
            self.bar_wk.setValue(100)
            self._set_bar_color(self.bar_wk, 100)
            self.lbl_wk_val.setText("--")

        # Claude / GPT
        cgpt = status_data.get("claude_gpt", {})
        c_5h = cgpt.get("five_hour_remaining_pct")
        c_wk = cgpt.get("weekly_remaining_pct")
        c_eta = cgpt.get("weekly_recharge_in") or "--"
        c_5h_s = f"{c_5h}%" if c_5h is not None else "--"
        c_wk_s = f"{c_wk}%" if c_wk is not None else "--"
        self.lbl_claude.setText(f"Claude/GPT: 5h: {c_5h_s} • Semanal: {c_wk_s} ({c_eta})")

        # Live model chips
        models = status_data.get("models", {})
        chips = []
        if isinstance(models, dict):
            for m_key, m_val in models.items():
                if not isinstance(m_val, dict):
                    continue
                lbl = m_val.get("label", m_key)
                frac = m_val.get("remaining_fraction")
                if frac is not None:
                    short = lbl.replace("Gemini ", "g-").replace("Claude ", "c-").replace(" (Thinking)", "").replace(" (High)", "-hi").replace(" (Medium)", "-med").replace(" (Low)", "-lo")
                    chips.append(f"{short}:{int(frac * 100)}%")
        if chips:
            self.lbl_chips.setText(" • ".join(chips[:3]))
            self.lbl_chips.setVisible(True)
        else:
            self.lbl_chips.setVisible(False)


class MinimalistPillHandle(QFrame):
    """Ultra-slim (28px x 110px) minimalist tab pinned to Antigravity window."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(28)
        self.setFixedHeight(110)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("✦ Antigravity Tokens (Clic para abrir / cerrar)")
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

        bg_color = QColor("#21252b") if self.is_hovered else QColor("#181a20")
        border_color = QColor("#528bff") if self.is_hovered else QColor(82, 139, 255, 120)

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
        glow_r = int(82 + 30 * self.pulse_val)
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.setPen(QColor(glow_r, 139, 255))
        painter.drawText(QRect(0, 8, w, 20), Qt.AlignmentFlag.AlignCenter, "✦")

        # Vertical Divider Micro Line
        painter.setPen(QPen(QColor(82, 139, 255, 140 if self.is_hovered else 60), 1.5))
        painter.drawLine(w // 2, 36, w // 2, h - 32)

        # Chevron Arrow › / ‹
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.setPen(QColor("#ffffff" if self.is_hovered else "#94a3b8"))
        arrow = "‹" if self.is_expanded else "›"
        painter.drawText(QRect(0, h - 26, w, 18), Qt.AlignmentFlag.AlignCenter, arrow)


class AntigravityDockedOverlay(QWidget):
    """
    Ultra-responsive native desktop widget docked to Antigravity.
    Smooth slide-in / slide-out animations and zero-lag Win32 tracking.
    """
    def __init__(self):
        super().__init__()
        self.is_expanded = False
        self.current_panel_w = 0
        self.antigravity_hwnd: Optional[int] = None
        self.last_rect = None
        self.switching = False
        self.last_memory_mtime = 0
        self.win_event_hook = None
        self._hook_cb_ref = None
        self.sync_spin_step = 0

        self.init_window_flags()
        self.init_ui()
        self.init_animations()
        self.init_tracking_engine()
        self.refresh_memory_data()

    def init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Antigravity Token Dock")

    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 1. Minimalist Pill Handle
        self.pill_handle = MinimalistPillHandle(self)
        self.pill_handle.clicked.connect(self.toggle_expanded)

        # 2. Minimalist Expanded Container (360px target)
        self.panel_container = QFrame()
        self.panel_container.setObjectName("PanelContainer")
        self.panel_container.setFixedWidth(0)
        self.panel_container.setStyleSheet("""
            QFrame#PanelContainer {
                background-color: #14161b;
                border: 1px solid #282c37;
                border-radius: 12px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 140))
        shadow.setOffset(0, 4)
        self.panel_container.setGraphicsEffect(shadow)

        panel_layout = QVBoxLayout(self.panel_container)
        panel_layout.setContentsMargins(12, 10, 12, 10)
        panel_layout.setSpacing(6)

        # Antigravity Signature Gradient Line
        grad_line = QFrame()
        grad_line.setFixedHeight(2)
        grad_line.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 #528bff, stop:0.35 #818cf8, stop:0.7 #c084fc, stop:1 #f472b6);
            border-radius: 1px;
            border: none;
        """)
        panel_layout.addWidget(grad_line)

        # Top Bar (Header)
        top_bar = QHBoxLayout()
        top_bar.setSpacing(4)

        icon_star = QLabel("✦")
        icon_star.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        icon_star.setStyleSheet("color: #528bff;")

        title_lbl = QLabel("Antigravity Tokens")
        title_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #f1f5f9;")

        self.btn_add = QPushButton("+")
        self.btn_add.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.btn_add.setFixedSize(24, 24)
        self.btn_add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_add.setToolTip("Agregar nueva cuenta de Google")
        self.btn_add.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #528bff;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #21252b;
                color: #93c5fd;
            }
        """)
        self.btn_add.clicked.connect(self.on_add_account_dialog)

        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFont(QFont("Segoe UI", 11))
        self.btn_refresh.setFixedSize(24, 24)
        self.btn_refresh.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_refresh.setToolTip("Actualizar tokens en vivo vía CDP")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #21252b;
                color: #528bff;
            }
        """)
        self.btn_refresh.clicked.connect(self.on_manual_refresh)

        btn_close = QPushButton("✕")
        btn_close.setFont(QFont("Segoe UI", 9))
        btn_close.setFixedSize(24, 24)
        btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close.setToolTip("Ocultar panel")
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #21252b;
                color: #f1f5f9;
            }
        """)
        btn_close.clicked.connect(self.toggle_expanded)

        top_bar.addWidget(icon_star)
        top_bar.addWidget(title_lbl, 1)
        top_bar.addWidget(self.btn_add)
        top_bar.addWidget(self.btn_refresh)
        top_bar.addWidget(btn_close)
        panel_layout.addLayout(top_bar)

        # Micro Status Line
        self.status_line = QLabel("● Monitoreo continuo activo")
        self.status_line.setFont(QFont("Segoe UI", 7))
        self.status_line.setStyleSheet("color: #64748b; padding-bottom: 2px;")
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
                background: #181b22;
                width: 4px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: #2d323c;
                border-radius: 2px;
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

        # Minimal Footer
        footer = QLabel("⚡ Auto-rotación activa • Sondeo 20s")
        footer.setFont(QFont("Segoe UI", 7))
        footer.setStyleSheet("color: #475569; padding-top: 2px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(footer)

        # Add to main layout
        self.main_layout.addWidget(self.pill_handle)
        self.main_layout.addWidget(self.panel_container)
        self.panel_container.setVisible(False)

        self.set_collapsed_geometry()

    def init_animations(self):
        """Initializes slide animation and breathing glow timers."""
        # 1. Slide Animation for Expand / Collapse
        self.slide_anim = QVariantAnimation(self)
        self.slide_anim.setDuration(220)
        self.slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.slide_anim.valueChanged.connect(self.on_slide_value)
        self.slide_anim.finished.connect(self.on_slide_finished)

        # 2. Breathing / Pulse Heartbeat Timer (60ms)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(60)
        self.pulse_timer.timeout.connect(self.on_pulse_tick)
        self.pulse_timer.start()

        # 3. Rotating Sync Icon Timer
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(120)
        self.sync_timer.timeout.connect(self.on_sync_spin)

    def on_pulse_tick(self):
        val = 0.5 + 0.5 * math.sin(time.time() * 3.2)
        self.pill_handle.set_pulse(val)
        if self.is_expanded:
            for card in self.account_cards.values():
                card.set_pulse_alpha(val)

    def on_sync_spin(self):
        spinner_chars = ["◐", "◓", "◑", "◒"]
        self.sync_spin_step = (self.sync_spin_step + 1) % len(spinner_chars)
        self.btn_refresh.setText(spinner_chars[self.sync_spin_step])

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.is_expanded:
                self.toggle_expanded()
            elif event.pos().x() <= 28 and event.pos().y() <= 110:
                self.toggle_expanded()
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

    def toggle_expanded(self):
        self.is_expanded = not self.is_expanded
        self.pill_handle.set_expanded(self.is_expanded)

        self.slide_anim.stop()
        if self.is_expanded:
            self.panel_container.setVisible(True)
            self.slide_anim.setStartValue(self.current_panel_w)
            self.slide_anim.setEndValue(360)
            self.refresh_memory_data()
        else:
            self.slide_anim.setStartValue(self.current_panel_w)
            self.slide_anim.setEndValue(0)
        self.slide_anim.start()

    def on_slide_value(self, val):
        self.current_panel_w = int(val)
        self.panel_container.setFixedWidth(self.current_panel_w)
        self.update_dock_position(animating=True)

    def on_slide_finished(self):
        if not self.is_expanded:
            self.panel_container.setVisible(False)
            self.current_panel_w = 0
            self.set_collapsed_geometry()
        else:
            self.current_panel_w = 360
        self.update_dock_position(animating=False)

    def update_dock_position(self, animating: bool = False):
        """Positions widget cleanly with zero lag and hardware acceleration."""
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

        if self.is_expanded or animating:
            widget_w = 28 + self.current_panel_w
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
            if updated_at and not self.switching:
                from datetime import datetime
                dt = datetime.fromisoformat(updated_at)
                self.status_line.setText(f"● Sincronizado: {dt.strftime('%H:%M:%S')} • Activa: {active_acc.split('@')[0]}")
                self.status_line.setStyleSheet("color: #64748b;")
        except Exception as e:
            self.status_line.setText(f"Error memoria: {e}")

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
        self.refresh_memory_data()

    def on_add_account_dialog(self):
        dlg = AddAccountDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.reload_accounts_ui()

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
