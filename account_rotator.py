"""
Account Rotator: Antigravity Google Account Switcher
Rotates seamlessly between configured Google AI accounts.
Automates Sign Out, Google OAuth selection in external browser, session verification, and task resumption.
"""

import os
import re
import time
import asyncio
import logging
from typing import Optional, Tuple
from playwright.async_api import Page, BrowserContext

from antigravity_bridge import (
    open_settings,
    close_settings,
    navigate_settings_tab,
    get_current_logged_in_email,
    get_active_conversation_id,
    ensure_active_page
)
from quota_detector import get_quota_limits
from external_oauth_handler import handle_external_google_signin
from task_resumer import resume_conversation_task

logger = logging.getLogger("AccountRotator")

# Capa 2 Safeguards: Total Token Safeguard & Task Protection
SAFEGUARD_PREVENT_DESTRUCTIVE_LOGOUT = True

# Authorized accounts dynamically resolved
try:
    from config_manager import get_authorized_emails
    AUTHORIZED_ACCOUNTS = set(get_authorized_emails())
except Exception:
    AUTHORIZED_ACCOUNTS = {
        "account1.pro@gmail.com",
        "account2.pro@gmail.com",
        "account3.pro@gmail.com",
        "account4.pro@gmail.com"
    }

def _emails_match(email_a: Optional[str], email_b: Optional[str]) -> bool:
    """Exact normalized comparison of two email addresses or their local usernames."""
    if not email_a or not email_b:
        return False
    a = email_a.strip().lower()
    b = email_b.strip().lower()
    if a == b:
        return True
    user_a = a.split("@")[0].strip()
    user_b = b.split("@")[0].strip()
    return bool(user_a and user_a == user_b)


def _log_tail_has_quota_error(log_file: str, max_bytes: int = 8192) -> bool:
    """Checks if the tail of language_server.log contains quota/capacity exhaustion errors."""
    try:
        size = os.path.getsize(log_file)
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            tail = f.read()
        patterns = (
            "MODEL_CAPACITY_EXHAUSTED",
            "RESOURCE_EXHAUSTED",
            "No capacity available",
            '"2010"',
            "Quota exceeded",
            "rateLimitExceeded"
        )
        tail_lower = tail.lower()
        return any(p.lower() in tail_lower for p in patterns)
    except Exception:
        return False


async def is_task_in_progress(page: Optional[Page] = None, is_exhausted: bool = False) -> Tuple[bool, str]:
    """
    Checks if active AI tasks or response streams are currently in progress in Antigravity.
    Guarantees that active tasks or subagent work are NEVER interrupted by account rotation.
    If is_exhausted=True, checks whether the stream is stalled/blocked due to quota exhaustion
    (e.g. language_server has stopped writing data or is logging quota errors) to avoid deadlock.
    """
    log_file = os.path.expandvars(r"%APPDATA%\Antigravity\logs\language_server.log")

    # 1. Chat DOM generation state check
    if page and not getattr(page, "is_closed", lambda: True)():
        try:
            state = await page.evaluate(r'''() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                const hasStop = buttons.some(b => {
                    const txt = (b.innerText || '').toLowerCase();
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    return txt.includes('stop generating') || txt.includes('detener') || (aria.includes('stop') && !aria.includes('settings'));
                });
                return { hasStop };
            }''')
            if state.get("hasStop"):
                if is_exhausted:
                    # If the log tail shows quota errors, the stream is deadlocked on quota exhaustion
                    if os.path.exists(log_file) and not _log_tail_has_quota_error(log_file):
                        try:
                            mtime = os.path.getmtime(log_file)
                            if (time.time() - mtime) < 1.5:
                                return True, "Transmisión de respuesta activa en curso antes del corte de cuota"
                        except Exception:
                            pass
                    return False, "Stream detenido por agotamiento de cuota"
                return True, "Generación activa de respuesta en curso en el chat"
        except Exception:
            pass

    # When quota is exhausted and no active generation stop-button is present (or page is None),
    # do NOT block rotation because language_server.log may be writing quota errors or heartbeats.
    if is_exhausted:
        return False, "Idle (quota exhausted)"

    # 2. language_server.log write activity check (within last 1.5s, excluding quota error spam)
    if os.path.exists(log_file):
        try:
            mtime = os.path.getmtime(log_file)
            if (time.time() - mtime) < 1.5 and not _log_tail_has_quota_error(log_file):
                return True, "Language Server escribiendo activamente transmisiones de datos"
        except Exception:
            pass

    return False, "Idle"

