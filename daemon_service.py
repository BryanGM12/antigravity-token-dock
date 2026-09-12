"""
Daemon Service: Autonomous Antigravity Account Rotation & Quota Monitor
Continuously monitors quota and active tasks. When tokens exhaust, switches accounts
and resumes paused conversation tasks. Integrates HUD, Analytics, Watchdog, Toast Notifications, and Goal Resumer.
"""

import os
import sys
import time
import asyncio
import logging
import argparse
import json
from typing import Optional
import psutil
from playwright.async_api import async_playwright

LOG_DIR = os.path.expandvars(r"%USERPROFILE%\.openclaw\workspace\state\antigravity_controller")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "controller.log")

class AutoFlushFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

# Configure root logger explicitly before importing submodules
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for h in list(root_logger.handlers):
    root_logger.removeHandler(h)

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
file_handler = AutoFlushFileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

logger = logging.getLogger("AntigravityDaemon")

# Core Modules
from antigravity_bridge import (
    connect_antigravity,
    get_active_conversation_id,
    get_current_logged_in_email,
    open_settings,
    close_settings
)
from quota_detector import (
    get_quota_limits,
    evaluate_token_exhaustion,
    check_log_quota_errors,
    check_chat_quota_errors
)
from account_rotator import rotate_account, determine_target_account
from task_resumer import navigate_to_conversation, resume_conversation_task
from goal_resumer import resume_with_context, clear_hung_generation
from token_memory import (
    format_memory_status_table,
    evaluate_switch_readiness,
    get_effective_account_status,
    load_memory
)

# New Subsystems
from notification_service import (
    send_windows_toast,
    notify_rotation_success,
    notify_token_refresh,
    notify_dual_exhaustion_warning
)
from analytics_engine import (
    record_usage_sample,
    record_rotation_event,
    calculate_burn_rate,
    format_analytics_report
)
from watchdog_service import (
    cleanup_orphan_comet_auth_tabs,
    ensure_dark_theme,
    run_health_audit
)
from local_hud import start_hud_in_background, HUD_PORT

COOLDOWN_SECONDS = 300  # 5 minutes minimum between automatic switches to avoid thrashing

async def check_status_cli():
    """Takes a live quota sample (if Antigravity is active) and displays the memory status table."""
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
            
    if is_antigravity_running():
        try:
            async with async_playwright() as p:
                browser, page = await connect_antigravity(p)
                await get_quota_limits(page)
                await browser.close()
        except Exception as e:
            logger.warning(f"No se pudo sincronizar cuota en vivo via CDP: {e}")
            
    # Print the formatted memory status table
    print(format_memory_status_table())

async def run_single_switch(target_email: Optional[str] = None):
    """Executes a single immediate account switch and task resumption."""
    target_str = f" to {target_email}" if target_email else ""
    logger.info(f"Executing immediate manual account switch{target_str}...")
    async with async_playwright() as p:
        browser, page = await connect_antigravity(p)
        ctx = browser.contexts[0]
        
        # Ensure dark theme is maintained
        await ensure_dark_theme(page)
        
        # Save active conversation ID
        conv_id = await get_active_conversation_id(page)
        logger.info(f"Saved active conversation ID before switch: {conv_id}")
        
        # Perform rotation
        success, prev, new_acc = await rotate_account(page, ctx, target_email=target_email)
        if success:
            logger.info(f"Account rotation successful: {prev} -> {new_acc}")
            # Record analytics & send toast
            record_rotation_event(prev, new_acc)
            new_st = get_effective_account_status(new_acc)
            record_usage_sample(new_acc, new_st.get("five_hour_remaining_pct"), new_st.get("weekly_remaining_pct"))
            notify_rotation_success(prev, new_acc, new_st.get("five_hour_remaining_pct"))
            
            # Deep task resumption
            if conv_id:
                logger.info(f"Resuming conversation {conv_id}...")
                await navigate_to_conversation(page, conv_id)
                await resume_with_context(page)
        else:
            logger.error("Account rotation failed.")
            
        await browser.close()

def is_antigravity_running() -> bool:
    """Checks if any Antigravity process is actively running."""
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info.get('name') or ''
            if 'antigravity.exe' in name.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

