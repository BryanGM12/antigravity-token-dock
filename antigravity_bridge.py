"""
Antigravity Bridge: CDP Connector and DOM Interaction Primitives
Provides robust access to the Antigravity Electron application via Chrome DevTools Protocol.
"""

import os
import re
import asyncio
from typing import Optional, Tuple, Dict, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

PORT_FILE = os.path.expandvars(r"%APPDATA%\Antigravity\DevToolsActivePort")

def get_cdp_port() -> int:
    """Reads the active remote debugging port from Antigravity user data."""
    if not os.path.exists(PORT_FILE):
        raise FileNotFoundError(f"Antigravity DevToolsActivePort not found at {PORT_FILE}. Is Antigravity running?")
    with open(PORT_FILE, "r", encoding="utf-8") as f:
        port_str = f.readline().strip()
    return int(port_str)

async def connect_antigravity(playwright_instance) -> Tuple[Browser, Page]:
    """Connects to the active Antigravity instance over CDP and returns (browser, main_page)."""
    port = get_cdp_port()
    cdp_url = f"http://127.0.0.1:{port}"
    browser = await playwright_instance.chromium.connect_over_cdp(cdp_url)
    
    if not browser.contexts:
        raise RuntimeError("Connected to Antigravity CDP but no browser contexts were found.")
    
    ctx = browser.contexts[0]
    # Find the main Antigravity webview/page
    target_page = None
    for p in ctx.pages:
        url = p.url
        if "127.0.0.1" in url and "/c/" in url or "section=" in url:
            target_page = p
            break
            
    if not target_page:
        if ctx.pages:
            target_page = ctx.pages[0]
        else:
            raise RuntimeError("No active pages found in Antigravity context.")
            
    return browser, target_page

async def get_active_conversation_id(page: Page) -> Optional[str]:
    """Extracts the conversation UUID from current page URL, breadcrumbs, or sidebar."""
    url = page.url
    match = re.search(r'/c/([a-f0-9\-]{36})', url)
    if match:
        return match.group(1)
        
    # Multi-strategy DOM extraction
    try:
        cid = await page.evaluate(r'''() => {
            // Check breadcrumb segment
            const bc = document.querySelector('[data-testid="breadcrumb-segment"], .breadcrumb');
            const bcTitle = bc ? bc.innerText.trim().toLowerCase() : '';
            
            const rows = document.querySelectorAll('a[href*="/c/"]');
            for (const a of rows) {
                const text = (a.innerText || '').toLowerCase();
                const href = a.getAttribute('href') || '';
                const m = href.match(/\/c\/([a-f0-9\-]{36})/);
                if (m) {
                    if (bcTitle && (text.includes(bcTitle) || bcTitle.includes(text))) {
                        return m[1];
                    }
                    // Check if parent has active background / styling
                    if (a.className.includes('bg-secondary') || a.parentElement.className.includes('bg-secondary')) {
                        return m[1];
                    }
                }
            }
            
            // Fallback: return first conversation row in sidebar
            for (const a of rows) {
                const href = a.getAttribute('href') || '';
                const m = href.match(/\/c\/([a-f0-9\-]{36})/);
                if (m) return m[1];
            }
            return null;
        }''')
        if cid:
            return cid
    except Exception:
        pass
        
    return None

async def open_settings(page: Page) -> bool:
    """Opens the Settings dialog if not already open."""
    dialog = page.locator('div[role="dialog"]')
    if await dialog.count() > 0 and await dialog.is_visible():
        return True
        
    settings_btn = page.locator('[data-testid="settings-button"]')
    if await settings_btn.count() == 0:
        return False
        
    await settings_btn.click()
    try:
        await page.wait_for_selector('div[role="dialog"]', timeout=3000)
        return True
    except Exception:
        return False

async def close_settings(page: Page) -> bool:
    """Closes the Settings dialog if open."""
    dialog = page.locator('div[role="dialog"]')
    if await dialog.count() > 0:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
        if await dialog.count() > 0 and await dialog.is_visible():
            # Try clicking close button or pressing Escape again
            close_btn = page.locator('div[role="dialog"] button[aria-label="Close"], div[role="dialog"] button:has-text("✕")')
            if await close_btn.count() > 0:
                await close_btn.first.click()
            else:
                await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
    return True

async def navigate_settings_tab(page: Page, tab_name: str) -> bool:
    """Navigates to a specific tab in the Settings dialog."""
    if not await open_settings(page):
        return False
        
    await asyncio.sleep(0.3)
    # Direct JS click to avoid DOM animation detachment issues
    clicked = await page.evaluate(f'''() => {{
        const btn = document.querySelector('[data-testid="settings-nav-item-{tab_name}"]') ||
                    Array.from(document.querySelectorAll('div[role="dialog"] button')).find(b => (b.innerText || '').trim().toLowerCase() === '{tab_name.lower()}');
        if (btn) {{
            btn.click();
            return true;
        }}
        return false;
    }}''')
    if clicked:
        await asyncio.sleep(0.4)
        return True
        
    # Tab names: 'Account', 'Models', 'General', 'Application', 'Appearance', etc.
    tab_locator = page.locator(f'[data-testid="settings-nav-item-{tab_name}"]')
    if await tab_locator.count() > 0:
        try:
            await tab_locator.first.click(timeout=2000, force=True)
            await asyncio.sleep(0.4)
            return True
        except Exception:
            pass
        
    # Fallback restricted strictly to navigation sidebar to never click content buttons
    fallback = page.locator(f'div[role="dialog"] nav button:has-text("{tab_name}"), div[role="dialog"] aside button:has-text("{tab_name}")')
    if await fallback.count() > 0:
        try:
            await fallback.first.click(timeout=2000, force=True)
            await asyncio.sleep(0.4)
            return True
        except Exception:
            pass
        
    return False

async def get_current_logged_in_email(page: Page, close_after: bool = True) -> Optional[str]:
    """Returns the currently authenticated email, checking React context first, then Account settings."""
    try:
        direct_email = await page.evaluate(r'''async () => {
            const allEls = document.querySelectorAll('*');
            let core = null;
            for (const el of allEls) {
                const key = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
                if (!key) continue;
                let cur = el[key];
                while (cur) {
                    if (cur.memoizedProps?.value?.core) {
                        core = cur.memoizedProps.value.core;
                        break;
                    }
                    cur = cur.return;
                }
                if (core) break;
            }
            if (core?.authService?._lsClient?.getUserStatus) {
                try {
                    const st = await core.authService._lsClient.getUserStatus({});
                    return st?.userStatus?.email || null;
                } catch (e) {
                    return null;
                }
            }
            return null;
        }''')
        if direct_email and "@" in direct_email:
            return direct_email.strip().lower()
    except Exception:
        pass

    if not await navigate_settings_tab(page, "Account"):
        from token_memory import load_memory
        mem = load_memory()
        return mem.get("active_account")
        
    await asyncio.sleep(0.3)
    email_text = await page.evaluate(r'''() => {
        const dialog = document.querySelector('div[role="dialog"]');
        if (!dialog) return null;
        const text = dialog.innerText;
        const match = text.match(/[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+/);
        return match ? match[0] : null;
    }''')
    
    if close_after:
        await close_settings(page)
        
    if not email_text:
        from token_memory import load_memory
        mem = load_memory()
        return mem.get("active_account")
        
    return email_text.strip().lower()