def safe_language_server_guard() -> bool:
    """
    Safety Guard: Guarantees language_server.exe is protected and NEVER terminated
    while tasks or subagents are in progress.
    """
    from watchdog_service import is_language_server_alive
    ls_alive = is_language_server_alive()
    if not ls_alive:
        logger.warning("[SAFEGUARD] language_server.exe no está en ejecución.")
        return False
    logger.info("[SAFEGUARD] language_server.exe verificado y protegido contra terminación forzada.")
    return True

async def rollback_to_functional_session(page: Optional[Page] = None, fallback_email: Optional[str] = None) -> bool:
    """
    Emergency Rollback Guard:
    If a rotation fails or is aborted and leaves Antigravity in an unauthenticated or
    inconsistent state, immediately rolls back to the known functional account.
    Guarantees Antigravity is NEVER left logged out or hanging on /onboarding.
    """
    if not fallback_email:
        try:
            from config_manager import get_authorized_emails
            fallback_email = get_authorized_emails()[0]
        except Exception:
            fallback_email = "atteelsidas@gmail.com"

    fallback_email = str(fallback_email).strip().lower()
    logger.warning(f"[ROLLBACK GUARD] Ejecutando rollback de emergencia hacia cuenta funcional: {fallback_email}...")

    # If page is missing or closed, handle safely
    if page is None or (hasattr(page, "is_closed") and page.is_closed()):
        logger.error("[ROLLBACK] Instancia de Page no proporcionada o cerrada. Imposible operar DOM de Antigravity.")
        return False

    try:
        if await is_authenticated_in_dom(page):
            curr = await get_current_logged_in_email(page, close_after=False)
            if curr:
                curr_lower = curr.lower().strip()
                try:
                    from config_manager import get_authorized_emails
                    valid_auths = [a.lower().strip() for a in get_authorized_emails()]
                except Exception:
                    valid_auths = [fallback_email]
                if _emails_match(fallback_email, curr_lower) or curr_lower in valid_auths:
                    logger.info(f"[ROLLBACK] Sesión ya activa y verificada con {curr}.")
                    return True

        from external_oauth_handler import capture_browser_hwnds, get_default_browser_info, handle_external_google_signin
        target_proc, _ = get_default_browser_info()
        pre_hwnds = capture_browser_hwnds(target_proc)

        triggered = await wait_for_and_click_sign_in(page, timeout_sec=8)
        if not triggered:
            logger.error("[ROLLBACK] No se pudo activar botón de inicio de sesión durante el rollback.")
            return False

        import threading
        auth_evt = threading.Event()
        loop = asyncio.get_running_loop()

        recovered = await loop.run_in_executor(
            None,
            lambda: handle_external_google_signin(
                fallback_email,
                timeout_sec=30,
                pre_hwnds=pre_hwnds,
                target_process=target_proc,
                auth_event=auth_evt
            )
        )
        auth_evt.set()

        for _ in range(50):
            if await is_authenticated_in_dom(page):
                logger.info(f"[ROLLBACK EXITOSO] Antigravity restaurado a cuenta funcional {fallback_email}.")
                return True
            await asyncio.sleep(0.1)

        return False
    except Exception as exc:
        logger.critical(f"[ROLLBACK ERROR] Excepción durante rollback de emergencia: {exc}")
        return False

def determine_target_account(current_email: str) -> str:
    """
    Determines the optimal target account among the other authorized accounts
    using token_memory evaluation (ranking by highest available tokens or earliest recharge).
    """
    norm = current_email.strip().lower()
    norm_user = norm.split("@")[0]
    from token_memory import evaluate_switch_readiness
    
    try:
        from config_manager import get_authorized_emails
        authorized = set(acc.lower().strip() for acc in get_authorized_emails())
    except Exception:
        authorized = set(acc.lower().strip() for acc in AUTHORIZED_ACCOUNTS)
        
    can_switch, reason, wait_secs, best_target = evaluate_switch_readiness(norm)
    if best_target and best_target.lower().strip() in authorized:
        return best_target
        
    # Deterministic fallback round-robin
    candidates = [
        acc for acc in authorized
        if acc.strip().lower() != norm and acc.split("@")[0].lower().strip() != norm_user
    ]
    if candidates:
        return sorted(list(candidates))[0]
        
    raise ValueError(
        f"Current email '{current_email}' is not in authorized list ({sorted(list(authorized))}). Aborting."
    )

