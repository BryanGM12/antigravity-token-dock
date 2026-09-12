"""
Quota Detector: Proactive and Reactive Token & Quota Exhaustion Detection
Monitors Models & Usage percentages directly via internal React services,
language_server.log real-time errors, and live chat error banners.
"""

import os
import re
import time
import asyncio
import logging
from typing import Dict, Any, Tuple, Optional
from playwright.async_api import Page
from antigravity_bridge import open_settings, close_settings, navigate_settings_tab

logger = logging.getLogger("QuotaDetector")

LOG_FILE = os.path.expandvars(r"%APPDATA%\Antigravity\logs\language_server.log")

async def get_direct_quota_limits(page: Page, known_email: Optional[str] = None) -> Dict[str, Any]:
    """
    Queries cloudCodeService.retrieveUserQuotaSummary and authService._lsClient.getUserStatus
    directly from the React context.
    Executes in under 50ms with ZERO visual disruption (no settings dialog opened).
    Tracks both Gemini Models and Claude/GPT Models with exact timestamps and per-model metrics.
    """
    try:
        data = await page.evaluate(r'''async () => {
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
            if (!core) return null;
            
            let quotaSummary = null;
            if (core.cloudCodeService) {
                try {
                    quotaSummary = await core.cloudCodeService.retrieveUserQuotaSummary({});
                } catch (e) {
                    quotaSummary = { error: String(e) };
                }
            }
            
            let userStatus = null;
            if (core.authService?._lsClient?.getUserStatus) {
                try {
                    userStatus = await core.authService._lsClient.getUserStatus({});
                } catch (e) {
                    userStatus = { error: String(e) };
                }
            }
            
            return {
                quotaSummary,
                userStatus
            };
        }''')
        
        if not data:
            return {}
            
        # Parse Email
        detected_email = None
        user_st = data.get("userStatus", {}).get("userStatus", {})
        if user_st.get("email"):
            detected_email = user_st["email"].strip().lower()
            
        resolved_email = known_email or detected_email
        if not resolved_email:
            try:
                from token_memory import load_memory
                resolved_email = load_memory().get("active_account")
            except Exception:
                pass
                
        # Parse Groups from Quota Summary
        groups = data.get("quotaSummary", {}).get("response", {}).get("groups", [])
        
        gemini_group = next((g for g in groups if "Gemini" in g.get("displayName", "")), None)
        claude_group = next((g for g in groups if "Claude" in g.get("displayName", "") or "GPT" in g.get("displayName", "")), None)
        
        def parse_bucket_group(group):
            res = {
                "weekly_remaining_pct": None,
                "five_hour_remaining_pct": None,
                "weekly_refresh_text": None,
                "five_hour_refresh_text": None,
                "weekly_reset_time": None,
                "five_hour_reset_time": None,
                "disabled": False
            }
            if not group:
                return res
            for bucket in group.get("buckets", []):
                bid = bucket.get("bucketId", "").lower()
                rem = bucket.get("remaining", {})
                rem_fraction = rem.get("value") if rem.get("case") == "remainingFraction" else None
                rem_pct = int(round(rem_fraction * 100)) if rem_fraction is not None else None
                desc = bucket.get("description", "")
                reset_ts = bucket.get("resetTime", {}).get("seconds")
                is_disabled = bucket.get("disabled", False)
                if is_disabled:
                    res["disabled"] = True
                    
                ref_m = re.search(r'refresh in\s+([^.\n]+)', desc, re.IGNORECASE)
                ref_text = ref_m.group(1).strip() if ref_m else None
                
                if "weekly" in bid:
                    res["weekly_remaining_pct"] = rem_pct
                    res["weekly_refresh_text"] = ref_text
                    res["weekly_reset_time"] = reset_ts
                elif "5h" in bid or "five" in bid:
                    res["five_hour_remaining_pct"] = rem_pct
                    res["five_hour_refresh_text"] = ref_text
                    res["five_hour_reset_time"] = reset_ts
            return res

        gemini_data = parse_bucket_group(gemini_group)
        claude_data = parse_bucket_group(claude_group)
        
        # Parse Models Quotas
        models_data = {}
        for m_cfg in user_st.get("cascadeModelConfigData", {}).get("clientModelConfigs", []):
            m_id = m_cfg.get("modelId", "")
            q_info = m_cfg.get("quotaInfo", {})
            if m_id and q_info:
                models_data[m_id] = {
                    "label": m_cfg.get("label", m_id),
                    "remaining_fraction": q_info.get("remainingFraction"),
                    "reset_time": q_info.get("resetTime", {}).get("seconds"),
                    "disabled": m_cfg.get("disabled", False)
                }
                
        # Determine exhaustion
        is_ex = False
        g_5h = gemini_data.get("five_hour_remaining_pct")
        g_wk = gemini_data.get("weekly_remaining_pct")
        if (g_5h is not None and g_5h <= 0) or (g_wk is not None and g_wk <= 0):
            is_ex = True
            
        limits = {
            "email": resolved_email,
            "weekly_remaining_pct": gemini_data.get("weekly_remaining_pct"),
            "five_hour_remaining_pct": gemini_data.get("five_hour_remaining_pct"),
            "weekly_refresh_text": gemini_data.get("weekly_refresh_text"),
            "five_hour_refresh_text": gemini_data.get("five_hour_refresh_text"),
            "weekly_reset_time": gemini_data.get("weekly_reset_time"),
            "five_hour_reset_time": gemini_data.get("five_hour_reset_time"),
            "gemini": gemini_data,
            "claude_gpt": claude_data,
            "models": models_data,
            "is_exhausted": is_ex
        }
        
        if resolved_email:
            try:
                from token_memory import update_account_snapshot
                update_account_snapshot(
                    email=resolved_email,
                    weekly_pct=gemini_data["weekly_remaining_pct"],
                    five_hour_pct=gemini_data["five_hour_remaining_pct"],
                    weekly_refresh_text=gemini_data["weekly_refresh_text"],
                    five_hour_refresh_text=gemini_data["five_hour_refresh_text"],
                    weekly_reset_time=gemini_data["weekly_reset_time"],
                    five_hour_reset_time=gemini_data["five_hour_reset_time"],
                    gemini_data=gemini_data,
                    claude_data=claude_data,
                    models_data=models_data
                )
            except Exception as e:
                logger.debug(f"Failed to update token memory: {e}")
                
        return limits
    except Exception as e:
        logger.debug(f"Direct quota query failed: {e}")
        return {}

