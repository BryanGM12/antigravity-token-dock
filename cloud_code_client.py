"""
Cloud Code Direct Client: Decoupled HTTPS Google Cloud Code Quota Monitoring
=============================================================================
Capa 1: Decoupled Direct HTTPS Querying via Google Cloud Code API:
- Endpoint: https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary
- Fallback: https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary
- Header: User-Agent: antigravity/1.11.5 windows/amd64
- Queries account quotas in parallel without touching Antigravity UI or changing active accounts.
- Integrates with token memory for seamless multi-account quota monitoring.
"""

import os
import re
import ssl
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from atomic_state import SafeJsonStore

logger = logging.getLogger("CloudCodeClient")

CLOUD_CODE_ENDPOINT = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
CLOUD_CODE_FALLBACK_ENDPOINT = "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
DEFAULT_USER_AGENT = "antigravity/1.11.5 windows/amd64"

TOKEN_STORE_DIR = os.path.expandvars(r"%USERPROFILE%\.openclaw\workspace\state\antigravity_controller")
TOKEN_STORE_FILE = os.path.join(TOKEN_STORE_DIR, "account_tokens.json")


def _get_ssl_context() -> ssl.SSLContext:
    """Creates a secure SSL context for Google Cloud Code HTTPS requests."""
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def load_all_account_tokens() -> Dict[str, str]:
    """Loads stored OAuth access tokens for background account querying."""
    return SafeJsonStore.load_json(TOKEN_STORE_FILE, dict)


def save_account_token(email: str, token: str) -> bool:
    """Atomically stores or updates an OAuth token for a given account."""
    if not email or not token:
        return False
    data = load_all_account_tokens()
    data[email.strip().lower()] = token.strip()
    SafeJsonStore.save_json(TOKEN_STORE_FILE, data)
    return True


def get_account_token(email: str) -> Optional[str]:
    """Retrieves stored access token for an account if available."""
    if not email:
        return None
    data = load_all_account_tokens()
    norm = email.strip().lower()
    return data.get(norm)


