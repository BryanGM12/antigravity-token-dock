"""
Local HUD: Ultra-Lightweight Web Dashboard & REST Micro-API
Serves a responsive, dark-mode real-time status dashboard on http://127.0.0.1:59123
and provides /api/status, /api/switch, and /api/settings endpoints for OpenClaw / Jarvis integration.
"""

import os
import sys
import json
import logging
import threading
import subprocess
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional

logger = logging.getLogger("LocalHUD")

HUD_PORT = 59123
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Import sibling modules
sys.path.insert(0, SCRIPT_DIR)
from token_memory import (
    load_memory, get_effective_account_status, DEFAULT_ACCOUNTS,
    is_auto_switch_enabled, set_auto_switch_enabled,
    is_sound_enabled, set_sound_enabled
)
from analytics_engine import calculate_burn_rate, load_analytics_data
from watchdog_service import run_health_audit

HTML_DASHBOARD = r"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Antigravity Controller - Live HUD</title>
  <style>
    :root {
      --bg: #0d0f12;
      --card-bg: #16191f;
      --card-border: #232730;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --purple: #a855f7;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      padding: 24px;
      display: flex;
      justify-content: center;
      min-height: 100vh;
    }
    .container {
      width: 100%;
      max-width: 960px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
      flex-wrap: wrap;
      gap: 12px;
    }
    .title-group h1 {
      font-size: 20px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.2);
      color: var(--success);
      font-weight: 500;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .btn-group {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .btn {
      background: var(--card-bg);
      color: var(--text);
      border: 1px solid var(--card-border);
      padding: 8px 14px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn:hover { background: #20242c; border-color: #3b82f6; }
    .btn-rotate {
      background: var(--accent);
      color: #fff;
      border: none;
    }
    .btn-rotate:hover { background: var(--accent-hover); }
    .btn-rotate:disabled { opacity: 0.5; cursor: not-allowed; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 16px;
      position: relative;
      transition: border-color 0.2s;
    }
    .card.active {
      border-color: var(--accent);
      box-shadow: 0 0 12px rgba(59, 130, 246, 0.15);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .acc-email {
      font-weight: 600;
      font-size: 14px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .acc-tag {
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 4px;
      font-weight: 600;
      text-transform: uppercase;
    }
    .tag-active { background: #1e3a8a; color: #93c5fd; }
    .tag-standby { background: #1f2937; color: #9ca3af; }
    .metric { margin-bottom: 10px; }
    .metric-label {
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: var(--text-muted);
      margin-bottom: 4px;
    }
    .metric-val { font-weight: 600; color: var(--text); }
    .progress-bar {
      width: 100%;
      height: 4px;
      background: #262a33;
      border-radius: 2px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      border-radius: 2px;
      transition: width 0.3s ease;
    }
    .fill-high { background: var(--success); }
    .fill-mid { background: var(--warning); }
    .fill-low { background: var(--danger); }
    
    /* Interactive Settings Modal */
    .modal-overlay {
      display: none;
      position: fixed;
      top: 0; left: 0; width: 100%; height: 100%;
      background: rgba(0, 0, 0, 0.65);
      backdrop-filter: blur(4px);
      z-index: 999;
      justify-content: center;
      align-items: center;
    }
    .modal-overlay.open { display: flex; }
    .modal-content {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      width: 90%;
      max-width: 440px;
      padding: 24px;
      box-shadow: 0 12px 36px rgba(0,0,0,0.5);
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 18px;
    }
    .modal-header h2 { font-size: 16px; font-weight: 600; }
    .btn-close {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 18px;
      cursor: pointer;
    }
    .btn-close:hover { color: var(--text); }
    .setting-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .setting-label { font-size: 13px; font-weight: 500; }
    .setting-desc { font-size: 11px; color: var(--text-muted); }
    .range-group {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .range-group span { font-size: 12px; min-width: 32px; text-align: right; }
    
    footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      color: var(--text-muted);
      border-top: 1px solid var(--card-border);
      padding-top: 16px;
      flex-wrap: wrap;
      gap: 8px;
    }
    @media (max-width: 600px) {
      body { padding: 12px; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="title-group">
        <h1>✦ Antigravity Token Hub</h1>
        <span class="badge" id="hud-status">● CONECTADO</span>
      </div>
      <div class="btn-group">
        <button class="btn" id="optionsMenu" onclick="openSettings()">⚙ Opciones</button>
        <button class="btn btn-rotate" id="btn-switch" onclick="triggerSwitch()">⇄ Rotar Cuenta</button>
      </div>
    </header>

    <div class="grid" id="accounts-grid">
      <!-- Generated dynamically -->
    </div>

    <!-- Interactive Settings Modal -->
    <div class="modal-overlay" id="settingsModal" onclick="handleBackdropClick(event)">
      <div class="modal-content">
        <div class="modal-header">
          <h2>⚙ Panel de Ajustes del Sistema</h2>
          <button class="btn-close" onclick="closeSettings()">✕</button>
        </div>
        <div class="setting-row">
          <div>
            <div class="setting-label">Rotación Automática a 0%</div>
            <div class="setting-desc">Alterna de cuenta cuando se agotan los tokens</div>
          </div>
          <input type="checkbox" id="autoSwitchToggle" onchange="toggleAutoSwitch(this.checked)" checked>
        </div>
        <div class="setting-row">
          <div>
            <div class="setting-label">Efectos de Sonido</div>
            <div class="setting-desc">Feedback acústico procedural al rotar</div>
          </div>
          <input type="checkbox" id="audioToggle" onchange="toggleSound(this.checked)" checked>
        </div>
        <div class="setting-row">
          <div>
            <div class="setting-label">Volumen Acústico</div>
            <div class="setting-desc">Sensibilidad sonora del sintetizador</div>
          </div>
          <div class="range-group">
            <input type="range" id="volumeSlider" min="0" max="100" value="50" oninput="updateVolume(this.value)">
            <span id="volumeVal">50%</span>
          </div>
        </div>
        <div class="setting-row">
          <div>
            <div class="setting-label">Sensibilidad de Sondeo</div>
            <div class="setting-desc">Cadencia de muestreo de cuota en vivo</div>
          </div>
          <div class="range-group">
            <input type="range" id="sensSlider" min="5" max="60" value="20" oninput="updateSens(this.value)">
            <span id="sensVal">20s</span>
          </div>
        </div>
      </div>
    </div>

    <footer>
      <div id="analytics-summary">Burn-Rate: Calculando... | Rotaciones: 0</div>
      <div id="last-sync">Sincronizando...</div>
    </footer>
  </div>

  <script>
    function clamp(val, min, max) {
      return Math.max(min, Math.min(max, val));
    }

    function openSettings() {
      document.getElementById('settingsModal').classList.add('open');
    }

    function closeSettings() {
      document.getElementById('settingsModal').classList.remove('open');
    }

    function handleBackdropClick(e) {
      if (e.target.id === 'settingsModal') closeSettings();
    }

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeSettings();
    });

    window.addEventListener('blur', () => {
      // Clear transient focuses
    });

    window.addEventListener('resize', () => {
      // Responsive layout auto-adjustment
    });

    function updateVolume(val) {
      const v = clamp(parseInt(val) || 50, 0, 100);
      document.getElementById('volumeVal').innerText = `${v}%`;
    }

    function updateSens(val) {
      const s = clamp(parseInt(val) || 20, 5, 60);
      document.getElementById('sensVal').innerText = `${s}s`;
    }

    async function toggleAutoSwitch(enabled) {
      try {
        await fetch('/api/toggle-auto-switch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !!enabled })
        });
      } catch (e) {
        console.error('Error toggling auto-switch:', e);
      }
    }

    async function toggleSound(enabled) {
      try {
        await fetch('/api/toggle-sound', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !!enabled })
        });
      } catch (e) {
        console.error('Error toggling sound:', e);
      }
    }

    async function updateHUD() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error('API Error');
        const data = await res.json();
        
        document.getElementById('hud-status').innerText = '● CONECTADO';
        document.getElementById('hud-status').style.color = '#10b981';
        
        const grid = document.getElementById('accounts-grid');
        grid.innerHTML = '';
        
        for (const [email, acc] of Object.entries(data.accounts || {})) {
          const isActive = (email === data.active_account);
          const gem = acc.gemini || {};
          const cgpt = acc.claude_gpt || {};
          
          const g5h = clamp(gem.five_hour_remaining_pct ?? acc.five_hour_remaining_pct ?? 100, 0, 100);
          const gwk = clamp(gem.weekly_remaining_pct ?? acc.weekly_remaining_pct ?? 100, 0, 100);
          const c5h = clamp(cgpt.five_hour_remaining_pct ?? 100, 0, 100);
          const cwk = clamp(cgpt.weekly_remaining_pct ?? 100, 0, 100);
          
          const fillG5h = g5h > 35 ? 'fill-high' : (g5h > 15 ? 'fill-mid' : 'fill-low');
          const fillGwk = gwk > 35 ? 'fill-high' : (gwk > 15 ? 'fill-mid' : 'fill-low');
          const fillC5h = c5h > 35 ? 'fill-high' : (c5h > 15 ? 'fill-mid' : 'fill-low');
          const fillCwk = cwk > 35 ? 'fill-high' : (cwk > 15 ? 'fill-mid' : 'fill-low');
          
          const card = document.createElement('div');
          card.className = `card ${isActive ? 'active' : ''}`;
          card.innerHTML = `
            <div class="card-header">
              <span class="acc-email">${email.split('@')[0]}</span>
              <span class="acc-tag ${isActive ? 'tag-active' : 'tag-standby'}">${isActive ? 'Activa' : 'En Espera'}</span>
            </div>
            <div style="font-size: 11px; font-weight: 600; color: #60a5fa; margin-bottom: 6px;">Gemini Models</div>
            <div class="metric">
              <div class="metric-label">
                <span>Límite 5h</span>
                <span class="metric-val">${g5h}%</span>
              </div>
              <div class="progress-bar"><div class="progress-fill ${fillG5h}" style="width: ${g5h}%"></div></div>
            </div>
            <div class="metric">
              <div class="metric-label">
                <span>Semanal</span>
                <span class="metric-val">${gwk}%</span>
              </div>
              <div class="progress-bar"><div class="progress-fill ${fillGwk}" style="width: ${gwk}%"></div></div>
            </div>
            <div style="font-size: 11px; font-weight: 600; color: #a78bfa; margin-top: 10px; margin-bottom: 6px;">Claude & GPT Models</div>
            <div class="metric">
              <div class="metric-label">
                <span>Límite 5h</span>
                <span class="metric-val">${c5h}%</span>
              </div>
              <div class="progress-bar"><div class="progress-fill ${fillC5h}" style="width: ${c5h}%"></div></div>
            </div>
            <div class="metric">
              <div class="metric-label">
                <span>Semanal</span>
                <span class="metric-val">${cwk}%</span>
              </div>
              <div class="progress-bar"><div class="progress-fill ${fillCwk}" style="width: ${cwk}%"></div></div>
            </div>
            <div style="font-size: 10px; color: var(--text-muted); margin-top: 8px;">
              Recarga: ${gem.five_hour_recharge_in || acc.five_hour_recharge_in || 'Disponible'}
            </div>
          `;
          grid.appendChild(card);
        }
        
        if (data.analytics) {
          document.getElementById('analytics-summary').innerText = 
            `Burn-Rate: ${data.analytics.burn_rate_pct_per_hour || 0}%/h | Rotaciones: ${data.analytics.total_rotations || 0}`;
        }
        document.getElementById('last-sync').innerText = `Sinc: ${new Date().toLocaleTimeString()}`;
      } catch (e) {
        document.getElementById('hud-status').innerText = 'ERROR';
        document.getElementById('hud-status').style.color = '#ef4444';
      }
    }

    async function triggerSwitch() {
      const btn = document.getElementById('btn-switch');
      if (!confirm('¿Deseas ejecutar un cambio de cuenta inmediato?')) return;
      btn.disabled = true;
      btn.innerText = 'Rotando cuenta...';
      try {
        const res = await fetch('/api/switch', { method: 'POST' });
        const data = await res.json();
        alert(data.message || 'Rotación en proceso');
      } catch (e) {
        alert('Error al solicitar rotación: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerText = 'Rotar Cuenta Ahora';
        updateHUD();
      }
    }

    setInterval(updateHUD, 4000);
    updateHUD();
  </script>
</body>
</html>
"""

_cached_health_audit: Optional[Dict[str, Any]] = None
_last_health_audit_time: float = 0.0

def get_cached_health_audit(ttl_sec: float = 15.0) -> Dict[str, Any]:
    """Caches health audit results for ttl_sec to prevent hammering CDP and system processes."""
    global _cached_health_audit, _last_health_audit_time
    now = time.time()
    if _cached_health_audit is None or (now - _last_health_audit_time) > ttl_sec:
        _cached_health_audit = run_health_audit()
        _last_health_audit_time = now
    return _cached_health_audit

def get_hud_status_payload() -> Dict[str, Any]:
    """Compiles the aggregate status payload for the HUD and API."""
    mem = load_memory()
    active = mem.get("active_account", "")
    
    effective_accounts = {}
    for email in DEFAULT_ACCOUNTS:
        effective_accounts[email] = get_effective_account_status(email)
        
    burn = calculate_burn_rate(active) if active else {}
    history = load_analytics_data()
    burn["total_rotations"] = history.get("total_rotations", 0)
    
    audit = get_cached_health_audit(ttl_sec=15.0)
    
    return {
        "active_account": active,
        "accounts": effective_accounts,
        "analytics": burn,
        "health": audit,
        "updated_at": mem.get("updated_at"),
        "auto_switch_enabled": is_auto_switch_enabled(),
        "sound_enabled": is_sound_enabled()
    }

class HUDRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
        elif self.path == "/api/status":
            payload = get_hud_status_payload()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/switch":
            logger.info("Manual switch triggered via Local HUD API!")
            switch_script = os.path.join(SCRIPT_DIR, "daemon_service.py")
            subprocess.Popen([sys.executable, switch_script, "--switch-now"])
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": "Rotación de cuenta solicitada en segundo plano."}).encode("utf-8"))
        elif self.path == "/api/toggle-auto-switch":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8'))
                enabled = bool(data.get('enabled', True))
                set_auto_switch_enabled(enabled)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "auto_switch_enabled": enabled}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        elif self.path == "/api/toggle-sound":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8'))
                enabled = bool(data.get('enabled', True))
                set_sound_enabled(enabled)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "sound_enabled": enabled}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence default stderr logging to keep console clean
        pass

class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

def start_hud_server(port: int = HUD_PORT):
    """Starts the multi-threaded HUD server on localhost."""
    server = ReusableThreadingHTTPServer(("127.0.0.1", port), HUDRequestHandler)
    logger.info(f"Local HUD server running at http://127.0.0.1:{port}")
    server.serve_forever()

def start_hud_in_background(port: int = HUD_PORT):
    """Starts HUD server inside a daemon background thread."""
    t = threading.Thread(target=start_hud_server, args=(port,), daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    print(f"Iniciando HUD en http://127.0.0.1:{HUD_PORT}...")
    start_hud_server()