async def programmatic_sign_out(page: Page) -> bool:
    """Attempts direct programmatic logout via React Fiber core.authService."""
    try:
        res = await page.evaluate(r'''async () => {
            let core = window.__antigravityCore;
            if (!core) {
                const candidates = document.querySelectorAll('div[id], div[class*="workbench"], main, #root, [data-testid], nav, aside');
                for (const el of candidates) {
                    const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
                    if (!key) continue;
                    let cur = el[key];
                    while (cur) {
                        if (cur.memoizedProps?.value?.core?.authService) {
                            core = cur.memoizedProps.value.core;
                            window.__antigravityCore = core;
                            break;
                        }
                        cur = cur.return;
                    }
                    if (core) break;
                }
            }
            if (core?.authService?.logout) {
                await core.authService.logout();
                return true;
            }
            return false;
        }''')
        return bool(res)
    except Exception as e:
        logger.debug(f"Programmatic sign out evaluation failed: {e}")
        return False

async def sign_out(page: Page, force_allow: bool = False) -> bool:
    """
    Executes Sign Out in Antigravity.
    SAFEGUARD GUARD: When SAFEGUARD_PREVENT_DESTRUCTIVE_LOGOUT is enabled,
    destructive sign-out is strictly blocked to prevent session destruction for running AIs.
    """
    if SAFEGUARD_PREVENT_DESTRUCTIVE_LOGOUT and not force_allow:
        logger.warning(
            "[SAFEGUARD TOTAL DE TOKENS] sign_out() destructivo interceptado y bloqueado. "
            "Antigravity preserva la sesión activa actual para garantizar la continuidad de otras IAs y subagentes."
        )
        return False

    logger.info("Executing Sign Out in Antigravity...")
    
    # Check if already in signed-out state
    if "/onboarding" in (page.url or ""):
        logger.info("Antigravity is already on /onboarding page. Sign out already complete.")
        return True
        
    entrance_btn = page.locator('.entrance-auth-panel button, button:has-text("Continue with Google")')
    if await entrance_btn.count() > 0 and await entrance_btn.first.is_visible():
        logger.info("Antigravity onboarding entrance is already visible. Sign out already complete.")
        return True

    # 1. Primary Engine: Fast Programmatic Logout
    if await programmatic_sign_out(page):
        logger.info("Programmatic logout dispatched. Verifying signed-out transition...")
        if not await is_authenticated_in_dom(page) or "/onboarding" in (page.url or ""):
            logger.info("Verified sign-out state via authService state machine immediately.")
            return True
        for _ in range(40):
            await asyncio.sleep(0.025)
            if not await is_authenticated_in_dom(page) or "/onboarding" in (page.url or ""):
                logger.info("Verified sign-out state via authService state machine.")
                return True
            if await entrance_btn.count() > 0 and await entrance_btn.first.is_visible():
                return True
        logger.warning("Programmatic logout dispatched but state did not flip within 1.0s; falling back to UI.")

    # 2. Fallback Engine: UI Dialog & Modal Handling
    dialog_sign_in = page.locator('div[role="dialog"] button:has-text("Sign In"), div[role="dialog"] button:has-text("Iniciar sesión")')
    if await dialog_sign_in.count() > 0 and await dialog_sign_in.first.is_visible():
        logger.info("Settings dialog is open and displays 'Sign In'. User is already signed out.")
        return True

    sign_out_btn = page.locator('div[role="dialog"] button:has-text("Sign Out"), div[role="dialog"] button:has-text("Cerrar sesión")')
    if await sign_out_btn.count() > 0 and await sign_out_btn.first.is_visible():
        logger.info("Sign Out button already visible in current dialog. Clicking...")
        await sign_out_btn.first.click(force=True)
    else:
        if not await navigate_settings_tab(page, "Account"):
            if await sign_out_btn.count() > 0 and await sign_out_btn.first.is_visible():
                await sign_out_btn.first.click(force=True)
            elif await dialog_sign_in.count() > 0 and await dialog_sign_in.first.is_visible():
                return True
            else:
                logger.error("Failed to navigate to Account settings tab.")
                return False
                
        await asyncio.sleep(0.4)
        sign_out_btn = page.locator('div[role="dialog"] button:has-text("Sign Out"), div[role="dialog"] button:has-text("Cerrar sesión")')
        if await sign_out_btn.count() > 0 and await sign_out_btn.first.is_visible():
            logger.info("Clicking Sign Out button in Account tab...")
            await sign_out_btn.first.click(force=True)
        else:
            if await dialog_sign_in.count() > 0 and await dialog_sign_in.first.is_visible():
                return True
            logger.error("Sign Out button not visible in Account settings.")
            return False

    # Wait for confirmation modal (prioritizing alertdialog over dialog)
    await asyncio.sleep(0.5)
    confirm_locators = [
        'div[role="alertdialog"] button:has-text("Sign Out")',
        'div[role="alertdialog"] button:has-text("Sign out")',
        'div[role="alertdialog"] button:has-text("Cerrar sesión")',
        'div[role="alertdialog"] button:has-text("Confirm")',
        'div[role="alertdialog"] button.bg-destructive',
        'div[role="dialog"]:not(:has(nav)) button:has-text("Sign Out")'
    ]
    for sel in confirm_locators:
        c_btn = page.locator(sel)
        if await c_btn.count() > 0 and await c_btn.first.is_visible():
            logger.info(f"Confirming Sign Out modal with selector: {sel}...")
            await c_btn.first.click(force=True)
            break

    # Verify sign out completed
    for _ in range(15):
        await asyncio.sleep(0.3)
        if "/onboarding" in (page.url or "") or not await is_authenticated_in_dom(page):
            logger.info("Sign out successfully verified.")
            return True
        if await entrance_btn.count() > 0 and await entrance_btn.first.is_visible():
            return True
            
    return True