def parse_cloud_code_quota_response(data: Dict[str, Any], email: Optional[str] = None) -> Dict[str, Any]:
    """
    Parses Google Cloud Code retrieveUserQuotaSummary JSON payload into standardized quota structure.
    Compatible with both direct HTTPS JSON and gRPC-web JSON responses.
    """
    if not data or not isinstance(data, dict):
        return {
            "status": "EMPTY",
            "email": email,
            "weekly_remaining_pct": None,
            "five_hour_remaining_pct": None,
            "gemini": {},
            "claude_gpt": {},
            "models": {},
            "is_exhausted": False
        }

    # Unwrap nested response structures if present
    quota_resp = data.get("response", data)
    if isinstance(quota_resp, dict) and "response" in quota_resp:
        quota_resp = quota_resp["response"]

    groups = quota_resp.get("groups", [])
    if not groups and "buckets" in quota_resp:
        # Single bucket list fallback
        groups = [{"displayName": "Gemini Models", "buckets": quota_resp.get("buckets", [])}]

    gemini_group = next((g for g in groups if "gemini" in g.get("displayName", "").lower()), None)
    claude_group = next((g for g in groups if any(k in g.get("displayName", "").lower() for k in ["claude", "gpt", "other"])), None)

    def parse_bucket_group(group: Optional[Dict[str, Any]]) -> Dict[str, Any]:
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
            rem_fraction = rem.get("value") if rem.get("case") == "remainingFraction" else rem.get("remainingFraction")
            if rem_fraction is None and "remainingFraction" in bucket:
                rem_fraction = bucket["remainingFraction"]

            rem_pct = int(round(rem_fraction * 100)) if rem_fraction is not None else None
            desc = bucket.get("description", "")
            reset_ts = bucket.get("resetTime", {})
            if isinstance(reset_ts, dict):
                reset_sec = reset_ts.get("seconds")
            elif isinstance(reset_ts, (int, float)):
                reset_sec = int(reset_ts)
            else:
                reset_sec = None

            if bucket.get("disabled", False):
                res["disabled"] = True

            ref_m = re.search(r'refresh in\s+([^.\n]+)', desc, re.IGNORECASE)
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

    # Models data
    models_data = {}
    model_configs = (data.get("userStatus", {}).get("cascadeModelConfigData", {}).get("clientModelConfigs", []))
    for m_cfg in model_configs:
        m_id = m_cfg.get("modelId", "")
        q_info = m_cfg.get("quotaInfo", {})
        if m_id and q_info:
            models_data[m_id] = {
                "label": m_cfg.get("label", m_id),
                "remaining_fraction": q_info.get("remainingFraction"),
                "reset_time": (q_info.get("resetTime") or {}).get("seconds") if isinstance(q_info.get("resetTime"), dict) else q_info.get("resetTime"),
                "disabled": m_cfg.get("disabled", False)
            }

    g_5h = gemini_data.get("five_hour_remaining_pct")
    g_wk = gemini_data.get("weekly_remaining_pct")
    effective_5h = g_5h if g_5h is not None else g_wk
    is_ex = (effective_5h is not None and effective_5h <= 0) or (g_wk is not None and g_wk <= 0)

    return {
        "status": "OK",
        "email": email,
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


def query_cloud_code_quota_direct(
    access_token: Optional[str] = None,
    user_agent: str = DEFAULT_USER_AGENT,
    endpoint: Optional[str] = None,
    timeout: float = 6.0,
    email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Direct HTTPS query to Google Cloud Code retrieveUserQuotaSummary endpoint.
    Guarantees Capa 1 decoupling: queries Google Cloud Code directly via HTTPS
    with strict 'User-Agent: antigravity/1.11.5 windows/amd64'.
    Zero UI interruption, zero Electron dependency.
    """
    target_endpoint = endpoint or CLOUD_CODE_ENDPOINT
    headers = {
        "User-Agent": user_agent,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token.strip()}"

    req = urllib.request.Request(
        target_endpoint,
        data=b"{}",
        headers=headers,
        method="POST"
    )

    ctx = _get_ssl_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            result = parse_cloud_code_quota_response(payload, email=email)
            result["endpoint_used"] = target_endpoint
            return result

    except urllib.error.HTTPError as he:
        err_body = ""
        try:
            err_body = he.read().decode("utf-8", errors="replace")
        except Exception:
            pass

        if he.code == 401:
            logger.debug(f"[Capa 1] HTTP 401 Unauthenticated on {target_endpoint} (Token required or expired)")
            return {
                "status": "UNAUTHENTICATED",
                "code": 401,
                "message": "OAuth access token missing or expired",
                "email": email,
                "endpoint_used": target_endpoint,
                "raw_error": err_body,
                "is_exhausted": False
            }
        elif he.code == 403:
            return {
                "status": "FORBIDDEN",
                "code": 403,
                "message": "Access forbidden for this account or project",
                "email": email,
                "endpoint_used": target_endpoint,
                "raw_error": err_body,
                "is_exhausted": False
            }
        elif he.code == 429:
            return {
                "status": "RATE_LIMITED",
                "code": 429,
                "message": "Rate limit exceeded on Google Cloud Code API",
                "email": email,
                "endpoint_used": target_endpoint,
                "is_exhausted": True
            }
        else:
            return {
                "status": "HTTP_ERROR",
                "code": he.code,
                "message": f"HTTP {he.code}: {he.reason}",
                "email": email,
                "endpoint_used": target_endpoint,
                "is_exhausted": False
            }

    except urllib.error.URLError as ue:
        # Fallback to secondary endpoint if daily/prod has DNS or connection issue
        if target_endpoint != CLOUD_CODE_FALLBACK_ENDPOINT and not endpoint:
            logger.debug(f"Retrying on fallback endpoint: {CLOUD_CODE_FALLBACK_ENDPOINT}")
            return query_cloud_code_quota_direct(
                access_token=access_token,
                user_agent=user_agent,
                endpoint=CLOUD_CODE_FALLBACK_ENDPOINT,
                timeout=timeout,
                email=email
            )
        return {
            "status": "NETWORK_ERROR",
            "message": str(ue.reason),
            "email": email,
            "endpoint_used": target_endpoint,
            "is_exhausted": False
        }

    except Exception as exc:
        return {
            "status": "EXCEPTION",
            "message": str(exc),
            "email": email,
            "endpoint_used": target_endpoint,
            "is_exhausted": False
        }


def monitor_accounts_parallel(
    accounts: Optional[List[str]] = None,
    tokens: Optional[Dict[str, str]] = None,
    max_workers: int = 4
) -> Dict[str, Dict[str, Any]]:
    """
    Capa 1: Monitoreo desacoplado en paralelo de todas las cuentas configuradas
    sin tocar Antigravity ni cambiar de cuenta en la UI.
    
    Para cada cuenta:
    1. Si cuenta con token OAuth disponible (en disco o parámetro), consulta directamente
       Google Cloud Code HTTPS con User-Agent: antigravity/1.11.5 windows/amd64.
    2. Si no tiene token directo, utiliza el modelo predictivo de ETA y estado persistente
       en token_memory para mantener actualizadas las cuotas en segundo plano.
    3. Si la cuenta reporta cuota en vivo, actualiza el snapshot persistente.
    """
    if accounts is None:
        try:
            from config_manager import get_authorized_emails
            target_accounts = get_authorized_emails()
        except Exception:
            target_accounts = [
                "atteelsidas@gmail.com",
                "delsidasatte@gmail.com",
                "gilsamaniego12m@gmail.com",
                "tom12bryan@gmail.com"
            ]
    else:
        target_accounts = accounts

    token_map = dict(tokens or {})
    disk_tokens = load_all_account_tokens()
    for acc, tok in disk_tokens.items():
        if acc not in token_map:
            token_map[acc] = tok

    results: Dict[str, Dict[str, Any]] = {}

    def fetch_account_quota(acc_email: str) -> Tuple[str, Dict[str, Any]]:
        norm_email = acc_email.strip().lower()
        token = token_map.get(norm_email)

        # 1. Direct HTTPS query if token exists
        if token:
            res = query_cloud_code_quota_direct(access_token=token, email=norm_email)
            if res.get("status") == "OK":
                try:
                    from token_memory import update_account_snapshot
                    update_account_snapshot(
                        email=norm_email,
                        weekly_pct=res.get("weekly_remaining_pct"),
                        five_hour_pct=res.get("five_hour_remaining_pct"),
                        weekly_refresh_text=res.get("weekly_refresh_text"),
                        five_hour_refresh_text=res.get("five_hour_refresh_text"),
                        weekly_reset_time=res.get("weekly_reset_time"),
                        five_hour_reset_time=res.get("five_hour_reset_time"),
                        gemini_data=res.get("gemini"),
                        claude_data=res.get("claude_gpt"),
                        models_data=res.get("models")
                    )
                except Exception as ex:
                    logger.debug(f"Failed to update token memory snapshot for {norm_email}: {ex}")
                return norm_email, res

        # 2. Reconstructed effective quota from token_memory countdown model
        try:
            from token_memory import get_effective_account_status
            st = get_effective_account_status(norm_email)
            st["status"] = "RECONSTRUCTED_COUNTDOWN"
            st["email"] = norm_email
            return norm_email, st
        except Exception as ex:
            return norm_email, {
                "status": "FALLBACK_ERROR",
                "message": str(ex),
                "email": norm_email,
                "is_exhausted": False
            }

    with ThreadPoolExecutor(max_workers=min(max_workers, len(target_accounts) or 1)) as executor:
        future_map = {executor.submit(fetch_account_quota, email): email for email in target_accounts}
        for future in as_completed(future_map):
            acc_email, quota_info = future.result()
            results[acc_email] = quota_info

    return results