async def get_ui_quota_limits(page: Page, known_email: Optional[str] = None) -> Dict[str, Any]:
    """Fallback UI scraper: Navigates to Models settings and extracts real-time quota percentages."""
    is_opened = False
    dialog = page.locator('div[role="dialog"]')
    if await dialog.count() == 0 or not await dialog.is_visible():
        is_opened = True
        
    nav_success = await navigate_settings_tab(page, "Models")
    if not nav_success:
        return {"error": "Failed to navigate to Models tab", "is_exhausted": False}
        
    await asyncio.sleep(0.4)
    
    dialog_text = await page.locator('div[role="dialog"]').inner_text()
    lines = [line.strip() for line in dialog_text.split('\n') if line.strip()]
    
    limits = {
        "weekly_remaining_pct": None,
        "five_hour_remaining_pct": None,
        "weekly_refresh_text": None,
        "five_hour_refresh_text": None,
        "is_exhausted": False
    }
    
    for i, line in enumerate(lines):
        if "Weekly Limit Remaining" in line:
            for window_line in lines[i:min(len(lines), i+4)]:
                m = re.search(r'(\d+)%', window_line)
                if m and limits["weekly_remaining_pct"] is None:
                    limits["weekly_remaining_pct"] = int(m.group(1))
                ref_m = re.search(r'refresh in\s+([^.\n]+)', window_line, re.IGNORECASE)
                if ref_m and limits["weekly_refresh_text"] is None:
                    limits["weekly_refresh_text"] = ref_m.group(1).strip()
                    
        elif "Five Hour Limit Remaining" in line:
            for window_line in lines[i:min(len(lines), i+4)]:
                m = re.search(r'(\d+)%', window_line)
                if m and limits["five_hour_remaining_pct"] is None:
                    limits["five_hour_remaining_pct"] = int(m.group(1))
                ref_m = re.search(r'refresh in\s+([^.\n]+)', window_line, re.IGNORECASE)
                if ref_m and limits["five_hour_refresh_text"] is None:
                    limits["five_hour_refresh_text"] = ref_m.group(1).strip()
                    
    # Determine exhaustion
    if limits["five_hour_remaining_pct"] is not None and limits["five_hour_remaining_pct"] <= 0:
        limits["is_exhausted"] = True
    if limits["weekly_remaining_pct"] is not None and limits["weekly_remaining_pct"] <= 0:
        limits["is_exhausted"] = True
        
    resolved_email = known_email
    if not resolved_email:
        try:
            from token_memory import load_memory
            resolved_email = load_memory().get("active_account")
        except Exception:
            pass
            
    if is_opened:
        await close_settings(page)
        
    # Update persistent memory
    if resolved_email:
        try:
            from token_memory import update_account_snapshot
            update_account_snapshot(
                email=resolved_email,
                weekly_pct=limits["weekly_remaining_pct"],
                five_hour_pct=limits["five_hour_remaining_pct"],
                weekly_refresh_text=limits["weekly_refresh_text"],
                five_hour_refresh_text=limits["five_hour_refresh_text"]
            )
        except Exception:
            pass
            
    return limits

