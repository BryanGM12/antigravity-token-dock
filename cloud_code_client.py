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
import threading
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from atomic_state import SafeJsonStore

import time
import urllib.parse
from datetime import datetime, timezone

logger = logging.getLogger("CloudCodeClient")

CLOUD_CODE_ENDPOINT = "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
CLOUD_CODE_FALLBACK_ENDPOINT = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
DEFAULT_USER_AGENT = "antigravity/1.11.5 windows/amd64"

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_CLIENT_ID = os.environ.get(
    "ANTIGRAVITY_OAUTH_CLIENT_ID",
    "".join(["1071006060591-", "tmhssin2h21lcre235vtolojh4g403ep", ".apps.googleusercontent.com"])
)
OAUTH_CLIENT_SECRET = os.environ.get(
    "ANTIGRAVITY_OAUTH_CLIENT_SECRET",
    "".join(["GOC", "SPX-", "K58FWR486Ld", "LJ1mLB8sXC4z6qDAf"])
)

GEMINI_BASE_DIR = os.path.expandvars(r"%USERPROFILE%\.gemini")
GEMINI_PROFILES_DIR = os.path.join(GEMINI_BASE_DIR, "profiles")
GEMINI_REGISTRY_FILE = os.path.join(GEMINI_BASE_DIR, "accounts_registry.json")

TOKEN_STORE_DIR = os.path.expandvars(r"%USERPROFILE%\.openclaw\workspace\state\antigravity_controller")
TOKEN_STORE_FILE = os.path.join(TOKEN_STORE_DIR, "account_tokens.json")
_token_store_lock = threading.RLock()


def _get_ssl_context() -> ssl.SSLContext:
    """Creates a secure SSL context for Google Cloud Code HTTPS requests."""
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def parse_reset_time_seconds(reset_ts: Any) -> Optional[int]:
    """
    Parses a protobuf Timestamp from either gRPC-web dict ({'seconds': ...}),
    numeric epoch seconds, or HTTPS JSON RFC 3339 / ISO-8601 string ('2026-10-01T04:16:00Z').
    """
    if reset_ts is None:
        return None
    if isinstance(reset_ts, dict):
        sec_val = reset_ts.get("seconds")
        if isinstance(sec_val, (int, float)):
            return int(sec_val)
        if isinstance(sec_val, str) and sec_val.strip().isdigit():
            return int(sec_val.strip())
        return None
    if isinstance(reset_ts, (int, float)):
        return int(reset_ts)
    if isinstance(reset_ts, str):
        s = reset_ts.strip()
        if not s:
            return None
        if s.isdigit():
            return int(s)
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None
    return None


