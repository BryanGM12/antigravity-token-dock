"""
Goal Resumer: Deep Task & Conversation Continuity Guard
Detects stalled generation, interrupted goal steps, or hung streams,
and intelligently resumes active work after account rotation.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Tuple
from playwright.async_api import Page

logger = logging.getLogger("GoalResumer")

async def analyze_chat_state(page: Page) -> Dict[str, Any]:
    """Inspects the active chat DOM to determine if work was interrupted."""
    try:
        state = await page.evaluate(r'''() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const hasStopButton = buttons.some(b => {
                const txt = (b.innerText || '').toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                return txt.includes('stop') || txt.includes('detener') || aria.includes('stop');
            });
            const hasRetryButton = buttons.some(b => {
                const txt = (b.innerText || '').toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                return txt.includes('retry') || txt.includes('reintentar') || aria.includes('retry');
            });
            const hasResumeButton = buttons.some(b => {
                const txt = (b.innerText || '').toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                return txt.includes('continuar') || txt.includes('resume') || txt.includes('proceed');
            });
            
            // Check for error banners
            const alerts = Array.from(document.querySelectorAll('[role="alert"], .text-destructive'));
            const errorTexts = alerts.map(a => a.innerText.trim()).filter(Boolean);
            
            // Check if input box is ready
            const inputReady = !!document.querySelector('div[aria-label="Message input"], div[contenteditable="true"], textarea[placeholder*="Ask"]');
            
            return {
                hasStopButton,
                hasRetryButton,
                hasResumeButton,
                errorTexts,
                inputReady
            };
        }''')
        return state
    except Exception as e:
        logger.warning(f"Error analyzing chat state: {e}")
        return {}

async def clear_hung_generation(page: Page) -> bool:
    """If a stream is stuck in 'Stop generating' due to token cutoff, cancels it."""
    try:
        stop_btn = page.locator('button[aria-label*="Stop"], button:has-text("Stop generating"), button:has-text("Detener")')
        if await stop_btn.count() > 0 and await stop_btn.first.is_visible():
            logger.info("Hung generation detected. Clicking Stop/Cancel button...")
            await stop_btn.first.click()
            await asyncio.sleep(1.0)
            return True
    except Exception:
        pass
    return False

async def resume_with_context(page: Page, prompt_override: Optional[str] = None) -> bool:
    """
    Intelligently resumes the interrupted task:
    1. Clicks Retry if an explicit Retry button is available.
    2. Clicks Continuar / Resume if available.
    3. If none, types prompt ('continuar' or prompt_override) into input box and sends.
    """
    logger.info("Resuming active conversation with context...")
    
    # 1. Clear any stuck stop button
    await clear_hung_generation(page)
    await asyncio.sleep(0.5)
    
    # 2. Check for explicit Retry / Resume button
    for sel in ['button:has-text("Retry")', 'button:has-text("Reintentar")', 'button:has-text("Continuar")', 'button:has-text("Resume")', 'button:has-text("Proceed")']:
        btn = page.locator(sel)
        if await btn.count() > 0 and await btn.last.is_visible():
            logger.info(f"Found actionable button: '{sel}'. Clicking...")
            await btn.last.click()
            await asyncio.sleep(1.0)
            return True
            
    # 3. Enter message into chat input
    continuation_text = prompt_override or "continuar"
    logger.info(f"Submitting continuation message: '{continuation_text}'...")
    
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
            await page.keyboard.type(continuation_text)
            await asyncio.sleep(0.3)
            await page.keyboard.press("Enter")
            logger.info("Continuation message submitted via Enter key.")
            await asyncio.sleep(1.0)
            return True
            
    # Fallback: send button click
    send_btn = page.locator('button[aria-label*="Send"]')
    if await send_btn.count() > 0 and await send_btn.first.is_visible():
        await send_btn.first.click()
        logger.info("Clicked send button.")
        return True
        
    logger.warning("Could not submit continuation message.")
    return False

if __name__ == "__main__":
    print("Goal Resumer module loaded successfully.")
