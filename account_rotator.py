"""
Account Rotator: Antigravity Google Account Switcher
Rotates seamlessly between configured Google AI accounts.
Automates Sign Out, Google OAuth selection in external browser, session verification, and task resumption.
"""

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

async def sign_out(page: Page) -> bool:
    """
    Executes Sign Out in Antigravity using dual-engine architecture:
    1. Primary: Direct programmatic core.authService.logout() with active state verification.
    2. Fallback: Calibrated DOM navigation with alertdialog priority and strict mode safety.
    """
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

async def wait_for_and_click_sign_in(page: Page, timeout_sec: int = 15) -> bool:
    """
    Triggers Google Sign-In with zero-delay programmatic acceleration:
    1. Primary: Direct invocation of core.authService.loginWithRedirect({ isGcpTos: false }).
    2. Fallback: Fast UI interaction on /onboarding or Settings dialog.
    """
    logger.info("Triggering Google Sign-In flow...")

    # Primary: Fast programmatic trigger
    try:
        triggered = await page.evaluate(r'''async () => {
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
            if (core?.authService?.loginWithRedirect) {
                // Trigger OAuth flow asynchronously without awaiting the Promise,
                // so Python immediately proceeds to handle external browser OAuth.
                core.authService.loginWithRedirect({ isGcpTos: false }).catch(() => {});
                return true;
            }
            return false;
        }''')
        if triggered:
            logger.info("Direct core.authService.loginWithRedirect triggered successfully!")
            return True
    except Exception as e:
        logger.debug(f"Direct programmatic login trigger failed: {e}")

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

async def rotate_account(page: Page, context: Optional[BrowserContext] = None, target_email: Optional[str] = None, auto_prompt: bool = False, conv_id: Optional[str] = None) -> Tuple[bool, str, str]:
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
        login_triggered = await wait_for_and_click_sign_in(page, timeout_sec=4)

    if not login_triggered:
        if not is_already_onboarding:
            logger.info("Falling back to full sign-out sequence...")
            if not await sign_out(page):
                if "/onboarding" in page.url or (await page.locator('.entrance-auth-panel button').count() > 0):
                    logger.info("Sign out transition led to onboarding state. Proceeding.")
                else:
                    raise RuntimeError("Failed to execute Sign Out in Antigravity.")

        if not await wait_for_and_click_sign_in(page, timeout_sec=15):
            await close_settings(page)
            await asyncio.sleep(0.5)
            if not await wait_for_and_click_sign_in(page, timeout_sec=10):
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
                    live_email = await page.evaluate(r'''() => {
                        let core = window.__antigravityCore;
                        if (!core?.authService) return null;
                        try {
                            const st = core.authService.authStateProvider?.getState?.();
                            if (st?.state === "signedIn") {
                                return st?.context?.userEmail || null;
                            }
                        } catch (e) {}
                        return null;
                    }''')
                    if live_email:
                        live_lower = live_email.lower().strip()
                        target_prefix = target_email.split("@")[0].lower()
                        current_prefix = current_email.split("@")[0].lower()
                        if target_prefix in live_lower or (live_lower != current_email.lower() and current_prefix not in live_lower):
                            auth_event.set()
                            logger.info(f"[AUTH-SYNC] Cambio a cuenta objetivo ({live_email}) detectado en tiempo real.")
                            break
            except Exception:
                pass
            await asyncio.sleep(0.04)

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

    for _ in range(50):
        if browser and browser.is_connected():
            try:
                page = await ensure_active_page(browser, page)
            except Exception:
                pass
        if await is_authenticated_in_dom(page):
            authenticated = True
            break
        await asyncio.sleep(0.04)
        
    await asyncio.sleep(0.05)
    
    # 7. Verify new account email (fast polling)
    new_email = None
    for _ in range(25):
        if browser and browser.is_connected():
            try:
                page = await ensure_active_page(browser, page)
            except Exception:
                pass
        try:
            new_email = await get_current_logged_in_email(page, close_after=False)
            if new_email and target_email.split("@")[0].lower() in new_email.lower():
                break
        except Exception:
            pass
        await asyncio.sleep(0.05)
        
    await close_settings(page)
    effective_new = new_email or target_email
    
    rotated_ok = bool(new_email and (target_email.split("@")[0].lower() in new_email.lower() or new_email.lower() != current_email.lower()))
    if rotated_ok:
        logger.info(f"Successfully rotated and verified account: {new_email}!")
    else:
        logger.error(f"Rotation verification failed. Active email remains: {new_email or effective_new} (Expected: {target_email})")
        return False, current_email, effective_new
        
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
