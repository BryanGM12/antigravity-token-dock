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
from typing import Dict, Any, Tuple, Optional, List
from playwright.async_api import Page
from antigravity_bridge import open_settings, close_settings, navigate_settings_tab

from cloud_code_client import (
    CLOUD_CODE_ENDPOINT,
    CLOUD_CODE_FALLBACK_ENDPOINT,
    DEFAULT_USER_AGENT,
    query_cloud_code_quota_direct,
    parse_cloud_code_quota_response,
    parse_reset_time_seconds,
    monitor_accounts_parallel,
    save_account_token,
    get_account_token,
    load_all_account_tokens,
    sync_active_antigravity_oauth_token
)

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
            let core = window.__antigravityCore;
            if (!core) {
                const primary = document.querySelectorAll('div[id], div[class*="workbench"], main, #root, [data-testid], nav, aside, button, header');
                const allNodes = primary.length > 0 ? Array.from(primary) : Array.from(document.querySelectorAll('*')).slice(0, 300);
                for (const el of allNodes) {
                    const key = Object.keys(el).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                    if (!key) continue;
                    let cur = el[key];
                    let depth = 0;
                    while (cur && depth < 100) {
                        const candidate = cur.memoizedProps?.value?.core || cur.memoizedProps?.core || cur.stateNode?.core;
                        if (candidate && (candidate.authService || candidate.cloudCodeService)) {
                            core = candidate;
                            window.__antigravityCore = core;
                            break;
                        }
                        cur = cur.return;
                        depth++;
                    }
                    if (core) break;
                }
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

            // Attempt to extract live OAuth access token from authService / cloudCodeService / userStatus
            let oauthToken = null;
            try {
                const auth = core.authService;
                const stateCtx = auth?.authStateProvider?.getState?.()?.context || auth?._state?.context || {};
                const candidates = [
                    stateCtx?.tokenInfo?.accessToken,
                    stateCtx?.accessToken,
                    stateCtx?.token,
                    stateCtx?.oauthToken,
                    stateCtx?.credentials?.accessToken,
                    auth?.accessToken,
                    auth?._accessToken,
                    auth?._token,
                    core.cloudCodeService?.accessToken,
                    core.cloudCodeService?._accessToken,
                    userStatus?.userStatus?.accessToken,
                    userStatus?.accessToken
                ];
                for (const c of candidates) {
                    if (typeof c === 'string' && c.trim().length >= 20) {
                        oauthToken = c.trim();
                        break;
                    }
                }
                if (!oauthToken && typeof auth?.getAccessToken === 'function') {
                    const t = await auth.getAccessToken();
                    if (typeof t === 'string' && t.trim().length >= 20) {
                        oauthToken = t.trim();
                    } else if (t && typeof t.accessToken === 'string') {
                        oauthToken = t.accessToken.trim();
                    }
                }
                if (!oauthToken && typeof auth?.getToken === 'function') {
                    const t = await auth.getToken();
                    if (typeof t === 'string' && t.trim().length >= 20) {
                        oauthToken = t.trim();
                    }
                }
            } catch (e) {}
            
            return {
                quotaSummary,
                userStatus,
                oauthToken
            };
        }''')
        
        if not data:
            return {}
            
        # Parse Email
        detected_email = None
        user_st = (data.get("userStatus") or {}).get("userStatus") or {}
        if user_st.get("email"):
            detected_email = user_st["email"].strip().lower()
            
        resolved_email = known_email or detected_email
        if not resolved_email:
            try:
                from token_memory import load_memory
                resolved_email = load_memory().get("active_account")
            except Exception:
                pass

        # Persist captured live OAuth token for Capa 1 direct HTTPS queries, or sync from Windows Credential Manager / Gemini profile
        extracted_token = data.get("oauthToken")
        if resolved_email:
            try:
                sync_active_antigravity_oauth_token(fallback_email=resolved_email)
            except Exception:
                pass
            if extracted_token and isinstance(extracted_token, str):
                try:
                    save_account_token(resolved_email, extracted_token)
                except Exception as e:
                    logger.debug(f"Failed to persist OAuth token for {resolved_email}: {e}")
            else:
                try:
                    get_account_token(resolved_email)
                except Exception:
                    pass
                
        # Parse Groups from Quota Summary safely
        quota_resp = (data.get("quotaSummary") or {}).get("response") or {}
        groups = quota_resp.get("groups") if isinstance(quota_resp, dict) else []
        if not groups:
            groups = []
        
        gemini_group = next((g for g in groups if isinstance(g, dict) and "gemini" in (g.get("displayName") or "").lower()), None)
        claude_group = next((g for g in groups if isinstance(g, dict) and any(k in (g.get("displayName") or "").lower() for k in ["claude", "gpt", "other"])), None)
        
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
            if not group or not isinstance(group, dict):
                return res
            buckets = group.get("buckets") or []
            for bucket in buckets:
                if not bucket or not isinstance(bucket, dict):
                    continue
                bid = (bucket.get("bucketId") or "").lower()
                rem = bucket.get("remaining") or {}
                rem_fraction = None
                if isinstance(rem, dict):
                    rem_fraction = rem.get("value") if rem.get("case") == "remainingFraction" else rem.get("remainingFraction")
                    if rem_fraction is None and "value" in rem:
                        rem_fraction = rem.get("value")
                elif isinstance(rem, (int, float)):
                    rem_fraction = float(rem)

                if rem_fraction is None and "remainingFraction" in bucket:
                    rem_fraction = bucket.get("remainingFraction")

                rem_pct = int(round(rem_fraction * 100)) if rem_fraction is not None else None
                desc = bucket.get("description") or ""
                reset_sec = parse_reset_time_seconds(bucket.get("resetTime"))

                is_disabled = bucket.get("disabled", False)
                if is_disabled:
                    res["disabled"] = True
                    
                ref_m = re.search(r'refresh in\s+([^.\n]+)', desc, re.IGNORECASE) if desc else None
                ref_text = ref_m.group(1).strip() if ref_m else None
                
                if "weekly" in bid:
                    res["weekly_remaining_pct"] = rem_pct
                    res["weekly_refresh_text"] = ref_text
                    res["weekly_reset_time"] = reset_sec
                elif "5h" in bid or "five" in bid or "hourly" in bid:
                    res["five_hour_remaining_pct"] = rem_pct
                    res["five_hour_refresh_text"] = ref_text
                    res["five_hour_reset_time"] = reset_sec
            return res

        gemini_data = parse_bucket_group(gemini_group)
        claude_data = parse_bucket_group(claude_group)
        
        # Parse Models Quotas safely
        models_data = {}
        cascade_data = (user_st.get("cascadeModelConfigData") or {}) if isinstance(user_st, dict) else {}
        model_configs = cascade_data.get("clientModelConfigs") or [] if isinstance(cascade_data, dict) else []
        for m_cfg in model_configs:
            if not m_cfg or not isinstance(m_cfg, dict):
                continue
            m_id = m_cfg.get("modelId", "")
            q_info = m_cfg.get("quotaInfo") or {}
            if m_id and isinstance(q_info, dict):
                models_data[m_id] = {
                    "label": m_cfg.get("label", m_id),
                    "remaining_fraction": q_info.get("remainingFraction"),
                    "reset_time": parse_reset_time_seconds(q_info.get("resetTime")),
                    "disabled": m_cfg.get("disabled", False)
                }
                
        # Determine exhaustion
        is_ex = False
        g_5h = gemini_data.get("five_hour_remaining_pct")
        g_wk = gemini_data.get("weekly_remaining_pct")
        effective_5h = g_5h if g_5h is not None else g_wk
        if (effective_5h is not None and effective_5h <= 0) or (g_wk is not None and g_wk <= 0):
            is_ex = True
            
        limits = {
            "email": resolved_email,
            "weekly_remaining_pct": g_wk,
            "five_hour_remaining_pct": effective_5h,
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
    if await dialog.count() == 0 or not await dialog.first.is_visible():
        is_opened = True
        
    nav_success = await navigate_settings_tab(page, "Models")
    if not nav_success:
        return {"error": "Failed to navigate to Models tab", "is_exhausted": False}
        
    await asyncio.sleep(0.4)
    
    dialog_text = await page.locator('div[role="dialog"]').first.inner_text()
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

def get_decoupled_parallel_quotas(accounts: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """
    Capa 1: Monitoreo desacoplado en paralelo de todas las cuentas configuradas
    vía Google Cloud Code HTTPS (User-Agent: antigravity/1.11.5 windows/amd64)
    sin tocar la ventana de Antigravity ni cambiar de cuenta.
    """
    return monitor_accounts_parallel(accounts=accounts)

async def get_quota_limits(
    page: Optional[Page] = None,
    known_email: Optional[str] = None,
    access_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Gets quota limits using 3-tier resilient hierarchy:
    Tier 1 (Capa 1 direct HTTPS): If access_token provided, queries Google Cloud Code directly.
    Tier 2 (React context direct): If page provided, queries React fiber background context (<50ms).
    Tier 3 (UI / memory fallback): Scrapes Models dialog if page present, or returns token_memory status.
    """
    # Tier 1: Direct HTTPS Google Cloud Code when access_token is explicitly provided or no page is attached
    if access_token:
        res = query_cloud_code_quota_direct(access_token=access_token, email=known_email)
        if res.get("status") == "OK":
            return res

    # Tier 2: React Fiber direct background reading when live page is available (<50ms, captures fresh OAuth token)
    if page:
        direct = await get_direct_quota_limits(page, known_email)
        if direct and (direct.get("weekly_remaining_pct") is not None or direct.get("five_hour_remaining_pct") is not None):
            return direct

    # Stored token direct HTTPS query (when page is None or React Fiber didn't return quota)
    if known_email and not access_token:
        stored_token = get_account_token(known_email)
        if stored_token:
            res = query_cloud_code_quota_direct(access_token=stored_token, email=known_email)
            if res.get("status") == "OK":
                return res

    if page:
        return await get_ui_quota_limits(page, known_email)

    # Tier 3: Memory fallback
    if known_email:
        try:
            from token_memory import get_effective_account_status
            return get_effective_account_status(known_email)
        except Exception:
            pass

    return {}

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
                    # Notice: if no timestamp matches within lookback_seconds, do not falsely flag stale errors
                        
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
            
            // Only inspect actual error/alert banners, strictly excluding conversation messages and code blocks
            const cards = document.querySelectorAll('[role="alert"], .text-destructive, .bg-destructive, [data-testid*="error-banner"], [data-testid*="alert"]');
            for (const el of cards) {
                if (el.closest('.user-message, .assistant-message, pre, code, p')) {
                    continue;
                }
                const txt = (el.textContent || '').toLowerCase();
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
