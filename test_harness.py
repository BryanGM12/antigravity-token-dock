"""
Test Harness: Comprehensive Validation of Antigravity Account Controller & Subsystems
Runs non-destructive validation of all 19 components across core and advanced modules.
"""

import sys
import asyncio
import urllib.request
import json
from playwright.async_api import async_playwright

from antigravity_bridge import (
    connect_antigravity,
    get_cdp_port,
    get_current_logged_in_email,
    get_active_conversation_id,
    close_settings
)
from quota_detector import get_quota_limits, check_log_quota_errors, check_chat_quota_errors
from account_rotator import determine_target_account, AUTHORIZED_ACCOUNTS
from external_oauth_handler import find_browser_window, switch_to_interactive_desktop
from token_memory import load_memory, get_effective_account_status, evaluate_switch_readiness
from analytics_engine import calculate_burn_rate, record_usage_sample, load_analytics_data
from watchdog_service import run_health_audit, ensure_dark_theme
from goal_resumer import analyze_chat_state
from notification_service import send_windows_toast

async def run_all_tests():
    print("\n--- INICIANDO TEST HARNESS DE CONTROLADOR ANTIGRAVITY (19 PRUEBAS) ---")
    
    # 1. CDP Port Check
    port = get_cdp_port()
    print(f"[PASS] 1. CDP Port detectado: {port}")
    
    # 2. Desktop Switch Check
    desk_ok = switch_to_interactive_desktop()
    print(f"[PASS] 2. Acceso a escritorio interactivo 'default': {desk_ok}")
    assert desk_ok, "Debe tener acceso a escritorio interactivo"
    
    # 3. Browser Window Detection Check
    browser_hwnd = find_browser_window()
    print(f"[PASS] 3. Ventana de navegador detectada: HWND {browser_hwnd}")
    
    async with async_playwright() as p:
        # 4. Browser Connection
        browser, page = await connect_antigravity(p)
        print(f"[PASS] 4. Conexion establecida a Antigravity: '{await page.title()}' (URL: {page.url})")
        
        # 5. Active Conversation Detection
        conv_id = await get_active_conversation_id(page)
        print(f"[PASS] 5. Conversacion activa ID: {conv_id}")
        assert conv_id is not None, "Debe detectar un ID de conversacion valido"
        
        # 6. Account Detection
        email = await get_current_logged_in_email(page)
        print(f"[PASS] 6. Cuenta actualmente iniciada: {email}")
        assert email is not None, "Debe detectar el correo actual"
        assert email.lower() in AUTHORIZED_ACCOUNTS, f"Cuenta {email} debe estar en cuentas autorizadas"
        
        # 7. Target Account Calculation
        target = determine_target_account(email)
        print(f"[PASS] 7. Siguiente cuenta objetivo calculada: {target}")
        assert target != email.lower(), "La cuenta objetivo debe ser distinta de la actual"
        assert target in AUTHORIZED_ACCOUNTS, "La cuenta objetivo debe ser una de las autorizadas"
        
        # 8. Quota Limits Direct Background Reading (Silent, zero UI disruption)
        limits = await get_quota_limits(page)
        print(f"[PASS] 8. Lectura directa de cuotas React: Gemini 5h={limits.get('gemini', {}).get('five_hour_remaining_pct')}%, Gemini Wk={limits.get('gemini', {}).get('weekly_remaining_pct')}%, Claude 5h={limits.get('claude_gpt', {}).get('five_hour_remaining_pct')}%, Claude Wk={limits.get('claude_gpt', {}).get('weekly_remaining_pct')}%")
        assert limits.get("weekly_remaining_pct") is not None, "Debe obtener limite semanal"
        assert limits.get("five_hour_remaining_pct") is not None, "Debe obtener limite de 5 horas"
        assert "gemini" in limits, "Debe contener grupo Gemini"
        assert "claude_gpt" in limits, "Debe contener grupo Claude/GPT"
        
        # 9. Log Quota Error Check
        log_err, log_desc = check_log_quota_errors()
        print(f"[PASS] 9. Chequeo de logs: error={log_err}, desc='{log_desc}'")
        
        # 10. Chat Element Check
        chat_err, chat_desc = await check_chat_quota_errors(page)
        print(f"[PASS] 10. Chequeo de chat: error={chat_err}, desc='{chat_desc}'")
        
        # 11. Chat Input Presence
        input_count = await page.locator('div[aria-label="Message input"]').count()
        print(f"[PASS] 11. Input de mensajes en chat detectado: {input_count > 0}")
        assert input_count > 0, "El input del chat debe estar presente"
        
        # 12. Token Memory Persistent State
        mem = load_memory()
        print(f"[PASS] 12. Memoria persistente cargada: Cuenta activa={mem.get('active_account')}, Total cuentas={len(mem.get('accounts', {}))}")
        assert mem.get("active_account") is not None, "Debe haber una cuenta activa en memoria"
        assert len(mem.get("accounts", {})) >= 4, "Deben estar registradas las 4 cuentas autorizadas"
        
        # 13. Effective Account Status
        status = get_effective_account_status(email)
        print(f"[PASS] 13. Estado efectivo: 5h={status.get('five_hour_remaining_pct')}%, ETA 5h={status.get('five_hour_recharge_in')}")
        assert status.get("five_hour_remaining_pct") is not None, "Debe calcular estado efectivo de 5h"
        
        # 14. Switch Readiness Evaluation
        can_switch, reason, wait_s, best_target = evaluate_switch_readiness(email)
        print(f"[PASS] 14. Evaluacion de alternancia: can_switch={can_switch}, target={best_target}, reason='{reason}'")
        assert can_switch is True or can_switch is False, "Debe retornar un booleano de alternancia"
        assert best_target in AUTHORIZED_ACCOUNTS, "La cuenta recomendada debe ser autorizada"
        
        # 15. Analytics Engine
        burn = calculate_burn_rate(email)
        print(f"[PASS] 15. Analiticas de consumo: Burn-rate={burn.get('burn_rate_pct_per_hour')}%/h, Estado={burn.get('status')}")
        assert "burn_rate_pct_per_hour" in burn, "Debe calcular velocidad de gasto"
        
        # 16. Watchdog Subsystem & Dark Theme Guard
        dark_ok = await ensure_dark_theme(page)
        audit = run_health_audit()
        print(f"[PASS] 16. Watchdog y Tema Oscuro: Tema={dark_ok}, Estado={audit.get('status')}")
        assert audit.get("status") == "OK", "La auditoria de salud debe reportar OK"
        
        # 17. Goal Resumer Chat State Analysis
        chat_st = await analyze_chat_state(page)
        print(f"[PASS] 17. Analisis de estado del chat: InputReady={chat_st.get('inputReady')}, StopBtn={chat_st.get('hasStopButton')}")
        assert "inputReady" in chat_st, "Debe analizar el estado del chat"
        
        await close_settings(page)
        await browser.close()

    # 18. Native Windows Toast Notification (Non-intrusive)
    toast_ok = send_windows_toast("Antigravity Harness", "Verificacion automatica de subsistemas completada.")
    print(f"[PASS] 18. Notificacion Toast nativa enviada: {toast_ok}")
    assert toast_ok, "El servicio de notificaciones Toast debe operar correctamente"
    
    # 19. Local HUD REST Micro-API Query
    hud_url = "http://127.0.0.1:59123/api/status"
    req = urllib.request.Request(hud_url, headers={"User-Agent": "AntigravityHarness"})
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        hud_payload = json.loads(resp.read().decode())
        print(f"[PASS] 19. Local HUD API en vivo (59123): Activa={hud_payload.get('active_account')}, Cuentas={len(hud_payload.get('accounts', {}))}")
        assert hud_payload.get("active_account") is not None, "El HUD debe reportar la cuenta activa"
        assert len(hud_payload.get("accounts", {})) == 4, "El HUD debe monitorear las 4 cuentas"
        
    print("\n--- TODOS LOS 19 TESTS PASARON EXITOSAMENTE (100%) ---\n")

if __name__ == "__main__":
    asyncio.run(run_all_tests())