async def _try_programmatic_login_redirect(page: Page) -> bool:
    """
    Exhaustively searches the React Fiber tree (upward return chain and downward child/sibling BFS)
    to locate core.authService and invoke loginWithRedirect({ isGcpTos: false }) without signing out.
    """
    try:
        triggered = await page.evaluate(r'''async () => {
            let core = window.__antigravityCore;
            const extractCore = (fiber) => {
                if (!fiber) return null;
                const c = fiber.memoizedProps?.value?.core || fiber.memoizedProps?.core || fiber.stateNode?.core;
                if (c?.authService) return c;
                return null;
            };

            if (!core || !core.authService) {
                const primary = document.querySelectorAll(
                    'div[role="dialog"] *, div[id], div[class*="workbench"], main, #root, [data-testid], nav, aside, button, header'
                );
                const nodes = primary.length > 0
                    ? Array.from(primary).slice(0, 400)
                    : Array.from(document.querySelectorAll('*')).slice(0, 500);

                for (const el of nodes) {
                    const key = Object.keys(el).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                    if (!key) continue;
                    let cur = el[key];
                    let depth = 0;
                    while (cur && depth < 120) {
                        const found = extractCore(cur);
                        if (found) {
                            core = found;
                            window.__antigravityCore = core;
                            break;
                        }
                        cur = cur.return;
                        depth++;
                    }
                    if (core?.authService) break;
                }
            }

            // Downward BFS from root fiber if upward walk did not find core
            if (!core || !core.authService) {
                const roots = document.querySelectorAll('#root, body > div, main');
                for (const r of roots) {
                    const key = Object.keys(r).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                    if (!key) continue;
                    const queue = [r[key]];
                    const visited = new Set();
                    let steps = 0;
                    while (queue.length > 0 && steps < 1500) {
                        const node = queue.shift();
                        if (!node || visited.has(node)) continue;
                        visited.add(node);
                        steps++;
                        const found = extractCore(node);
                        if (found) {
                            core = found;
                            window.__antigravityCore = core;
                            break;
                        }
                        if (node.child) queue.push(node.child);
                        if (node.sibling) queue.push(node.sibling);
                    }
                    if (core?.authService) break;
                }
            }

            if (core?.authService?.loginWithRedirect) {
                core.authService.loginWithRedirect({ isGcpTos: false }).catch(() => {});
                return true;
            }
            if (typeof core?.authService?.showLoginFlow === 'function') {
                core.authService.showLoginFlow().catch?.(() => {});
                return true;
            }
            if (typeof core?.authService?.login === 'function') {
                core.authService.login({ isGcpTos: false }).catch?.(() => {});
                return true;
            }
            if (typeof core?.authService?._lsClient?.loginWithBrowser === 'function') {
                core.authService._lsClient.loginWithBrowser({ isGcpTos: false }).catch?.(() => {});
                return true;
            }
            return false;
        }''')
        return bool(triggered)
    except Exception as e:
        logger.debug(f"Direct programmatic login trigger failed: {e}")
        return False