async def get_quota_limits(page: Page, known_email: Optional[str] = None) -> Dict[str, Any]:
    """Gets quota limits preferring direct background query first, falling back to UI scraper."""
    direct = await get_direct_quota_limits(page, known_email)
    if direct and direct.get("weekly_remaining_pct") is not None:
        return direct
    return await get_ui_quota_limits(page, known_email)

def check_log_quota_errors(lookback_seconds: int = 60) -> Tuple[bool, str]:
    """Tails language_server.log to detect recent quota exhaustion or capacity errors."""
    if not os.path.exists(LOG_FILE):
        return False, "Log file not found"
        
    try:
        from datetime import datetime
        now = datetime.now()
        
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            
        recent_lines = lines[-150:] if len(lines) > 150 else lines
        error_patterns = [
            (r"MODEL_CAPACITY_EXHAUSTED", "Google Model Capacity Exhausted"),
            (r"RESOURCE_EXHAUSTED", "Google Resource Quota Exhausted"),
            (r"No capacity available for model", "No capacity available for model"),
            (r'error_number":\s*"2010"', "Error 2010 (Model Capacity Exhausted)")
        ]
        
        for line in reversed(recent_lines):
            for pattern, desc in error_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    ts_match = re.search(r'[IWEF](\d{2})(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', line)
                    if ts_match:
                        month, day, hour, minute, second = map(int, ts_match.groups())
                        try:
                            line_time = now.replace(month=month, day=day, hour=hour, minute=minute, second=second)
                            diff = (now - line_time).total_seconds()
                            if 0 <= diff <= lookback_seconds:
                                return True, f"{desc} (hace {int(diff)}s)"
                        except Exception:
                            pass
                    else:
                        return True, desc
                        
        return False, "No recent errors in log"
    except Exception as e:
        return False, f"Log check error: {str(e)}"

async def check_chat_quota_errors(page: Page) -> Tuple[bool, str]:
    """Checks the chat conversation area for visible quota/rate limit error banners."""
    try:
        error_info = await page.evaluate('''() => {
            const errorKeywords = [
                'resource has been exhausted',
                'quota exceeded',
                'rate limit reached',
                'capacity exhausted',
                'you have exhausted your capacity',
                'model capacity exhausted'
            ];
            
            const cards = document.querySelectorAll('[role="alert"], .text-destructive, .bg-destructive, div');
            for (const el of cards) {
                const txt = (el.innerText || '').toLowerCase();
                for (const kw of errorKeywords) {
                    if (txt.includes(kw)) {
                        return { found: true, message: kw };
                    }
                }
            }
            return { found: false, message: '' };
        }''')
        
        if error_info.get("found"):
            return True, f"Chat error banner detected: {error_info.get('message')}"
        return False, "No chat errors detected"
    except Exception as e:
        return False, f"Chat check error: {str(e)}"

async def evaluate_token_exhaustion(page: Page) -> Tuple[bool, str]:
    """
    Comprehensive token exhaustion check combining:
    1. Active chat error banners
    2. Real-time language_server.log events
    3. Direct background quota limit percentages (no UI popups)
    """
    # 1. Chat errors (most immediate)
    chat_err, chat_desc = await check_chat_quota_errors(page)
    if chat_err:
        return True, chat_desc
        
    # 2. Live log errors
    log_err, log_desc = check_log_quota_errors(lookback_seconds=45)
    if log_err:
        return True, log_desc
        
    # 3. Direct background quota check (silent, zero flicker)
    limits = await get_quota_limits(page)
    if limits.get("is_exhausted"):
        return True, f"Quota limit hit 0% (5h: {limits.get('five_hour_remaining_pct')}%, Weekly: {limits.get('weekly_remaining_pct')}%)"
        
    return False, "Tokens and quota available"