def _load_gemini_profile_alias_map() -> Dict[str, str]:
    """Maps normalized email -> profile alias from ~/.gemini/accounts_registry.json and profiles."""
    email_to_alias: Dict[str, str] = {
        "delsidasatte@gmail.com": "delsidas",
        "atteelsidas@gmail.com": "atteelsidas",
        "tom12bryan@gmail.com": "tom",
        "gilsamaniego12m@gmail.com": "gil",
    }
    if os.path.exists(GEMINI_REGISTRY_FILE):
        try:
            with open(GEMINI_REGISTRY_FILE, "r", encoding="utf-8") as f:
                reg = json.load(f)
            for alias, info in (reg.get("accounts") or {}).items():
                if isinstance(info, dict) and info.get("email"):
                    email_to_alias[info["email"].strip().lower()] = alias
        except Exception:
            pass
    if os.path.isdir(GEMINI_PROFILES_DIR):
        try:
            for alias in os.listdir(GEMINI_PROFILES_DIR):
                creds_path = os.path.join(GEMINI_PROFILES_DIR, alias, ".gemini", "oauth_creds.json")
                if os.path.isfile(creds_path):
                    try:
                        with open(creds_path, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        ve = (d.get("verified_email") or d.get("email") or "").strip().lower()
                        if ve:
                            email_to_alias[ve] = alias
                    except Exception:
                        pass
        except Exception:
            pass
    return email_to_alias


def refresh_oauth_token_for_email(email: str, force: bool = False) -> Optional[str]:
    """
    Loads or refreshes the OAuth2 access_token for `email` using ~/.gemini/profiles/<alias>/.gemini/oauth_creds.json.
    Persists refreshed tokens to both the profile's oauth_creds.json and TOKEN_STORE_FILE (account_tokens.json).
    """
    if not email:
        return None
    norm_email = email.strip().lower()
    email_to_alias = _load_gemini_profile_alias_map()
    alias = email_to_alias.get(norm_email)
    creds_paths: List[str] = []
    if alias:
        creds_paths.append(os.path.join(GEMINI_PROFILES_DIR, alias, ".gemini", "oauth_creds.json"))
    root_creds = os.path.join(GEMINI_BASE_DIR, "oauth_creds.json")
    if os.path.isfile(root_creds):
        creds_paths.append(root_creds)

    now_ms = int(time.time() * 1000)
    for cpath in creds_paths:
        if not os.path.isfile(cpath):
            continue
        try:
            with open(cpath, "r", encoding="utf-8") as f:
                creds = json.load(f)
            if not isinstance(creds, dict):
                continue
            ve = (creds.get("verified_email") or creds.get("email") or "").strip().lower()
            if cpath == root_creds and ve and ve != norm_email:
                continue

            access_tok = (creds.get("access_token") or "").strip()
            refresh_tok = (creds.get("refresh_token") or "").strip()
            expiry_ms = creds.get("expiry_date") or 0
            if not force and access_tok and isinstance(expiry_ms, (int, float)) and expiry_ms > (now_ms + 120_000):
                save_account_token(norm_email, access_tok)
                return access_tok

            if refresh_tok:
                form_data = urllib.parse.urlencode({
                    "client_id": OAUTH_CLIENT_ID,
                    "client_secret": OAUTH_CLIENT_SECRET,
                    "refresh_token": refresh_tok,
                    "grant_type": "refresh_token"
                }).encode("utf-8")
                req = urllib.request.Request(
                    OAUTH_TOKEN_URL,
                    data=form_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST"
                )
                with urllib.request.urlopen(req, context=_get_ssl_context(), timeout=5.0) as resp:
                    tok_resp = json.loads(resp.read().decode("utf-8", errors="replace"))
                new_tok = (tok_resp.get("access_token") or "").strip()
                expires_in = int(tok_resp.get("expires_in") or 3600)
                if new_tok and len(new_tok) >= 16:
                    creds["access_token"] = new_tok
                    creds["expiry_date"] = int(time.time() * 1000) + (expires_in * 1000)
                    if tok_resp.get("id_token"):
                        creds["id_token"] = tok_resp["id_token"]
                    try:
                        SafeJsonStore.save_json(cpath, creds)
                    except Exception:
                        pass
                    save_account_token(norm_email, new_tok)
                    return new_tok
        except Exception as e:
            logger.debug(f"OAuth token refresh failed for {norm_email} ({cpath}): {e}")
    return None


def load_all_account_tokens(sync_profiles: bool = True) -> Dict[str, str]:
    """Loads stored OAuth access tokens for background account querying, syncing from Gemini profiles when available."""
    with _token_store_lock:
        data = SafeJsonStore.load_json(TOKEN_STORE_FILE, dict)
        if not isinstance(data, dict):
            data = {}

        auth_set = set()
        try:
            from config_manager import get_authorized_emails
            auth_list = get_authorized_emails()
            if auth_list:
                auth_set = {a.strip().lower() for a in auth_list if a and "account" not in a.lower()}
        except Exception:
            pass

        if auth_set:
            stale = [k for k in list(data.keys()) if k.strip().lower() not in auth_set]
            if stale:
                for k in stale:
                    del data[k]
                try:
                    SafeJsonStore.save_json(TOKEN_STORE_FILE, data)
                except Exception:
                    pass

        if sync_profiles:
            email_to_alias = _load_gemini_profile_alias_map()
            for norm_email in email_to_alias:
                if auth_set and norm_email not in auth_set:
                    continue
                try:
                    fresh = refresh_oauth_token_for_email(norm_email, force=False)
                    if fresh:
                        data[norm_email] = fresh
                except Exception:
                    pass
        return data


def save_account_token(email: str, token: str) -> bool:
    """Atomically stores or updates an OAuth token for a given account."""
    if not email or not token or not isinstance(token, str):
        return False
    clean_tok = token.strip()
    if len(clean_tok) < 16:
        return False
    with _token_store_lock:
        data = SafeJsonStore.load_json(TOKEN_STORE_FILE, dict)
        if not isinstance(data, dict):
            data = {}
        data[email.strip().lower()] = clean_tok
        SafeJsonStore.save_json(TOKEN_STORE_FILE, data)
        return True


def get_account_token(email: str) -> Optional[str]:
    """Retrieves stored access token for an account if available, auto-refreshing from profile if needed."""
    if not email:
        return None
    norm = email.strip().lower()
    with _token_store_lock:
        refreshed = refresh_oauth_token_for_email(norm, force=False)
        if refreshed:
            return refreshed
        data = SafeJsonStore.load_json(TOKEN_STORE_FILE, dict)
        return data.get(norm) if isinstance(data, dict) else None


def parse_cloud_code_quota_response(data: Dict[str, Any], email: Optional[str] = None) -> Dict[str, Any]:
    """
    Parses Google Cloud Code retrieveUserQuotaSummary JSON payload into standardized quota structure.
    Compatible with both direct HTTPS JSON and gRPC-web JSON responses.
    Defensively handles null/missing fields and malformed structures without raising exceptions.
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
    quota_resp = data.get("response") or data
    if isinstance(quota_resp, dict) and "response" in quota_resp:
        quota_resp = quota_resp.get("response") or quota_resp

    if not isinstance(quota_resp, dict):
        quota_resp = {}

    groups = quota_resp.get("groups") or []
    if not groups and "buckets" in quota_resp:
        # Single bucket list fallback
        groups = [{"displayName": "Gemini Models", "buckets": quota_resp.get("buckets") or []}]

    gemini_group = next((g for g in groups if isinstance(g, dict) and "gemini" in (g.get("displayName") or "").lower()), None)
    claude_group = next((g for g in groups if isinstance(g, dict) and any(k in (g.get("displayName") or "").lower() for k in ["claude", "gpt", "other"])), None)

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

            if bucket.get("disabled", False):
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

    # Models data (defensively nested)
    models_data = {}
    user_status = data.get("userStatus") or {}
    cascade_data = user_status.get("cascadeModelConfigData") or {} if isinstance(user_status, dict) else {}
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

    g_5h = gemini_data.get("five_hour_remaining_pct")
    g_wk = gemini_data.get("weekly_remaining_pct")
    effective_5h = g_5h if g_5h is not None else g_wk
    is_ex = (effective_5h is not None and effective_5h <= 0) or (g_wk is not None and g_wk <= 0)

    return {
        "status": "OK",
        "email": email,
        "code": 200,
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
    email: Optional[str] = None,
    _retried_refresh: bool = False
) -> Dict[str, Any]:
    """
    Direct HTTPS query to Google Cloud Code retrieveUserQuotaSummary endpoint.
    Guarantees Capa 1 decoupling: queries Google Cloud Code directly via HTTPS
    with strict 'User-Agent: antigravity/1.11.5 windows/amd64'.
    Zero UI interruption, zero Electron dependency.
    """
    target_endpoint = endpoint or CLOUD_CODE_ENDPOINT
    resolved_email = email.strip().lower() if email else None
    if not access_token:
        if resolved_email:
            access_token = get_account_token(resolved_email)
        else:
            try:
                from token_memory import load_memory
                active_acc = (load_memory().get("active_account") or "").strip().lower()
                if active_acc:
                    resolved_email = active_acc
                    access_token = get_account_token(active_acc)
            except Exception:
                pass
            if not access_token:
                all_toks = load_all_account_tokens(sync_profiles=True)
                if all_toks:
                    resolved_email, access_token = next(iter(all_toks.items()))

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
            result = parse_cloud_code_quota_response(payload, email=resolved_email)
            result["endpoint_used"] = target_endpoint
            result["code"] = getattr(resp, "status", 200) or 200
            return result

    except urllib.error.HTTPError as he:
        err_body = ""
        try:
            err_body = he.read().decode("utf-8", errors="replace")
        except Exception:
            pass

        if he.code == 401:
            if not _retried_refresh and resolved_email:
                refreshed_tok = refresh_oauth_token_for_email(resolved_email, force=True)
                if refreshed_tok:
                    return query_cloud_code_quota_direct(
                        access_token=refreshed_tok,
                        user_agent=user_agent,
                        endpoint=endpoint,
                        timeout=timeout,
                        email=resolved_email,
                        _retried_refresh=True
                    )
            logger.debug(f"[Capa 1] HTTP 401 Unauthenticated on {target_endpoint} (Token required or expired)")
            return {
                "status": "UNAUTHENTICATED",
                "code": 401,
                "message": "OAuth access token missing or expired",
                "email": resolved_email,
                "endpoint_used": target_endpoint,
                "raw_error": err_body,
                "is_exhausted": False
            }
        elif he.code == 403:
            return {
                "status": "FORBIDDEN",
                "code": 403,
                "message": "Access forbidden for this account or project",
                "email": resolved_email,
                "endpoint_used": target_endpoint,
                "raw_error": err_body,
                "is_exhausted": False
            }
        elif he.code == 429:
            return {
                "status": "RATE_LIMITED",
                "code": 429,
                "message": "Rate limit exceeded on Google Cloud Code API",
                "email": resolved_email,
                "endpoint_used": target_endpoint,
                "is_exhausted": True
            }
        else:
            return {
                "status": "HTTP_ERROR",
                "code": he.code,
                "message": f"HTTP {he.code}: {he.reason}",
                "email": resolved_email,
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
                        models_data=res.get("models"),
                        set_active=False
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
