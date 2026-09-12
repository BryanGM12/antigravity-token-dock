"""
Task Resumer: Conversation Recovery and Automatic Task Continuation
Navigates to active conversations after account rotation and triggers 'Continuar' / Resume.
"""

import asyncio
import logging
from typing import Optional, List
from playwright.async_api import Page

logger = logging.getLogger("TaskResumer")

async def navigate_to_conversation(page: Page, conv_id: str) -> bool:
    """Navigates to the specified conversation by UUID or sidebar link."""
    logger.info(f"Navigating to conversation {conv_id}...")
    
    # Try clicking the sidebar link first if visible
    sidebar_link = page.locator(f'a[href*="{conv_id}"]')
    if await sidebar_link.count() > 0 and await sidebar_link.first.is_visible():
        await sidebar_link.first.click()
        await asyncio.sleep(1.0)
        return True
        
    # Otherwise navigate via URL directly
    current_url = page.url
    base_match = current_url.split("/c/")[0] if "/c/" in current_url else "https://127.0.0.1:59485"
    target_url = f"{base_match}/c/{conv_id}"
    await page.goto(target_url, wait_until="domcontentloaded")
    await asyncio.sleep(1.5)
    return True

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

async def resume_conversation_task(page: Page, conv_id: Optional[str] = None) -> bool:
    """
    Main resumption pipeline:
    1. Navigates to conversation if ID provided.
    2. Looks for explicit Resume / Continuar button.
    3. If none found, enters 'continuar' into the message box.
    """
    if conv_id:
        await navigate_to_conversation(page, conv_id)
        
    await asyncio.sleep(1.0)
    
    # 1. Look for explicit button
    if await find_and_trigger_resume_button(page):
        logger.info("Successfully resumed task via resume button.")
        return True
        
    # 2. Type 'continuar' into chat input
    if await send_continue_message_input(page, "continuar"):
        logger.info("Successfully sent 'continuar' in chat input.")
        return True
        
    logger.warning("Could not find resume button or active message input to continue.")
    return False
