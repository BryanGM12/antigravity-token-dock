#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini Autonomous Multi-Account Pool & Auto-Failover Balancer
============================================================
100% Autonomous, Zero-Manual, Zero-Collisions Account Router across all 7 accounts.

Features:
- Dynamically loads all 7 Pro accounts from accounts_registry.json.
- Automatically refreshes expired OAuth access_tokens before probing quota.
- Continuously probes real-time 5-hour and weekly quota for all 7 accounts.
- Automatically selects the account with the highest available 5h capacity.
- Performs zero-latency profile switching (environment, active_account.json, root creds, keytar).
- Provides instant failover if any account encounters rate limits or quota exhaustion.
- Syncs with Orca status bar for decoupled, real-time live monitoring.
"""

import getpass
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

GEMINI_DIR = Path.home() / ".gemini"
PROFILES_DIR = GEMINI_DIR / "profiles"
ACTIVE_FILE = GEMINI_DIR / "active_account.json"
REGISTRY_FILE = GEMINI_DIR / "accounts_registry.json"
CACHE_FILE = GEMINI_DIR / "pool_status.json"
GEMINI_TOKENS_FILE = GEMINI_DIR / "account_tokens.json"

DEFAULT_PRO_ACCOUNTS = [
    "primary_dev",
    "backup_worker",
    "ai_architect",
    "reviewer_pro",
    "qa_engineer",
    "devops_runner",
    "data_analyst",
]

OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
if not OAUTH_CLIENT_ID or not OAUTH_CLIENT_SECRET:
    _cfg = Path.home() / ".gemini" / "oauth_credentials.json"
    if _cfg.exists():
        try:
            with open(_cfg, "r", encoding="utf-8") as _f:
                _data = json.load(_f)
                OAUTH_CLIENT_ID = _data.get("client_id", "")
                OAUTH_CLIENT_SECRET = _data.get("client_secret", "")
        except Exception:
            pass
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

CACHE_TTL_SEC = 45


def get_pro_accounts():
    accounts = list(DEFAULT_PRO_ACCOUNTS)
    if REGISTRY_FILE.exists():
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                reg = json.load(f).get("accounts", {})
                for alias in reg.keys():
                    a_low = alias.lower()
                    if a_low not in accounts:
                        accounts.append(a_low)
        except Exception:
            pass
    return accounts


def refresh_oauth_token(refresh_token):
    data = urllib.parse.urlencode({
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": OAUTH_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        now_ms = int(time.time() * 1000)
        expires_in = int(res.get("expires_in", 3600))
        return {
            "access_token": res["access_token"],
            "expiry_date": now_ms + expires_in * 1000,
            "token_type": res.get("token_type", "Bearer"),
            "scope": res.get("scope"),
        }


def to_mcp_credentials(tokens):
    now_ms = int(time.time() * 1000)
    return {
        "serverName": "main-account",
        "token": {
            "accessToken": tokens.get("access_token", ""),
            "refreshToken": tokens.get("refresh_token"),
            "tokenType": tokens.get("token_type", "Bearer"),
            "scope": tokens.get("scope"),
            "expiresAt": tokens.get("expiry_date") or (now_ms + 3600000),
        },
        "updatedAt": now_ms,
    }


def encrypt_file_keychain(tokens):
    hostname = socket.gethostname()
    username = getpass.getuser()
    salt = f"{hostname}-{username}-gemini-cli".encode("utf-8")
    key = hashlib.scrypt(b"gemini-cli-oauth", salt=salt, n=16384, r=8, p=1, maxmem=0, dklen=32)
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    mcp_creds = to_mcp_credentials(tokens)
    payload = {
        "gemini-cli-oauth": {
            "main-account": json.dumps(mcp_creds)
        }
    }
    plaintext = json.dumps(payload, indent=2).encode("utf-8")
    ct_tag = aesgcm.encrypt(iv, plaintext, None)
    return f"{iv.hex()}:{ct_tag[-16:].hex()}:{ct_tag[:-16].hex()}"


def decrypt_file_keychain(enc_str):
    try:
        parts = enc_str.strip().split(":")
        if len(parts) != 3:
            return None
        iv = bytes.fromhex(parts[0])
        tag = bytes.fromhex(parts[1])
        ct = bytes.fromhex(parts[2])
        hostname = socket.gethostname()
        username = getpass.getuser()
        salt = f"{hostname}-{username}-gemini-cli".encode("utf-8")
        key = hashlib.scrypt(b"gemini-cli-oauth", salt=salt, n=16384, r=8, p=1, maxmem=0, dklen=32)
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ct + tag, None)
        data = json.loads(plaintext.decode("utf-8"))
        mcp_str = data.get("gemini-cli-oauth", {}).get("main-account")
        if not mcp_str:
            return None
        mcp_creds = json.loads(mcp_str)
        tok = mcp_creds.get("token", {})
        return {
            "access_token": tok.get("accessToken"),
            "refresh_token": tok.get("refreshToken"),
            "token_type": tok.get("tokenType", "Bearer"),
            "scope": tok.get("scope"),
            "expiry_date": tok.get("expiresAt", 0),
        }
    except Exception:
        return None


def save_profile_credentials(alias, tokens):
    prof_gemini = PROFILES_DIR / alias / ".gemini"
    prof_gemini.mkdir(parents=True, exist_ok=True)
    creds_file = prof_gemini / "oauth_creds.json"
    with open(creds_file, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    try:
        enc_str = encrypt_file_keychain(tokens)
        with open(prof_gemini / "gemini-credentials.json", "w", encoding="utf-8") as wf:
            wf.write(enc_str)
    except Exception:
        pass


def get_token_for_alias(alias):
    creds_file = PROFILES_DIR / alias / ".gemini" / "oauth_creds.json"
    enc_file = PROFILES_DIR / alias / ".gemini" / "gemini-credentials.json"
    email = None
    if REGISTRY_FILE.exists():
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                email = json.load(f).get("accounts", {}).get(alias, {}).get("email")
        except Exception:
            pass

    d = None
    if creds_file.exists():
        try:
            with open(creds_file, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = None

    if not d and enc_file.exists():
        try:
            with open(enc_file, "r", encoding="utf-8") as f:
                d = decrypt_file_keychain(f.read().strip())
        except Exception:
            d = None

    if d:
        try:
            email = d.get("verified_email") or email
            access_token = d.get("access_token")
            refresh_token = d.get("refresh_token")
            expiry_ms = d.get("expiry_date", 0)
            now_ms = int(time.time() * 1000)

            if refresh_token and (not access_token or expiry_ms <= now_ms + 60000):
                try:
                    refreshed = refresh_oauth_token(refresh_token)
                    d.update(refreshed)
                    save_profile_credentials(alias, d)
                    access_token = d.get("access_token")
                    if alias == get_active_alias():
                        try:
                            with open(GEMINI_DIR / "oauth_creds.json", "w", encoding="utf-8") as wf:
                                json.dump(d, wf, indent=2)
                            enc_str = encrypt_file_keychain(d)
                            with open(GEMINI_DIR / "gemini-credentials.json", "w", encoding="utf-8") as wf:
                                wf.write(enc_str)
                            sync_keytar(d)
                        except Exception:
                            pass
                except Exception:
                    pass

            if access_token:
                return access_token, email
        except Exception:
            pass

    # Fallback to account_tokens.json if email matches
    if email and GEMINI_TOKENS_FILE.exists():
        try:
            with open(GEMINI_TOKENS_FILE, "r", encoding="utf-8") as f:
                oc_tokens = json.load(f)
                val = oc_tokens.get(email)
                if isinstance(val, str) and val.startswith("ya29."):
                    return val, email
                elif isinstance(val, dict) and val.get("access_token"):
                    return val["access_token"], email
        except Exception:
            pass

    return None, email


def query_account_quota(access_token):
    url = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/1.11.5 windows/amd64",
    }
    req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            gemini_5h_rem = None
            gemini_5h_reset = None
            gemini_weekly_rem = None
            gemini_weekly_reset = None

            # 1. Priorizar el grupo especifico de 'Gemini Models'
            for g in data.get("groups", []):
                is_gemini_group = (g.get("displayName") == "Gemini Models")
                for b in g.get("buckets", []):
                    bid = b.get("bucketId", "")
                    rem_val = b.get("remainingFraction")
                    if rem_val is None and isinstance(b.get("remaining"), dict):
                        rem_val = b.get("remaining", {}).get("value")
                    rem_float = float(rem_val) if rem_val is not None else 1.0

                    if is_gemini_group or bid in ("gemini-5h", "gemini-weekly"):
                        if bid == "gemini-5h":
                            gemini_5h_rem = rem_float
                            gemini_5h_reset = b.get("resetTime")
                        elif bid == "gemini-weekly":
                            gemini_weekly_rem = rem_float
                            gemini_weekly_reset = b.get("resetTime")

            # 2. Fallback si no vinieron buckets con prefijo gemini-
            if gemini_5h_rem is None or gemini_weekly_rem is None:
                for g in data.get("groups", []):
                    for b in g.get("buckets", []):
                        bid = b.get("bucketId", "")
                        rem_val = b.get("remainingFraction")
                        if rem_val is None and isinstance(b.get("remaining"), dict):
                            rem_val = b.get("remaining", {}).get("value")
                        rem_float = float(rem_val) if rem_val is not None else 1.0
                        if bid in ("gemini-5h", "3p-5h") and gemini_5h_rem is None:
                            gemini_5h_rem = rem_float
                            gemini_5h_reset = b.get("resetTime")
                        elif bid in ("gemini-weekly", "3p-weekly") and gemini_weekly_rem is None:
                            gemini_weekly_rem = rem_float
                            gemini_weekly_reset = b.get("resetTime")

            return {
                "ok": True,
                "gemini_5h_rem": gemini_5h_rem if gemini_5h_rem is not None else 1.0,
                "gemini_5h_reset": gemini_5h_reset,
                "gemini_weekly_rem": gemini_weekly_rem if gemini_weekly_rem is not None else 1.0,
                "gemini_weekly_reset": gemini_weekly_reset,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP_{e.code}", "gemini_5h_rem": 0.0, "gemini_5h_reset": None, "gemini_weekly_rem": 0.0, "gemini_weekly_reset": None}
    except Exception as e:
        return {"ok": False, "error": str(e), "gemini_5h_rem": 0.0, "gemini_5h_reset": None, "gemini_weekly_rem": 0.0, "gemini_weekly_reset": None}


def load_pool_cache():
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_pool_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def get_active_alias():
    if ACTIVE_FILE.exists():
        try:
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("active_alias", "primary_dev").lower()
        except Exception:
            pass
    return "primary_dev"


MIN_QUOTA_THRESHOLD = 0.05  # Regla estricta: Umbral del 5%. Cambio de cuenta cuando cuota < 5%


def update_pool_status(force_probe=False):
    cache = load_pool_cache()
    now = time.time()
    last_update = cache.get("_updated_at", 0)
    pro_accounts = get_pro_accounts()

    if not force_probe and (now - last_update) < CACHE_TTL_SEC:
        return cache

    accounts_data = cache.get("accounts", {})

    for alias in pro_accounts:
        token, email = get_token_for_alias(alias)
        if not token:
            accounts_data[alias] = {
                "email": email or "",
                "available": False,
                "reason": "missing_token",
                "rem_5h": 0.0,
                "reset_5h": None,
            }
            continue

        exhausted_until = accounts_data.get(alias, {}).get("exhausted_until", 0)
        if now < exhausted_until:
            continue

        q = query_account_quota(token)
        if q["ok"]:
            accounts_data[alias] = {
                "email": email or "",
                "available": (q["gemini_5h_rem"] >= MIN_QUOTA_THRESHOLD and q.get("gemini_weekly_rem", 1.0) >= MIN_QUOTA_THRESHOLD),
                "rem_5h": q["gemini_5h_rem"],
                "rem_weekly": q["gemini_weekly_rem"],
                "reset_5h": q["gemini_5h_reset"],
                "last_checked": now,
            }
        else:
            accounts_data[alias] = {
                "email": email or "",
                "available": False,
                "error": q["error"],
                "rem_5h": 0.0,
                "rem_weekly": 0.0,
                "reset_5h": None,
                "last_checked": now,
            }

    cache["_updated_at"] = now
    cache["accounts"] = accounts_data
    save_pool_cache(cache)
    return cache


def select_best_account(pool_cache):
    accounts = pool_cache.get("accounts", {})
    current_alias = get_active_alias()
    pro_accounts = get_pro_accounts()
    now = time.time()

    curr_data = accounts.get(current_alias, {})
    # Regla estricta: La cuenta activa se conserva UNICAMENTE si tiene >= 5% tanto en 5 horas como semanalmente
    if (curr_data.get("available", False) and 
        now >= curr_data.get("exhausted_until", 0) and
        curr_data.get("rem_5h", 0) >= MIN_QUOTA_THRESHOLD and 
        curr_data.get("rem_weekly", 0) >= MIN_QUOTA_THRESHOLD):
        return current_alias

    candidates = []
    for alias in pro_accounts:
        data = accounts.get(alias, {})
        if data.get("available", False) and now >= data.get("exhausted_until", 0):
            r5 = float(data.get("rem_5h", 0.0))
            rw = float(data.get("rem_weekly", 1.0))
            if r5 >= MIN_QUOTA_THRESHOLD and rw >= MIN_QUOTA_THRESHOLD:
                score = min(r5, rw)
                candidates.append((score, r5, rw, alias))

    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        return candidates[0][3]

    # If all accounts are in exhausted cooldown, clear cooldowns and pick highest quota >= MIN_QUOTA_THRESHOLD
    for a in pro_accounts:
        if a in accounts:
            accounts[a]["exhausted_until"] = 0
            accounts[a]["available"] = (float(accounts[a].get("rem_5h", 0)) >= MIN_QUOTA_THRESHOLD and 
                                        float(accounts[a].get("rem_weekly", 1.0)) >= MIN_QUOTA_THRESHOLD)
    pool_cache["accounts"] = accounts
    save_pool_cache(pool_cache)

    all_accs = []
    for alias in pro_accounts:
        data = accounts.get(alias, {})
        r5 = float(data.get("rem_5h", 0.0))
        rw = float(data.get("rem_weekly", 1.0))
        score = min(r5, rw)
        all_accs.append((score, r5, rw, alias))
    all_accs.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return all_accs[0][3] if all_accs else current_alias



def sync_keytar(tokens_dict):
    if not tokens_dict or not tokens_dict.get("access_token"):
        return
    mcp_creds = to_mcp_credentials(tokens_dict)
    keytar_path = (Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@google" / "gemini-cli" / "node_modules" / "@github" / "keytar").as_posix()
    js_cmd = (
        "try {"
        f"  const keytar = require({json.dumps(keytar_path)});"
        "  const payload = process.argv[1];"
        "  keytar.setPassword('gemini-cli-oauth', 'main-account', payload).then(() => process.exit(0)).catch(() => process.exit(1));"
        "} catch(e) { process.exit(0); }"
    )
    try:
        subprocess.run(
            ["node", "-e", js_cmd, json.dumps(mcp_creds)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except Exception:
        pass


def apply_active_account(alias, force=True):
    current_alias = get_active_alias()
    profile_path = PROFILES_DIR / alias
    token, email = get_token_for_alias(alias)

    if force or alias != current_alias or not (GEMINI_DIR / "oauth_creds.json").exists() or not (GEMINI_DIR / "gemini-credentials.json").exists():
        with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "active_alias": alias,
                "active_email": email or "",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, f, indent=2)

        src_creds = profile_path / ".gemini" / "oauth_creds.json"
        dst_creds = GEMINI_DIR / "oauth_creds.json"
        tokens_dict = None
        if src_creds.exists():
            try:
                shutil.copyfile(src_creds, dst_creds)
                with open(src_creds, "r", encoding="utf-8") as f:
                    tokens_dict = json.load(f)
            except Exception:
                pass

        src_enc = profile_path / ".gemini" / "gemini-credentials.json"
        dst_enc = GEMINI_DIR / "gemini-credentials.json"
        if src_enc.exists():
            try:
                shutil.copyfile(src_enc, dst_enc)
            except Exception:
                pass
        elif tokens_dict:
            try:
                enc_str = encrypt_file_keychain(tokens_dict)
                with open(src_enc, "w", encoding="utf-8") as wf:
                    wf.write(enc_str)
                with open(dst_enc, "w", encoding="utf-8") as wf:
                    wf.write(enc_str)
            except Exception:
                pass

        if email:
            try:
                with open(GEMINI_DIR / "google_accounts.json", "w", encoding="utf-8") as f:
                    json.dump({"active": email, "old": []}, f, indent=2)
            except Exception:
                pass

        if tokens_dict:
            sync_keytar(tokens_dict)

        try:
            import inject_wincred
            inject_wincred.inject_profile_token(alias)
        except Exception:
            pass

        storage_path = os.path.expandvars(r"%APPDATA%\Antigravity\app_storage.json")
        if os.path.exists(storage_path) and email:
            try:
                with open(storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["jetski.onboarding.lastLoginUsername"] = email
                data["jetski.onboarding.lastLoginIsGcpTos"] = "false"
                data["ide-install-wizard-shown"] = "true"
                with open(storage_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

        if SYNC_SCRIPT.exists():
            try:
                subprocess.Popen(
                    [sys.executable, str(SYNC_SCRIPT)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except Exception:
                pass

    return str(profile_path)


def mark_account_exhausted(alias, cooldown_sec=1800):
    cache = load_pool_cache()
    accs = cache.get("accounts", {})
    if alias in accs:
        accs[alias]["available"] = False
        accs[alias]["rem_5h"] = 0.0
        accs[alias]["exhausted_until"] = time.time() + cooldown_sec
    cache["accounts"] = accs
    save_pool_cache(cache)


def ensure_active(force_probe=False):
    cache = update_pool_status(force_probe=force_probe)
    best_alias = select_best_account(cache)
    prof_path = apply_active_account(best_alias)
    return best_alias, prof_path


def rotate_next():
    current = get_active_alias()
    mark_account_exhausted(current, cooldown_sec=3600)
    cache = update_pool_status(force_probe=True)
    best_alias = select_best_account(cache)
    prof_path = apply_active_account(best_alias)
    return best_alias, prof_path


if __name__ == "__main__":
    if "--rotate" in sys.argv:
        alias, p = rotate_next()
        print(f"ROTATED_TO:{alias}:{p}")
    elif "--apply" in sys.argv:
        idx = sys.argv.index("--apply")
        target = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else get_active_alias()
        p = apply_active_account(target)
        print(f"APPLIED:{target}:{p}")
    elif "--probe" in sys.argv:
        cache = update_pool_status(force_probe=True)
        print(json.dumps(cache, indent=2))
    elif "--mark-exhausted" in sys.argv:
        idx = sys.argv.index("--mark-exhausted")
        target = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else get_active_alias()
        mark_account_exhausted(target)
        alias, p = rotate_next()
        print(f"EXHAUSTED:{target}->NEXT:{alias}:{p}")
    else:
        force = "--force" in sys.argv
        alias, p = ensure_active(force_probe=force)
        print(f"ACTIVE:{alias}:{p}")
