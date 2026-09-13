"""
Task Resumer: Conversation Recovery and Automatic Task Continuation
Navigates to active conversations after account rotation and triggers 'Continuar' / Resume.
Hardened with non-reloading navigation, interruption detection, and zero-intrusion guarantees.
"""

import asyncio
import logging
import urllib.parse
from typing import Optional, List
from playwright.async_api import Page

logger = logging.getLogger("TaskResumer")

async def navigate_to_conversation(page: Page, conv_id: str) -> bool:
    """Navigates to the specified conversation by UUID or sidebar link without crashing on network errors."""
    if not conv_id:
        return False
        
    # If already on this conversation, no navigation needed
    if conv_id in (page.url or ""):
        logger.info(f"Already on conversation {conv_id}.")
        return True
        
    logger.info(f"Navigating to conversation {conv_id}...")
    
    # 1. Preferred: Client-side React link click (zero network reload, 0ms lag)
    try:
        clicked = await page.evaluate(f'''() => {{
            const link = document.querySelector('a[href*="{conv_id}"]');
            if (link) {{
                link.click();
                return true;
            }}
            return false;
        }}''')
        if clicked:
            await asyncio.sleep(0.6)
            if conv_id in (page.url or ""):
                return True
    except Exception as e:
        logger.debug(f"Client-side link click failed: {e}")

    # 2. React Router pushState navigation (smooth SPA transition)
    try:
        target_path = f"/c/{conv_id}"
        nav_ok = await page.evaluate(f'''(tPath) => {{
            if (window.location.pathname === tPath) return true;
            window.history.pushState({{}}, '', tPath);
            window.dispatchEvent(new PopStateEvent('popstate'));
            return true;
        }}''', target_path)
        if nav_ok:
            await asyncio.sleep(0.6)
            if conv_id in (page.url or ""):
                return True
    except Exception as e:
        logger.debug(f"pushState navigation failed: {e}")

    # 3. Try clicking locator with force=True
    try:
        sidebar_link = page.locator(f'a[href*="{conv_id}"]')
        if await sidebar_link.count() > 0 and await sidebar_link.first.is_visible():
            await sidebar_link.first.click(force=True, timeout=2000)
            await asyncio.sleep(0.8)
            if conv_id in (page.url or ""):
                return True
    except Exception:
        pass
        
    # 4. Dynamic URL navigation using ACTUAL host & port from current page.url (fallback)
    try:
        current_url = page.url or ""
        parsed = urllib.parse.urlparse(current_url)
        if parsed.scheme and parsed.netloc and ":" in parsed.netloc:
            target_url = f"{parsed.scheme}://{parsed.netloc}/c/{conv_id}"
            await page.goto(target_url, wait_until="domcontentloaded", timeout=6000)
            await asyncio.sleep(1.0)
            return True
    except Exception as e:
        logger.warning(f"Direct URL navigation to {conv_id} failed safely: {e}")
        
    return False

async def clear_hung_generation(page: Page) -> bool:
    """If a stream is stuck in 'Stop generating' due to token cutoff, cancels it cleanly."""
    try:
        stop_btn = page.locator('button[aria-label*="Stop"], button:has-text("Stop generating"), button:has-text("Detener")')
        if await stop_btn.count() > 0 and await stop_btn.first.is_visible():
            logger.info("Hung generation detected in chat feed. Clicking Stop button...")
            await stop_btn.first.click(force=True)
            await asyncio.sleep(0.8)
            return True
    except Exception as e:
        logger.debug(f"Stop button clear failed: {e}")
    return False

async def is_task_interrupted(page: Page) -> bool:
    """
    Checks if the conversation actually has an error, rate limit alert,
    hung stop button, or uncompleted generation.
    Prevents intrusive continuation prompts if the task completed normally.
    """
    try:
        res = await page.evaluate(r'''() => {
            const alerts = document.querySelectorAll('[role="alert"], .text-destructive');
            for (const a of alerts) {
                const t = (a.innerText || '').toLowerCase();
                if (t.includes('quota') || t.includes('limit') || t.includes('rate') || t.includes('error') || t.includes('cuota') || t.includes('interrumpid')) {
                    return true;
                }
            }
            const btns = Array.from(document.querySelectorAll('button'));
            const hasRetry = btns.some(b => {
                const txt = (b.innerText || '').toLowerCase();
                return txt.includes('retry') || txt.includes('reintentar') || txt.includes('resume') || txt.includes('reanudar');
            });
            if (hasRetry) return true;

            const hasStop = btns.some(b => {
                const txt = (b.innerText || '').toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                return txt.includes('stop generating') || txt.includes('detener') || aria.includes('stop');
            });
            if (hasStop) return true;

            return false;
        }''')
        return bool(res)
    except Exception:
        return False

