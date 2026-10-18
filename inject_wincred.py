import ctypes, ctypes.wintypes as wt, json, sys, os, time
from datetime import datetime, timezone

class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wt.DWORD), ("dwHighDateTime", wt.DWORD)]

class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wt.DWORD),
        ("Type", wt.DWORD),
        ("TargetName", wt.LPWSTR),
        ("Comment", wt.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wt.LPWSTR),
        ("UserName", wt.LPWSTR),
    ]

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wt.DWORD]
advapi32.CredWriteW.restype = wt.BOOL
advapi32.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
advapi32.CredReadW.restype = wt.BOOL
advapi32.CredFree.argtypes = [ctypes.c_void_p]

def cred_read_utf8(target="gemini:antigravity"):
    pcred = ctypes.POINTER(CREDENTIALW)()
    if not advapi32.CredReadW(target, 1, 0, ctypes.byref(pcred)):
        return None
    try:
        c = pcred.contents
        raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        return raw.decode("utf-8")
    except Exception:
        return None
    finally:
        advapi32.CredFree(pcred)

def cred_write_utf8(json_str, target="gemini:antigravity", username="antigravity"):
    raw = json_str.encode("utf-8")
    buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = None
    cred.CredentialBlobSize = len(raw)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = username
    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(f"CredWriteW failed with error {ctypes.get_last_error()}")

def inject_profile_token(profile_alias_or_email):
    # Find profile oauth_creds.json or account_tokens.json
    homedir = os.path.expanduser("~")
    alias = profile_alias_or_email.strip().lower()
    
    # Map email to alias if needed
    alias_map = {
        "primary.dev@gmail.com": "primary_dev",
        "backup.worker@gmail.com": "backup_worker",
        "reviewer_pro@gmail.com": "reviewer_pro",
        "qa_engineer@gmail.com": "qa_engineer",
        "devops_runner@gmail.com": "devops_runner",
        "data_analyst@gmail.com": "data_analyst",
        "ai.architect@gmail.com": "ai_architect"
    }
    target_alias = alias_map.get(alias, alias)
    
    creds_path = os.path.join(homedir, ".gemini", "profiles", target_alias, ".gemini", "oauth_creds.json")
    creds = None
    if os.path.exists(creds_path):
        with open(creds_path, "r", encoding="utf-8") as f:
            creds = json.load(f)
            
    if not creds:
        # Fallback to account_tokens.json
        candidate_token_paths = [
            os.path.join(homedir, ".gemini", "account_tokens.json"),
        ]
        tokens_path = next((p for p in candidate_token_paths if os.path.exists(p)), candidate_token_paths[0])
        if os.path.exists(tokens_path):
            with open(tokens_path, "r", encoding="utf-8") as f:
                store = json.load(f)
                email_key = None
                for k in store:
                    if k.lower() == alias or alias_map.get(k.lower()) == alias:
                        email_key = k
                        break
                if email_key:
                    tok = store[email_key]
                    if isinstance(tok, str):
                        creds = {"access_token": tok, "verified_email": email_key}
                    elif isinstance(tok, dict):
                        creds = tok

    if not creds or not creds.get("access_token"):
        raise ValueError(f"No credentials found for {profile_alias_or_email}")

    now_ms = int(time.time() * 1000)
    expiry_ms = int(creds.get("expiry_date") or 0)
    if not expiry_ms or expiry_ms <= now_ms:
        expiry_ms = now_ms + 3600000
    expiry_iso = datetime.fromtimestamp(expiry_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    payload = {
        "token": {
            "access_token": creds["access_token"],
            "token_type": creds.get("token_type") or "Bearer",
            "refresh_token": creds.get("refresh_token") or "",
            "expiry": expiry_iso,
        },
        "auth_method": "consumer",
        "id_token": creds.get("id_token") or "",
    }
    json_str = json.dumps(payload, separators=(",", ":"))
    cred_write_utf8(json_str)
    
    # Also update token_memory active_account
    candidate_mem_files = [
        os.path.join(homedir, ".gemini", "token_memory.json"),
    ]
    for mem_file in candidate_mem_files:
        if os.path.exists(mem_file):
            try:
                with open(mem_file, "r", encoding="utf-8") as f:
                    mem = json.load(f)
                # Find matching email
                matched_email = None
                for email in alias_map:
                    if alias_map[email] == target_alias or email == alias:
                        matched_email = email
                        break
                if matched_email:
                    mem["active_account"] = matched_email
                    with open(mem_file, "w", encoding="utf-8") as f:
                        json.dump(mem, f, indent=2)
            except Exception as e:
                sys.stderr.write(f"Note on token_memory sync: {e}\n")

    return target_alias, creds.get("verified_email") or alias

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
        a, em = inject_profile_token(target)
        print(f"INJECTED: {a} ({em})")
    else:
        print("Usage: python inject_wincred.py <alias_or_email>")