async def wait_for_and_click_sign_in(page: Page, timeout_sec: int = 15) -> bool:
    """
    Triggers Google Sign-In with zero-delay programmatic acceleration:
    1. Primary: Direct invocation of core.authService.loginWithRedirect({ isGcpTos: false }).
    2. Secondary: Mount Account Settings dialog to expose authService in Fiber tree and retry loginWithRedirect.
    3. Fallback: Fast UI interaction on /onboarding or Settings dialog.
    """
    logger.info("Triggering Google Sign-In flow...")

    # 1. Primary: Fast programmatic trigger
    if await _try_programmatic_login_redirect(page):
        logger.info("Direct core.authService.loginWithRedirect triggered successfully!")
        return True

    # 2. Secondary: If not on /onboarding, open Account Settings tab briefly so React mounts the Account fiber node
    if "/onboarding" not in (page.url or ""):
        try:
            if await navigate_settings_tab(page, "Account"):
                await asyncio.sleep(0.25)
                if await _try_programmatic_login_redirect(page):
                    logger.info("core.authService.loginWithRedirect triggered after mounting Account Settings tab!")
                    await close_settings(page)
                    return True
        except Exception as e:
            logger.debug(f"Account tab mount fallback for loginWithRedirect failed: {e}")

    # Fallback UI polling
    start = time.time()
    while time.time() - start < timeout_sec:
        # Check if settings dialog is open; if it has Sign In, click it, else close it so it doesn't obstruct /onboarding
        dialog = page.locator('div[role="dialog"]')
        if await dialog.count() > 0 and await dialog.first.is_visible():
            settings_sign_in = page.locator('div[role="dialog"] button:has-text("Sign In"), div[role="dialog"] button:has-text("Iniciar sesión")')
            if await settings_sign_in.count() > 0 and await settings_sign_in.first.is_visible():
                logger.info("Found 'Sign In' button in Settings dialog. Clicking...")
                await settings_sign_in.first.click(force=True)
                await asyncio.sleep(0.5)
                return True
            else:
                # Close settings to uncover onboarding screen
                await close_settings(page)
                await asyncio.sleep(0.3)

        # Check for 'Continue with Google' button on onboarding page
        onboarding_btn = page.locator(
            'button:has-text("Continue with Google"), '
            'button[title="Continue with Google"], '
            '.entrance-auth-panel button'
        )
        if await onboarding_btn.count() > 0 and await onboarding_btn.first.is_visible():
            logger.info("Found 'Continue with Google' button. Clicking...")
            await onboarding_btn.first.click(force=True)
            return True
            
        # General selectors fallback
        for sel in [
            'button:has-text("Sign in with Google")',
            'button:has-text("Iniciar sesión con Google")',
            'button:has-text("Sign in")',
            'button:has-text("Iniciar sesión")',
            '[data-testid="sign-in-button"]'
        ]:
            btn = page.locator(sel)
            if await btn.count() > 0 and await btn.first.is_visible():
                logger.info(f"Found sign-in button with selector: {sel}. Clicking...")
                await btn.first.click(force=True)
                return True
                
        await asyncio.sleep(0.4)

    logger.warning("Sign in button did not appear within timeout.")
    return False