async def find_and_trigger_resume_button(page: Page) -> bool:
    """
    Detects and clicks explicit 'Continuar' or 'Retry' buttons in the chat stream.
    Strictly excludes approval buttons (like 'Proceed') to prevent unwanted action execution.
    """
    resume_selectors = [
        'button:has-text("Retry")',
        'button:has-text("Reintentar")',
        'button:has-text("Resume")',
        'button:has-text("Resume task")',
        'button:has-text("Reanudar")',
        'button:has-text("Continuar")',
        'button:has-text("Continuar generación")',
        'button:has-text("Intentar de nuevo")'
    ]
    
    for sel in resume_selectors:
        buttons = page.locator(sel)
        cnt = await buttons.count()
        if cnt > 0:
            for i in reversed(range(cnt)):
                btn = buttons.nth(i)
                if await btn.is_visible():
                    logger.info(f"Found explicit resume button: {sel}. Clicking...")
                    await btn.click(force=True)
                    await asyncio.sleep(1.0)
                    return True
                    
    return False

async def send_continue_message_input(page: Page, message: str = "continuar") -> bool:
    """Types continuation message into the Antigravity message input and submits cleanly."""
    logger.info(f"Typing '{message}' into chat message input...")
    input_selectors = [
        'div[aria-label="Message input"]',
        'div[contenteditable="true"]',
        'textarea[placeholder*="Ask anything"]',
        'input[placeholder*="Ask anything"]'
    ]
    
    for sel in input_selectors:
        box = page.locator(sel)
        if await box.count() > 0 and await box.first.is_visible():
            await box.first.click()
            await asyncio.sleep(0.2)
            await page.keyboard.type(message)
            await asyncio.sleep(0.3)
            # Press Enter
            await page.keyboard.press("Enter")
            logger.info("Sent continuation message via Enter key.")
            await asyncio.sleep(1.0)
            return True
            
    # Try finding send button
    send_btn = page.locator('button[aria-label*="Send"], button:has(svg path[d*="M2.01 21L23 12 2.01 3"])')
    if await send_btn.count() > 0 and await send_btn.first.is_visible():
        await send_btn.first.click(force=True)
        logger.info("Clicked send button.")
        return True
        
    return False

async def resume_conversation_task(page: Page, conv_id: Optional[str] = None, auto_prompt: bool = False) -> bool:
    """
    Main resumption pipeline:
    1. Navigates to conversation if ID provided.
    2. Clears any hung generation stream.
    3. Looks for explicit Resume / Retry button in chat stream.
    4. Checks if task was actually interrupted before sending any continuation prompt.
    5. If interrupted and auto_prompt=True, submits clean 'continuar' message.
    """
    if conv_id:
        try:
            await navigate_to_conversation(page, conv_id)
        except Exception as e:
            logger.warning(f"Failed to navigate to conversation {conv_id}: {e}")
        
    await asyncio.sleep(0.6)
    
    # 1. Clear hung generation if stuck
    await clear_hung_generation(page)
    await asyncio.sleep(0.4)

    # 2. Look for explicit resume/retry button
    if await find_and_trigger_resume_button(page):
        logger.info("Successfully resumed task via resume button.")
        return True
        
    # 3. Only type 'continuar' if explicitly authorized AND task was actually interrupted
    if auto_prompt:
        if await is_task_interrupted(page):
            logger.info("Interrupted task state confirmed. Submitting continuation prompt...")
            if await send_continue_message_input(page, "continuar"):
                logger.info("Successfully sent 'continuar' in chat input.")
                return True
        else:
            logger.info("No active errors or interrupted state detected; skipping intrusive continuation prompt.")
            
    logger.info("Conversation restored cleanly without injecting unwanted prompt.")
    return True
