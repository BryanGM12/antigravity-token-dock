"""
Local HUD: Ultra-Lightweight Web Dashboard & REST Micro-API
Serves a responsive, dark-mode real-time status dashboard on http://127.0.0.1:59123
and provides /api/status and /api/switch endpoints for OpenClaw / Jarvis integration.
"""

import os
import sys
import json
import logging
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional

logger = logging.getLogger("LocalHUD")

HUD_PORT = 59123
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Import sibling modules
sys.path.insert(0, SCRIPT_DIR)
from token_memory import load_memory, get_effective_account_status, DEFAULT_ACCOUNTS
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
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      padding: 24px;
      display: flex;
      justify-content: center;
    }
    .container {
      width: 100%;
      max-width: 880px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
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
    .btn-rotate {
      background: var(--accent);
      color: #fff;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.2s;
    }
    .btn-rotate:hover { background: var(--accent-hover); }
    .btn-rotate:disabled { opacity: 0.5; cursor: not-allowed; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 18px;
    }
    .card.active {
      border-color: rgba(59, 130, 246, 0.4);
      box-shadow: 0 0 16px rgba(59, 130, 246, 0.08);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }
    .acc-email {
      font-size: 14px;
      font-weight: 600;
    }
    .acc-tag {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .tag-active { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }
    .tag-standby { background: rgba(156, 163, 175, 0.2); color: var(--text-muted); }
    .metric { margin-bottom: 12px; }
    .metric-label {
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: var(--text-muted);
      margin-bottom: 4px;
    }
    .metric-val { font-weight: 600; color: var(--text); }
    .progress-bar {
      height: 6px;
      background: #262b36;
      border-radius: 9999px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      border-radius: 9999px;
      transition: width 0.4s ease;
    }
    .fill-high { background: var(--success); }
    .fill-mid { background: var(--warning); }
    .fill-low { background: var(--danger); }
    .footer-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 16px;
      font-size: 12px;
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="title-group">
        <h1>Antigravity HUD <span class="badge" id="hud-status">EN VIVO</span></h1>
      </div>
      <button class="btn-rotate" id="btn-switch" onclick="triggerSwitch()">Rotar Cuenta Ahora</button>
    </header>

    <div class="grid" id="accounts-grid">
      <!-- Injected dynamically -->
    </div>

    <div class="footer-card">
      <div id="analytics-summary">Velocidad de Gasto: Calculando...</div>
      <div id="last-sync">Actualizando...</div>
    </div>
  </div>

  <script>
    async function updateHUD() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        const active = data.active_account || "";
        const grid = document.getElementById('accounts-grid');
        grid.innerHTML = '';
        
        for (const [email, acc] of Object.entries(data.accounts || {})) {
          const isActive = active.toLowerCase().includes(email.toLowerCase().split('@')[0]);
          const gem = acc.gemini || {};
          const cgpt = acc.claude_gpt || {};
          
          const g5h = gem.five_hour_remaining_pct ?? acc.five_hour_remaining_pct ?? 100;
          const gwk = gem.weekly_remaining_pct ?? acc.weekly_remaining_pct ?? 100;
          const c5h = cgpt.five_hour_remaining_pct ?? 100;
          const cwk = cgpt.weekly_remaining_pct ?? 100;
          
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
    
    audit = run_health_audit()
    
    return {
        "active_account": active,
        "accounts": effective_accounts,
        "analytics": burn,
        "health": audit,
        "updated_at": mem.get("updated_at")
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
            # Trigger asynchronous switch via python script in background
            switch_script = os.path.join(SCRIPT_DIR, "daemon_service.py")
            subprocess.Popen(["python.exe", switch_script, "--switch-now"])
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": "Rotación de cuenta solicitada en segundo plano."}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence default stderr logging to keep console clean
        pass

def start_hud_server(port: int = HUD_PORT):
    """Starts the HUD server on localhost."""
    server = HTTPServer(("127.0.0.1", port), HUDRequestHandler)
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