async def run_daemon_loop(poll_interval_sec: int = 15):
    """Perpetual background loop monitoring quota and triggering automatic rotation."""
    logger.info("=======================================================")
    logger.info("Antigravity Autonomous Account Daemon iniciado.")
    logger.info("=======================================================")
    
    # 1. Start Local HUD Server
    try:
        start_hud_in_background(HUD_PORT)
        logger.info(f"[HUD] Servidor Local HUD activo en http://127.0.0.1:{HUD_PORT}")
    except Exception as e:
        logger.warning(f"[HUD] No se pudo iniciar el servidor Local HUD: {e}")
        
    last_switch_time = 0
    last_ui_sample_time = 0
    last_retention_notify_time = 0
    UI_SAMPLE_INTERVAL = 20  # Sample UI quota every 20 seconds for live token display
    
    # Take initial sample on startup
    if is_antigravity_running():
        try:
            async with async_playwright() as p:
                browser, page = await connect_antigravity(p)
                logger.info("Capturando muestra inicial de cuota y cuenta...")
                await ensure_dark_theme(page)
                await get_quota_limits(page)
                last_ui_sample_time = time.time()
                
                # Record sample in analytics
                mem = load_memory()
                active_acc = mem.get("active_account")
                if active_acc:
                    st = get_effective_account_status(active_acc)
                    record_usage_sample(
                        active_acc,
                        st.get("five_hour_remaining_pct"),
                        st.get("weekly_remaining_pct")
                    )
                await browser.close()
                logger.info("Muestra inicial registrada en memoria y analiticas exitosamente.")
        except Exception as e:
            logger.warning(f"No se pudo capturar muestra inicial: {e}")
            
    while True:
        # Check if Antigravity is still running
        if not is_antigravity_running():
            logger.info("Antigravity no detectado en ejecucion. Esperando 5s de gracia...")
            await asyncio.sleep(5.0)
            if not is_antigravity_running():
                logger.info("Antigravity cerrado. Finalizando daemon ordenadamente.")
                break
                
        # Watchdog: cleanup orphan Comet authentication tabs
        try:
            cleaned = cleanup_orphan_comet_auth_tabs()
            if cleaned > 0:
                logger.info(f"[Watchdog] Cerradas {cleaned} pestana(s) huerfanas de Comet.")
        except Exception as e:
            logger.debug(f"[Watchdog] Error limpiando pestanas huerfanas: {e}")
                
        try:
            # 1. Fast check: language_server.log
            log_exhausted, log_reason = check_log_quota_errors(lookback_seconds=30)
            
            # 2. Check chat errors or periodic UI sample
            async with async_playwright() as p:
                browser, page = await connect_antigravity(p)
                ctx = browser.contexts[0]
                
                # Watchdog: ensure dark theme stays enforced
                await ensure_dark_theme(page)
                
                chat_exhausted, chat_reason = await check_chat_quota_errors(page)
                
                now = time.time()
                if (now - last_ui_sample_time) > UI_SAMPLE_INTERVAL or log_exhausted or chat_exhausted:
                    await get_quota_limits(page)
                    last_ui_sample_time = now
                    
                    mem = load_memory()
                    active_acc = mem.get("active_account")
                    if active_acc:
                        st = get_effective_account_status(active_acc)
                        record_usage_sample(
                            active_acc,
                            st.get("five_hour_remaining_pct"),
                            st.get("weekly_remaining_pct")
                        )
                    
                is_exhausted = log_exhausted or chat_exhausted
                reason = chat_reason if chat_exhausted else (log_reason if log_exhausted else "")
                
                # If neither log nor chat flagged an error, check memory for 0%
                if not is_exhausted:
                    mem = load_memory()
                    active_acc = mem.get("active_account")
                    if active_acc:
                        st = get_effective_account_status(active_acc)
                        p_5h = st.get("five_hour_remaining_pct")
                        p_wk = st.get("weekly_remaining_pct")
                        if (p_5h is not None and p_5h <= 0) or (p_wk is not None and p_wk <= 0):
                            is_exhausted = True
                            reason = f"Cuota de cuenta activa en 0% (5h: {p_5h}%, Semanal: {p_wk}%)"
                            
                if is_exhausted:
                    elapsed_since_switch = now - last_switch_time
                    if elapsed_since_switch < COOLDOWN_SECONDS:
                        logger.warning(
                            f"Tokens agotados ({reason}), pero en periodo de cooldown ({int(COOLDOWN_SECONDS - elapsed_since_switch)}s restantes). Esperando..."
                        )
                    else:
                        mem = load_memory()
                        current_email = mem.get("active_account")
                        if not current_email:
                            current_email = await get_current_logged_in_email(page, close_after=True)
                            
                        can_switch, switch_reason, wait_sec, best_target = evaluate_switch_readiness(current_email)
                        
                        if not can_switch:
                            logger.warning(
                                f"[RETENCION] {switch_reason} Todas las cuentas estan agotadas o no listas. El daemon retendra la alternancia para evitar bucles."
                            )
                            if (now - last_retention_notify_time) > 900:  # At most once per 15 min
                                notify_dual_exhaustion_warning(max(1, int((wait_sec or 300) // 60)))
                                last_retention_notify_time = now
                        else:
                            logger.warning(f"[ALERTA] AGOTAMIENTO DE TOKENS DETECTADO: {reason}")
                            logger.info(f"Autorizando alternancia: {switch_reason} (Destino: {best_target})")
                            
                            conv_id = await get_active_conversation_id(page)
                            logger.info(f"Guardando ID de conversacion activa: {conv_id}")
                            
                            success, prev, new_acc = await rotate_account(page, ctx, target_email=best_target)
                            if success:
                                last_switch_time = time.time()
                                logger.info(f"Cambio de cuenta exitoso: {prev} -> {new_acc}")
                                
                                # Analytics & Toast Notifications
                                record_rotation_event(prev, new_acc)
                                new_st = get_effective_account_status(new_acc)
                                record_usage_sample(new_acc, new_st.get("five_hour_remaining_pct"), new_st.get("weekly_remaining_pct"))
                                notify_rotation_success(prev, new_acc, new_st.get("five_hour_remaining_pct"))
                                
                                if conv_id:
                                    logger.info(f"Reanudando tareas profundas en conversacion {conv_id}...")
                                    await asyncio.sleep(2.0)
                                    await navigate_to_conversation(page, conv_id)
                                    await resume_with_context(page)
                            else:
                                logger.error("Fallo la rotacion automatica de cuenta.")
                                
                await browser.close()
        except Exception as e:
            logger.error(f"Error en iteracion del monitor: {str(e)}")
            
        await asyncio.sleep(poll_interval_sec)

def main():
    parser = argparse.ArgumentParser(description="Antigravity Account Controller & Token Memory Monitor")
    parser.add_argument("--status", action="store_true", help="Muestra el reporte de memoria de tokens y cuotas")
    parser.add_argument("--switch-now", action="store_true", help="Ejecuta un cambio inmediato de cuenta manual")
    parser.add_argument("--switch-to", type=str, default=None, help="Ejecuta un cambio inmediato a una cuenta especifica")
    parser.add_argument("--daemon", action="store_true", help="Ejecuta el servicio de monitoreo en segundo plano")
    parser.add_argument("--interval", type=int, default=15, help="Intervalo de sondeo en segundos (defecto: 15)")
    parser.add_argument("--analytics", action="store_true", help="Muestra el reporte de burn-rate y analiticas")
    parser.add_argument("--health", action="store_true", help="Auditoria de salud de subsistemas (watchdog)")
    parser.add_argument("--notify-test", action="store_true", help="Envia una notificacion Windows Toast de prueba")
    
    args = parser.parse_args()
    
    if args.status:
        asyncio.run(check_status_cli())
    elif args.switch_to:
        asyncio.run(run_single_switch(target_email=args.switch_to))
    elif args.switch_now:
        asyncio.run(run_single_switch())
    elif args.daemon:
        asyncio.run(run_daemon_loop(poll_interval_sec=args.interval))
    elif args.analytics:
        mem = load_memory()
        try:
            from config_manager import get_authorized_emails
            default_email = get_authorized_emails()[0]
        except Exception:
            default_email = "primary.pro@gmail.com"
        active = mem.get("active_account", default_email)
        print(format_analytics_report(active))
    elif args.health:
        audit = run_health_audit()
        print(json.dumps(audit, indent=2, ensure_ascii=False))
    elif args.notify_test:
        send_windows_toast("🚀 Antigravity Test", "Notificacion Toast de prueba enviada con exito.")
        print("Notificacion enviada.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