async def is_authenticated_in_dom(page: Page) -> bool:
    """Checks whether the application core authService state is 'signedIn'."""
    try:
        state = await page.evaluate(r'''() => {
            let core = window.__antigravityCore;
            if (!core) {
                const primary = document.querySelectorAll('div[id], div[class*="workbench"], main, #root, [data-testid], nav, aside, button, header');
                const candidates = primary.length > 0 ? Array.from(primary) : Array.from(document.querySelectorAll('*')).slice(0, 300);
                for (const el of candidates) {
                    const key = Object.keys(el).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                    if (!key) continue;
                    let cur = el[key];
                    let depth = 0;
                    while (cur && depth < 100) {
                        const c = cur.memoizedProps?.value?.core || cur.memoizedProps?.core || cur.stateNode?.core;
                        if (c?.authService) {
                            core = c;
                            window.__antigravityCore = core;
                            break;
                        }
                        cur = cur.return;
                        depth++;
                    }
                    if (core) break;
                }
            }
            if (core?.authService) {
                const s1 = core.authService.authStateProvider?.getState?.()?.state;
                if (s1) return s1;
                const s2 = core.authService._authActor?.getSnapshot?.()?.value;
                if (s2) return s2;
            }
            return null;
        }''')
        return state == "signedIn"
    except Exception:
        return False

