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
    get_active_conversation_id
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
    from token_memory import evaluate_switch_readiness
    
    can_switch, reason, wait_secs, best_target = evaluate_switch_readiness(norm)
    if best_target and best_target.lower() in AUTHORIZED_ACCOUNTS:
        return best_target
        
    # Deterministic fallback round-robin
    candidates = [acc for acc in AUTHORIZED_ACCOUNTS if acc.split("@")[0].lower() not in norm]
    if candidates:
        return sorted(list(candidates))[0]
        
    raise ValueError(
        f"Current email '{current_email}' is not in authorized list ({sorted(list(AUTHORIZED_ACCOUNTS))}). Aborting."
    )

async def sign_out(page: Page) -> bool:
    """Navigates to Account settings and executes Sign Out."""
    logger.info("Opening Account settings to sign out...")
    if not await navigate_settings_tab(page, "Account"):
        logger.error("Failed to navigate to Account settings tab.")
        return False
        
    await asyncio.sleep(0.5)
    
    # Locate Sign Out button
    sign_out_btn = page.locator('button:has-text("Sign Out"), button:has-text("Cerrar sesión")')
    if await sign_out_btn.count() == 0:
        logger.error("Sign Out button not found in Account settings.")
        return False
        
    logger.info("Clicking Sign Out button...")
    await sign_out_btn.first.click()
    await asyncio.sleep(1.0)
    
    # Check if a confirmation modal appeared
    confirm_btn = page.locator(
        'div[role="dialog"] button:has-text("Sign Out"), '
        'div[role="dialog"] button:has-text("Cerrar"), '
        'div[role="alertdialog"] button:has-text("Sign Out")'
    )
    if await confirm_btn.count() > 0:
        logger.info("Confirming Sign Out modal...")
        await confirm_btn.first.click()
        await asyncio.sleep(1.0)
        
    return True

async def wait_for_and_click_sign_in(page: Page, timeout_sec: int = 15) -> bool:
    """
    Triggers Google Sign-In:
    1. If Settings dialog has 'Sign In' button, clicks it (which navigates to /onboarding?login=true).
    2. On /onboarding, clicks 'Continue with Google' (.entrance-auth-panel button).
    3. Programmatic fallback invokes core.authService.loginWithRedirect({isGcpTos: false}) directly.
    """
    logger.info("Waiting for sign-in controls to initiate Google OAuth...")
    start = time.time()
    
    while time.time() - start < timeout_sec:
        # Check if Settings dialog has 'Sign In' button
        settings_sign_in = page.locator('div[role="dialog"] button:has-text("Sign In"), div[role="dialog"] button:has-text("Iniciar sesión")')
        if await settings_sign_in.count() > 0 and await settings_sign_in.first.is_visible():
            logger.info("Found 'Sign In' button in Settings dialog. Clicking...")
            await settings_sign_in.first.click()
            await asyncio.sleep(1.0)
            
        # Check for 'Continue with Google' button on onboarding page
        onboarding_btn = page.locator(
            'button:has-text("Continue with Google"), '
            'button[title="Continue with Google"], '
            '.entrance-auth-panel button'
        )
        if await onboarding_btn.count() > 0 and await onboarding_btn.first.is_visible():
            logger.info("Found 'Continue with Google' button. Clicking...")
            await onboarding_btn.first.click()
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
                await btn.first.click()
                return True
                
        await asyncio.sleep(0.5)
        
    # Programmatic fallback via core.authService
    logger.info("Attempting programmatic authService.loginWithRedirect fallback...")
    try:
        res = await page.evaluate(r'''async () => {
            const allEls = document.querySelectorAll('*');
            for (const el of allEls) {
                const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
                if (!key) continue;
                let cur = el[key];
                while (cur) {
                    if (cur.memoizedProps?.value?.core?.authService) {
                        const auth = cur.memoizedProps.value.core.authService;
                        await auth.loginWithRedirect({ isGcpTos: false });
                        return true;
                    }
                    cur = cur.return;
                }
            }
            return false;
        }''')
        if res:
            logger.info("Programmatic authService.loginWithRedirect dispatched successfully!")
            return True
    except Exception as e:
        logger.warning(f"Programmatic login fallback failed: {e}")
        
    logger.warning("Sign in button did not appear within timeout.")
    return False

async def is_authenticated_in_dom(page: Page) -> bool:
    """Checks whether the application core authService state is 'signedIn'."""
    try:
        state = await page.evaluate(r'''() => {
            const allEls = document.querySelectorAll('*');
            for (const el of allEls) {
                const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
                if (!key) continue;
                let cur = el[key];
                while (cur) {
                    if (cur.memoizedProps?.value?.core?.authService) {
                        const auth = cur.memoizedProps.value.core.authService;
                        return auth?.authStateProvider?.getState?.()?.state;
                    }
                    cur = cur.return;
                }
            }
            return null;
        }''')
        return state == "signedIn"
    except Exception:
        return False

async def rotate_account(page: Page, context: Optional[BrowserContext] = None, target_email: Optional[str] = None, auto_prompt: bool = False) -> Tuple[bool, str, str]:
    """
    Full rotation pipeline:
    1. Detects current active email and captures active conversation ID.
    2. Validates it is in AUTHORIZED_ACCOUNTS.
    3. Determines next target email (or uses explicitly specified target_email).
    4. Clicks Sign Out.
    5. Clicks Sign In / Continue with Google.
    6. Completes Google OAuth in Comet with calibrated row selection and closes Comet tab.
    7. Verifies new logged in email in Antigravity.
    8. Updates token memory with new account quota.
    9. Restores active conversation without intrusive prompts unless auto_prompt=True.
    """
    logger.info("Starting automated account rotation...")
    
    # 1. Capture active conversation for resumption later
    active_conv_id = await get_active_conversation_id(page)
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
    
    # 3. Sign Out
    if not await sign_out(page):
        raise RuntimeError("Failed to execute Sign Out in Antigravity.")
        
    await asyncio.sleep(1.2)
    
    # 4. Trigger Sign In flow
    if not await wait_for_and_click_sign_in(page, timeout_sec=15):
        await close_settings(page)
        await asyncio.sleep(0.5)
        if not await wait_for_and_click_sign_in(page, timeout_sec=10):
            raise RuntimeError("Could not trigger Google Sign In button.")
            
    # 5. Handle external Google OAuth in Comet
    logger.info(f"Handling external Google OAuth in browser for {target_email}...")
    oauth_handled = handle_external_google_signin(target_email, timeout_sec=40)
    if not oauth_handled:
        logger.warning("External OAuth handler did not confirm success; checking Antigravity state...")
        
    # 6. Wait for Antigravity workbench to re-authenticate (fast polling)
    logger.info("Waiting for Antigravity workbench to confirm signedIn state...")
    authenticated = False
    for _ in range(25):
        if await is_authenticated_in_dom(page):
            authenticated = True
            break
        await asyncio.sleep(0.4)
        
    await asyncio.sleep(0.6)
    
    # 7. Verify new account email (fast polling)
    new_email = None
    for _ in range(12):
        try:
            new_email = await get_current_logged_in_email(page)
            if new_email and target_email.split("@")[0].lower() in new_email.lower():
                break
        except Exception:
            pass
        await asyncio.sleep(0.4)
        
    await close_settings(page)
    effective_new = new_email or target_email
    
    if new_email and target_email.split("@")[0].lower() in new_email.lower():
        logger.info(f"Successfully rotated and verified account: {new_email}!")
    else:
        logger.warning(f"Rotation complete. Active email detected: {new_email or effective_new}")
        
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
