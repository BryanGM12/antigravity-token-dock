"""
Notification Service: Native Windows Toast Notifications for Antigravity Controller
Sends non-intrusive Windows 10/11 Toast Notifications for rotation events,
quota threshold warnings, and token refresh completion.
"""

import os
import sys
import logging
import subprocess
from typing import Optional

logger = logging.getLogger("NotificationService")

def send_windows_toast(
    title: str,
    message: str,
    app_id: str = "Antigravity Account Controller"
) -> bool:
    """
    Sends a native Windows Toast notification via PowerShell WinRT APIs.
    Runs completely silently in the background without stealing window focus.
    """
    try:
        # Sanitize strings to avoid quote breakage
        safe_title = title.replace('"', '`"').replace("'", "''")
        safe_msg = message.replace('"', '`"').replace("'", "''")
        safe_app = app_id.replace('"', '`"').replace("'", "''")
        
        ps_cmd = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $template.GetElementsByTagName("text")
$texts.Item(0).AppendChild($template.CreateTextNode("{safe_title}")) | Out-Null
$texts.Item(1).AppendChild($template.CreateTextNode("{safe_msg}")) | Out-Null

$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{safe_app}")
$notification = [Windows.UI.Notifications.ToastNotification]::new($template)
$notifier.Show($notification)
"""
        # Execute powershell with hidden window
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=5,
            startupinfo=startupinfo
        )
        if res.returncode == 0:
            logger.info(f"Toast notification sent: '{title}' - '{message}'")
            return True
        else:
            logger.warning(f"Toast notification failed: {res.stderr.strip()}")
            return False
    except Exception as e:
        logger.warning(f"Error sending toast notification: {e}")
        return False

def notify_rotation_success(prev_account: str, new_account: str, new_pct_5h: Optional[int] = None):
    """Notification when an account rotation completes successfully."""
    title = "🔄 Antigravity: Rotación de Cuenta Exitosa"
    msg = f"De: {prev_account.split('@')[0]}\nA: {new_account.split('@')[0]}"
    if new_pct_5h is not None:
        msg += f" (Cuota inicial 5h: {new_pct_5h}%)"
    send_windows_toast(title, msg)

def notify_token_refresh(account: str, quota_type: str = "5 Horas"):
    """Notification when an idle account reaches 100% recharge."""
    title = "⚡ Antigravity: Tokens Recargados"
    msg = f"La cuenta {account.split('@')[0]} ha completado su recarga de {quota_type} (100% disponible)."
    send_windows_toast(title, msg)

def notify_dual_exhaustion_warning(minutes_to_recharge: int):
    """Critical warning when both accounts are exhausted and retention is engaged."""
    title = "⚠️ Antigravity: Ambas Cuentas al Límite"
    msg = f"Protocolo de retención activo. Próxima recarga estimada en {minutes_to_recharge} min."
    send_windows_toast(title, msg)

def notify_preemptive_switch(current_account: str, next_account: str, current_pct: int):
    """Notification when proactive switch occurs before 0% crash."""
    title = "⚡ Antigravity: Rotación Preventiva Inteligente"
    msg = f"Cuota baja ({current_pct}%). Rotando a {next_account.split('@')[0]} para evitar interrupciones."
    send_windows_toast(title, msg)

def notify_auto_switch_toggled(enabled: bool):
    """Notification when user toggles auto-switch."""
    state = "ACTIVADA" if enabled else "PAUSADA"
    title = f"🔄 Antigravity: Auto-Rotación {state}"
    msg = "El daemon cambiará automáticamente de cuenta al agotarse cuota." if enabled else "La cuenta actual se mantendrá fija hasta rotación manual."
    send_windows_toast(title, msg)

if __name__ == "__main__":
    print("Enviando toast de prueba...")
    success = send_windows_toast(
        "🚀 Antigravity Controller",
        "Sistema de Notificaciones Nativas Windows Activo y Verificado."
    )
    print("Resultado:", "ÉXITO" if success else "FALLO")