async def rotate_account(
    page: Page,
    context: Optional[BrowserContext] = None,
    target_email: Optional[str] = None,
    auto_prompt: bool = False,
    conv_id: Optional[str] = None,
    force: bool = False,
    is_exhaustion_switch: bool = False
) -> Tuple[bool, str, str]:
    """
    Full rotation pipeline:
    1. Detects current active email and captures active conversation ID.
    2. Validates it is in AUTHORIZED_ACCOUNTS.
    3. Determines next target email (or uses explicitly specified target_email).
    4. Triggers seamless in-place re-authentication (RE_SIGN_IN) without dropping tokens for subagents.
    5. Completes Google OAuth in default browser with calibrated row selection and closes auth tab.
    6. Verifies new logged in email in Antigravity.
    7. Updates token memory with new account quota.
    8. Restores active conversation without intrusive prompts unless auto_prompt=True.
    """
    logger.info("Starting automated account rotation...")

    # 0. Active Task Safeguard: verify no active AI tasks or generation streams in progress
    if not force:
        task_busy, busy_desc = await is_task_in_progress(page, is_exhausted=is_exhaustion_switch)
        if task_busy:
            if is_exhaustion_switch:
                from goal_resumer import clear_hung_generation
                await clear_hung_generation(page)
                logger.info("[SAFEGUARD] Stream interrumpido por agotamiento de cuota cancelado limpiamente. Continuando con rotación...")
            else:
                logger.warning(f"[SAFEGUARD] Tarea activa en curso detectada ({busy_desc}). Rotación pospuesta para no interrumpir el trabajo de la IA.")
                current_email = await get_current_logged_in_email(page, close_after=False) or "unknown"
                return False, current_email, current_email
    else:
        logger.info("[FORCE] Rotación forzada autorizada. Omitiendo comprobación de tarea activa.")

    # 1. Capture active conversation for resumption later (with persistent disk backup)
    active_conv_id = conv_id or await get_active_conversation_id(page)
    if not active_conv_id:
        try:
            from token_memory import load_memory
            active_conv_id = load_memory().get("last_active_conversation_id")
        except Exception:
            pass
    if active_conv_id:
        try:
            from token_memory import load_memory, save_memory
            mem = load_memory()
            mem["last_active_conversation_id"] = active_conv_id
            save_memory(mem)
        except Exception:
            pass
    logger.info(f"Active conversation ID: {active_conv_id}")
    
    # 2. Detect current email
    current_email = await get_current_logged_in_email(page)
    if not current_email:
        await close_settings(page)
        await asyncio.sleep(0.5)
        current_email = await get_current_logged_in_email(page)
        
    if not current_email:
        # Fallback to token memory
        from token_memory import load_memory
        current_email = load_memory().get("active_account")
        
    if not current_email:
        raise RuntimeError("Could not detect currently logged in email in Antigravity.")
        
    logger.info(f"Current logged in account: {current_email}")
    if target_email and target_email.strip().lower() in AUTHORIZED_ACCOUNTS:
        chosen_target = target_email.strip().lower()
        logger.info(f"Using explicitly requested target account: {chosen_target}")
    else:
        chosen_target = determine_target_account(current_email)
        logger.info(f"Determined target account: {chosen_target}")
    target_email = chosen_target
    
    # 3. Trigger Sign In flow with Pre-Click HWND Snapshot
    from external_oauth_handler import capture_browser_hwnds, get_default_browser_info
    target_proc, _ = get_default_browser_info()
    pre_hwnds = capture_browser_hwnds(target_proc)
    logger.info(f"Captured {len(pre_hwnds)} pre-existing {target_proc} window(s) before sign-in trigger.")

    is_already_onboarding = "/onboarding" in page.url or (await page.locator('.entrance-auth-panel button, button:has-text("Continue with Google")').count() > 0)
    login_triggered = False

    if not is_already_onboarding:
        # Seamless In-Place Re-Authentication (RE_SIGN_IN):
        # Keeps active session token alive until OAuth completes, preventing
        # "You are not logged into Antigravity" crashes in background subagents.
        logger.info("Attempting seamless in-place re-authentication (RE_SIGN_IN)...")
        login_triggered = await wait_for_and_click_sign_in(page, timeout_sec=5)

    if not login_triggered:
        if not is_already_onboarding:
            # TOTAL TOKEN SAFEGUARD: Never call destructive sign_out() when active!
            logger.warning("[SAFEGUARD TOTAL DE TOKENS] No se pudo activar loginWithRedirect sin cerrar sesión. Abortando rotación para proteger la sesión activa de subagentes.")
            return False, current_email, current_email

        if not await wait_for_and_click_sign_in(page, timeout_sec=15):
            await close_settings(page)
            await asyncio.sleep(0.5)
            if not await wait_for_and_click_sign_in(page, timeout_sec=10):
                logger.error("[EMERGENCY] No se pudo iniciar login en pantalla de onboarding. Activando rollback...")
                await rollback_to_functional_session(page, current_email)
                raise RuntimeError("Could not trigger Google Sign In button.")
            
    # 4. Handle external Google OAuth in default browser with isolation and real-time sync
    logger.info(f"Handling external Google OAuth in {target_proc} for {target_email}...")
    import threading
    auth_event = threading.Event()

    async def poll_auth_success():
        poll_start = time.time()
        while not auth_event.is_set() and (time.time() - poll_start) < 300.0:
            try:
                if is_already_onboarding:
                    if await is_authenticated_in_dom(page):
                        auth_event.set()
                        logger.info("[AUTH-SYNC] Autenticación detectada en Antigravity DOM tras onboarding.")
                        break
                else:
                    # In RE_SIGN_IN mode, we were already signed in to current_email.
                    # ONLY fire if the session context has flipped to target_email or away from current_email!
                    live_email = await page.evaluate(r'''async () => {
                        let core = window.__antigravityCore;
                        if (!core) {
                            const candidates = document.querySelectorAll('div[id], div[class*="workbench"], main, #root, [data-testid], nav, aside');
                            for (const el of candidates) {
                                const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
                                if (!key) continue;
                                let cur = el[key];
                                while (cur) {
                                    if (cur.memoizedProps?.value?.core?.authService) {
                                        core = cur.memoizedProps.value.core;
                                        window.__antigravityCore = core;
                                        break;
                                    }
                                    cur = cur.return;
                                }
                                if (core) break;
                            }
                        }
                        if (core?.authService?._lsClient?.getUserStatus) {
                            try {
                                const st = await core.authService._lsClient.getUserStatus({});
                                if (st?.userStatus?.email) return st.userStatus.email;
                            } catch (e) {}
                        }
                        try {
                            const ctx = core?.authService?.authStateProvider?.getState?.()?.context;
                            if (ctx?.userEmail) return ctx.userEmail;
                        } catch (e) {}
                        return null;
                    }''')
                    if live_email:
                        live_lower = live_email.lower().strip()
                        if _emails_match(target_email, live_lower) or not _emails_match(current_email, live_lower):
                            auth_event.set()
                            logger.info(f"[AUTH-SYNC] Cambio a cuenta objetivo ({live_email}) detectado en tiempo real.")
                            break
            except Exception:
                pass
            await asyncio.sleep(0.05)

    poll_task = asyncio.create_task(poll_auth_success())

    loop = asyncio.get_running_loop()
    oauth_handled = await loop.run_in_executor(
        None,
        lambda: handle_external_google_signin(
            target_email,
            timeout_sec=35,
            pre_hwnds=pre_hwnds,
            target_process=target_proc,
            auth_event=auth_event
        )
    )
    auth_event.set()
    await poll_task

    if not oauth_handled and not await is_authenticated_in_dom(page):
        logger.warning("External OAuth handler did not confirm success; checking Antigravity state...")
        
    # 6. Wait for Antigravity workbench to re-authenticate (fast polling with living page guard)
    logger.info("Waiting for Antigravity workbench to confirm signedIn state...")
    authenticated = False
    browser = getattr(getattr(page, "context", None), "browser", None)

    for _ in range(60):  # Wait up to 30 seconds for initial signedIn state
        if browser and browser.is_connected():
            try:
                page = await ensure_active_page(browser, page)
            except Exception:
                pass
        if await is_authenticated_in_dom(page):
            authenticated = True
            break
        await asyncio.sleep(0.5)
        
    await asyncio.sleep(0.2)
    
    # 7. Verify new account email (patient polling up to 35s, with allow_memory_fallback=False)
    new_email = None
    logger.info(f"Verificando confirmación de nueva cuenta (objetivo: {target_email})...")
    verify_start = time.time()
    
    for verify_round in range(70):  # 70 * 0.5s = 35 seconds max
        if browser and browser.is_connected():
            try:
                page = await ensure_active_page(browser, page)
            except Exception:
                pass
        try:
            # allow_memory_fallback=False prevents reading old account from disk memory
            detected = await get_current_logged_in_email(page, close_after=False, allow_memory_fallback=False)
            if detected:
                det_lower = detected.lower().strip()
                if _emails_match(target_email, det_lower) or not _emails_match(current_email, det_lower):
                    new_email = det_lower
                    elapsed = time.time() - verify_start
                    logger.info(f"[AUTH-VERIFIED] Nueva cuenta confirmada ({new_email}) en {elapsed:.1f}s.")
                    break
        except Exception:
            pass
        await asyncio.sleep(0.5)
        
    await close_settings(page)
    effective_new = new_email or target_email
    
    rotated_ok = bool(new_email and (_emails_match(target_email, new_email) or not _emails_match(current_email, new_email)))
    if rotated_ok:
        logger.info(f"Successfully rotated and verified account: {new_email}!")
    else:
        logger.warning(f"Rotation verification failed for target {target_email}. Checking session integrity...")
        if await is_authenticated_in_dom(page):
            logger.info(f"[SAFEGUARD] Sesión funcional preservada ({current_email}). No se perdió acceso a la cuenta.")
            return False, current_email, current_email
        else:
            logger.critical(f"[EMERGENCY ROLLBACK] Sesión desautenticada tras intento de rotación. Ejecutando rollback a {current_email}...")
            rb_ok = await rollback_to_functional_session(page, current_email)
            if rb_ok:
                logger.info(f"[ROLLBACK COMPLETADO] Sesión restaurada con éxito a {current_email}.")
                return False, current_email, current_email
            else:
                logger.critical(f"[ROLLBACK FALLIDO] No se pudo restaurar la sesión a {current_email}.")
                return False, current_email, "UNAUTHENTICATED"
        
    # 8. Sample and update token memory for the newly active account
    try:
        logger.info(f"Sampling quota snapshot for newly active account {effective_new}...")
        limits = await get_quota_limits(page, known_email=effective_new)
        logger.info(f"New account quota: 5h={limits.get('five_hour_remaining_pct')}%, Weekly={limits.get('weekly_remaining_pct')}%")
    except Exception as e:
        logger.warning(f"Could not sample quota after rotation: {e}")
        
    # 9. Resume paused task in active conversation
    try:
        logger.info(f"Resuming active conversation task (auto_prompt={auto_prompt})...")
        await resume_conversation_task(page, active_conv_id, auto_prompt=auto_prompt)
    except Exception as e:
        logger.warning(f"Failed to resume task after rotation: {e}")
        
    return True, current_email, effective_new
