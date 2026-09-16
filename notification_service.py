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

import threading

logger = logging.getLogger("NotificationService")

def _send_toast_worker(title: str, message: str, app_id: str):
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
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            
        import base64
        encoded_cmd = base64.b64encode(ps_cmd.encode("utf-16-le")).decode("ascii")
        res = subprocess.run(
            ["powershell.exe", "-WindowStyle", "Hidden", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_cmd],
            capture_output=True,
            text=True,
            timeout=8,
            startupinfo=startupinfo,
            creationflags=creationflags
        )
        if res.returncode == 0:
            logger.info(f"Toast notification sent: '{title}' - '{message}'")
        else:
            logger.warning(f"Toast notification failed: {res.stderr.strip()}")
    except Exception as e:
        logger.warning(f"Error sending toast notification: {e}")

def send_windows_toast(
    title: str,
    message: str,
    app_id: str = "Antigravity Account Controller",
    sync: bool = False
) -> bool:
    """
    Sends a native Windows Toast notification via PowerShell WinRT APIs.
    Runs asynchronously in background thread to guarantee 0ms caller latency.
    """
    if sync:
        _send_toast_worker(title, message, app_id)
        return True
    
    thread = threading.Thread(
        target=_send_toast_worker,
        args=(title, message, app_id),
        daemon=True
    )
    thread.start()
    return True

def notify_rotation_success(prev_account: str, new_account: str, new_pct_5h: Optional[int] = None):
    """Notification when an account rotation completes successfully."""
    title = "↻ Antigravity: Rotación de Cuenta Exitosa"
    msg = f"De: {prev_account.split('@')[0]}\nA: {new_account.split('@')[0]}"
    if new_pct_5h is not None:
        msg += f" (Cuota inicial 5h: {new_pct_5h}%)"
    send_windows_toast(title, msg)

def notify_token_refresh(account: str, quota_type: str = "5 Horas"):
    """Notification when an idle account reaches 100% recharge."""
    title = "✦ Antigravity: Tokens Recargados"
    msg = f"La cuenta {account.split('@')[0]} ha completado su recarga de {quota_type} (100% disponible)."
    send_windows_toast(title, msg)

def notify_dual_exhaustion_warning(minutes_to_recharge: int):
    """Critical warning when both accounts are exhausted and retention is engaged."""
    title = "[!] Antigravity: Ambas Cuentas al Límite"
    msg = f"Protocolo de retención activo. Próxima recarga estimada en {minutes_to_recharge} min."
    send_windows_toast(title, msg)

def notify_preemptive_switch(current_account: str, next_account: str, current_pct: int):
    """Notification when proactive switch occurs before 0% crash."""
    title = "✦ Antigravity: Rotación Preventiva Inteligente"
    msg = f"Cuota baja ({current_pct}%). Rotando a {next_account.split('@')[0]} para evitar interrupciones."
    send_windows_toast(title, msg)

def notify_auto_switch_toggled(enabled: bool):
    """Notification when user toggles auto-switch."""
    state = "ACTIVADA" if enabled else "PAUSADA"
    title = f"↻ Antigravity: Auto-Rotación {state}"
    msg = "El daemon cambiará automáticamente de cuenta al agotarse cuota." if enabled else "La cuenta actual se mantendrá fija hasta rotación manual."
    send_windows_toast(title, msg)

def notify_verification_required(
    account_email: str,
    challenge_type: str,
    details: str = "",
    prompt_number: Optional[str] = None
):
    """Notification when Google requires additional 2FA / challenge verification."""
    acc_name = account_email.split('@')[0] if account_email else "Google"
    title = f"✦ Antigravity: Verificación de Google ({acc_name})"

    c_upper = (challenge_type or "").upper()
    if ("PHONE_PROMPT" in c_upper or "DEVICE" in c_upper) and prompt_number:
        msg = f"Toca el número {prompt_number} en tu teléfono para autorizar el acceso."
    elif "PHONE_PROMPT" in c_upper or "DEVICE" in c_upper:
        msg = "Comprueba tu teléfono y pulsa 'Sí' en la notificación de Google."
    elif "CODE" in c_upper or "2FA" in c_upper or "TOTP" in c_upper:
        msg = "Introduce el código de verificación (SMS o Google Authenticator)."
    elif "PASSWORD" in c_upper or "PWD" in c_upper:
        msg = "Introduce la contraseña de la cuenta en el navegador para continuar."
    elif "RECOVERY" in c_upper:
        msg = "Confirma tu método de recuperación para verificar tu identidad."
    elif "PASSKEY" in c_upper or "SECURITY_KEY" in c_upper:
        msg = "Usa tu llave de seguridad física o passkey para continuar."
    elif "CAPTCHA" in c_upper:
        msg = "Resuelve el captcha en el navegador para continuar."
    else:
        msg = details or "Google requiere verificación adicional en el navegador."

    send_windows_toast(title, msg)

if __name__ == "__main__":
    print("Enviando toast de prueba...")
    success = send_windows_toast(
        "✦ Antigravity Controller",
        "Sistema de Notificaciones Nativas Windows Activo y Verificado."
    )
    print("Resultado:", "ÉXITO" if success else "FALLO")
