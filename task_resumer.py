"""
Task Resumer: Conversation Recovery and Automatic Task Continuation
Navigates to active conversations after account rotation and triggers 'Continuar' / Resume.
"""

import asyncio
import logging
from typing import Optional, List
from playwright.async_api import Page

logger = logging.getLogger("TaskResumer")

import urllib.parse

async def navigate_to_conversation(page: Page, conv_id: str) -> bool:
    """Navigates to the specified conversation by UUID or sidebar link without crashing on network errors."""
    if not conv_id:
        return False
        
    # If already on this conversation, no navigation needed
    if conv_id in (page.url or ""):
        logger.info(f"Already on conversation {conv_id}.")
        return True
        
    logger.info(f"Navigating to conversation {conv_id}...")
    
    # 1. Preferred: Client-side React Router navigation (zero network reload, 0ms lag)
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
            await asyncio.sleep(0.8)
            return True
    except Exception as e:
        logger.debug(f"Client-side link click failed: {e}")

    # 2. Try clicking locator with force=True
    try:
        sidebar_link = page.locator(f'a[href*="{conv_id}"]')
        if await sidebar_link.count() > 0:
            await sidebar_link.first.click(force=True, timeout=2000)
            await asyncio.sleep(0.8)
            return True
    except Exception:
        pass
        
    # 3. Dynamic URL navigation using ACTUAL host & port from current page.url
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

async def find_and_trigger_resume_button(page: Page) -> bool:
    """Detects and clicks any explicit 'Continuar' or 'Resume' button in the chat stream."""
    resume_selectors = [
        'button:has-text("Continuar")',
        'button:has-text("Resume")',
        'button:has-text("Resume task")',
        'button:has-text("Reanudar")',
        'button:has-text("Retry")',
        'button:has-text("Proceed")'
    ]
    
    for sel in resume_selectors:
        buttons = page.locator(sel)
        cnt = await buttons.count()
        if cnt > 0:
            # Click the last visible one in the feed
            for i in reversed(range(cnt)):
                btn = buttons.nth(i)
                if await btn.is_visible():
                    logger.info(f"Found explicit resume button: {sel}. Clicking...")
                    await btn.click()
                    await asyncio.sleep(1.0)
                    return True
                    
    return False

async def send_continue_message_input(page: Page, message: str = "continuar") -> bool:
    """Types 'continuar' into the Antigravity message input and submits."""
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
            logger.info("Sent 'continuar' via Enter key.")
            await asyncio.sleep(1.0)
            return True
            
    # Try finding send button
    send_btn = page.locator('button[aria-label*="Send"], button:has(svg path[d*="M2.01 21L23 12 2.01 3"])')
    if await send_btn.count() > 0 and await send_btn.first.is_visible():
        await send_btn.first.click()
        logger.info("Clicked send button.")
        return True
        
    return False

async def resume_conversation_task(page: Page, conv_id: Optional[str] = None, auto_prompt: bool = False) -> bool:
    """
    Main resumption pipeline:
    1. Navigates to conversation if ID provided.
    2. Looks for explicit Resume / Continuar / Retry button in chat stream.
    3. If none found and auto_prompt=True, enters 'continuar' into message box.
    """
    if conv_id:
        try:
            await navigate_to_conversation(page, conv_id)
        except Exception as e:
            logger.warning(f"Failed to navigate to conversation {conv_id}: {e}")
        
    await asyncio.sleep(0.8)
    
    # 1. Look for explicit button
    if await find_and_trigger_resume_button(page):
        logger.info("Successfully resumed task via resume button.")
        return True
        
    # 2. Only type 'continuar' if explicitly authorized (e.g. background crash recovery)
    if auto_prompt:
        if await send_continue_message_input(page, "continuar"):
            logger.info("Successfully sent 'continuar' in chat input.")
            return True
            
    logger.info("Conversation restored cleanly without injecting unwanted prompt.")
    return True
