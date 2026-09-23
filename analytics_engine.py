"""
Analytics Engine: Token Burn-Rate Tracking & Depletion Forecasting
Tracks real-time consumption velocity (% per hour / % per minute),
estimates time to depletion (ETD), and records historical rotation cycles.
"""

import os
import json
import logging
import hashlib
import copy
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("AnalyticsEngine")

STATE_DIR = os.path.expandvars(r"%USERPROFILE%\.openclaw\workspace\state\antigravity_controller")
ANALYTICS_FILE = os.path.join(STATE_DIR, "analytics_history.json")
os.makedirs(STATE_DIR, exist_ok=True)

MAX_HISTORY_SAMPLES = 200

_cached_analytics: Optional[Dict[str, Any]] = None
_cached_analytics_mtime: float = 0.0
_last_analytics_hash: Optional[str] = None

def _compute_analytics_hash(data: Dict[str, Any]) -> str:
    """Computes a lightweight hash of actual analytics payload."""
    payload = {
        "total_rotations": data.get("total_rotations", 0),
        "samples_count": len(data.get("samples", [])),
        "last_sample": data.get("samples", [])[-1] if data.get("samples") else None
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.md5(raw).hexdigest()

def _default_analytics_factory() -> Dict[str, Any]:
    return {
        "updated_at": None,
        "total_rotations": 0,
        "samples": []
    }

def load_analytics_data(force_reload: bool = False) -> Dict[str, Any]:
    """Loads analytics history and cycle stats from disk with mtime caching and corrupt recovery."""
    global _cached_analytics, _cached_analytics_mtime, _last_analytics_hash

    if not force_reload and _cached_analytics is not None and os.path.exists(ANALYTICS_FILE):
        try:
            mtime = os.path.getmtime(ANALYTICS_FILE)
            if mtime == _cached_analytics_mtime:
                return copy.deepcopy(_cached_analytics)
        except Exception:
            pass

    from atomic_state import SafeJsonStore
    data = SafeJsonStore.load_json(ANALYTICS_FILE, _default_analytics_factory)
    _cached_analytics = copy.deepcopy(data)
    _cached_analytics_mtime = os.path.getmtime(ANALYTICS_FILE) if os.path.exists(ANALYTICS_FILE) else 0.0
    _last_analytics_hash = _compute_analytics_hash(data)
    return data

def save_analytics_data(data: Dict[str, Any], force: bool = False) -> bool:
    """Saves analytics data atomically to disk with dirty-checking hash and Windows retry."""
    global _cached_analytics, _cached_analytics_mtime, _last_analytics_hash
    from atomic_state import SafeJsonStore

    current_hash = _compute_analytics_hash(data)
    if not force and _last_analytics_hash == current_hash and os.path.exists(ANALYTICS_FILE):
        _cached_analytics = copy.deepcopy(data)
        return False

    data["updated_at"] = datetime.now().isoformat()
    SafeJsonStore.save_json(ANALYTICS_FILE, data)
    _cached_analytics = copy.deepcopy(data)
    _cached_analytics_mtime = os.path.getmtime(ANALYTICS_FILE) if os.path.exists(ANALYTICS_FILE) else 0.0
    _last_analytics_hash = current_hash
    return True

def record_usage_sample(account: str, five_hour_pct: Optional[int], weekly_pct: Optional[int]) -> Dict[str, Any]:
    """Records a new timestamped quota sample for burn-rate calculations."""
    if five_hour_pct is None and weekly_pct is None:
        return {}
        
    data = load_analytics_data()
    now_dt = datetime.now()
    now = now_dt.isoformat()
    
    sample = {
        "timestamp": now,
        "account": account.strip().lower(),
        "five_hour_pct": five_hour_pct,
        "weekly_pct": weekly_pct
    }
    
    # Avoid recording duplicate consecutive samples and unnecessary disk writes if values are identical
    if data["samples"]:
        last = data["samples"][-1]
        if (last["account"] == sample["account"] and 
            last["five_hour_pct"] == sample["five_hour_pct"] and 
            last["weekly_pct"] == sample["weekly_pct"]):
            try:
                last_dt = datetime.fromisoformat(last["timestamp"])
                # Throttle disk update on identical readings to at most once per 180 seconds
                if (now_dt - last_dt).total_seconds() < 180:
                    return sample
            except Exception:
                pass
            last["timestamp"] = now
            save_analytics_data(data)
            return sample
            
    data["samples"].append(sample)
    if len(data["samples"]) > MAX_HISTORY_SAMPLES:
        data["samples"] = data["samples"][-MAX_HISTORY_SAMPLES:]
        
    save_analytics_data(data)
    return sample

def record_rotation_event(from_account: str, to_account: str):
    """Increments total rotations counter and records an event entry."""
    data = load_analytics_data()
    data["total_rotations"] = data.get("total_rotations", 0) + 1
    save_analytics_data(data)

def calculate_burn_rate(account: str, window_minutes: int = 30) -> Dict[str, Any]:
    """
    Calculates the token consumption velocity (% consumed per hour and per minute)
    for a given account over a sliding window.
    """
    data = load_analytics_data()
    norm = account.strip().lower()
    now = datetime.now()
    cutoff = now - timedelta(minutes=window_minutes)
    
    # Filter samples for this account within the window
    account_samples = []
    for s in data["samples"]:
        if norm in s["account"]:
            try:
                t = datetime.fromisoformat(s["timestamp"])
                if t >= cutoff:
                    account_samples.append((t, s))
            except Exception:
                pass
                
    if len(account_samples) < 2:
        return {
            "account": account,
            "burn_rate_pct_per_hour": 0.0,
            "burn_rate_pct_per_min": 0.0,
            "estimated_minutes_remaining": None,
            "status": "Sin datos suficientes (en reposo)"
        }
        
    first_time, first_s = account_samples[0]
    last_time, last_s = account_samples[-1]
    
    time_diff_sec = (last_time - first_time).total_seconds()
    if time_diff_sec < 60:  # Less than 1 minute span
        return {
            "account": account,
            "burn_rate_pct_per_hour": 0.0,
            "burn_rate_pct_per_min": 0.0,
            "estimated_minutes_remaining": None,
            "status": "Intervalo muy corto"
        }
        
    pct_start = first_s["five_hour_pct"]
    pct_end = last_s["five_hour_pct"]
    
    if pct_start is None or pct_end is None:
        return {
            "account": account,
            "burn_rate_pct_per_hour": 0.0,
            "burn_rate_pct_per_min": 0.0,
            "estimated_minutes_remaining": None,
            "status": "Valores indeterminados"
        }
        
    # Consumption is decrease in percentage
    pct_consumed = max(0, pct_start - pct_end)
    hours = time_diff_sec / 3600.0
    burn_per_hour = round(pct_consumed / hours, 1) if hours > 0 else 0.0
    burn_per_min = round(burn_per_hour / 60.0, 3)
    
    est_mins = None
    if burn_per_min > 0 and pct_end > 0:
        est_mins = int(round(pct_end / burn_per_min))
        
    status = "Activo" if burn_per_hour > 0 else "En reposo"
    
    return {
        "account": account,
        "current_5h_pct": pct_end,
        "burn_rate_pct_per_hour": burn_per_hour,
        "burn_rate_pct_per_min": burn_per_min,
        "estimated_minutes_remaining": est_mins,
        "window_analyzed_minutes": int(round(time_diff_sec / 60.0)),
        "status": status
    }

def format_analytics_report(account: str) -> str:
    """Generates a human-readable CLI / Discord-ready analytics text box."""
    metrics = calculate_burn_rate(account)
    data = load_analytics_data()
    
    lines = [
        "------------------------------------------------------------------------",
        " [STATS] ANALITICAS DE CONSUMO PREDICTIVO (BURN-RATE):",
        f"   - Cuenta Analizada:     {account}",
        f"   - Estado de Consumo:    {metrics['status']}",
        f"   - Velocidad de Gasto:   {metrics['burn_rate_pct_per_hour']}% / hora ({metrics['burn_rate_pct_per_min']}% / min)"
    ]
    
    if metrics["estimated_minutes_remaining"] is not None:
        hrs = metrics["estimated_minutes_remaining"] // 60
        mins = metrics["estimated_minutes_remaining"] % 60
        time_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins} minutos"
        lines.append(f"   - Tiempo Est. Agotamiento: ~{time_str} de trabajo continuo")
    else:
        lines.append("   - Tiempo Est. Agotamiento: Indeterminado (consumo bajo/nulo)")
        
    lines.append(f"   - Rotaciones Totales:    {data.get('total_rotations', 0)} ciclos completados")
    lines.append("------------------------------------------------------------------------")
    return "\n".join(lines)

if __name__ == "__main__":
    import sys
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        from config_manager import get_authorized_emails
        sample_email = get_authorized_emails()[0]
    except Exception:
        sample_email = "primary.pro@gmail.com"
    record_usage_sample(sample_email, 94, 86)
    print(format_analytics_report(sample_email))
