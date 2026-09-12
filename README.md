<div align="center">

# ✦ Antigravity Token Dock & Multi-Account Controller

**The native docked overlay and autonomous account rotator for Google Antigravity IDE.**

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg?logo=windows&logoColor=white)](https://microsoft.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![UI Framework](https://img.shields.io/badge/GUI-PyQt6%20%7C%20Win32-41CD52.svg?logo=qt&logoColor=white)](https://riverbankcomputing.com/software/pyqt/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Theme](https://img.shields.io/badge/Design-Deep%20Obsidian%20Minimalist-528bff.svg)](#design--interface)

</div>

---

## 🌟 Overview

**Antigravity Token Dock** is an ultra-lightweight, hardware-accelerated desktop companion designed exclusively for **Google Antigravity IDE**.

When developing complex multi-agent workflows, codebases, or executing `/goal` tasks, model quota exhaustion (5-hour and weekly caps) disrupts the development lifecycle. **Antigravity Token Dock** eliminates manual switching by docking directly to the Antigravity window, tracking quotas across multiple Google AI accounts in real time, and enabling seamless 1-click or automated background rotation with zero interruption to your active task.

---

## ⚡ Key Capabilities

- **📍 Magnetic Zero-Lag Window Docking**: Hooks directly into the native Windows Win32 event subsystem (`EVENT_OBJECT_LOCATIONCHANGE`) with an adaptive 25ms heartbeat and hardware `SetWindowPos` repositioning. Tracks moves, resizes, minimizations, and multi-monitor setups without CPU overhead.
- **✨ Intelligent Auto-Sorting**:
  - **Active Account (Top)**: The account currently logged in is pinned at the very top with an animated emerald heartbeat pulse.
  - **Available Accounts (Middle)**: Standby accounts with active token reserves ranked by remaining quotas.
  - **Exhausted Accounts (Bottom)**: Accounts that have hit quota limits are automatically moved to the bottom with live recharge countdowns and reset clocks.
- **🎨 Antigravity Minimalist Aesthetic**:
  - Signature Google AI gradient accent line (`#528bff` ➔ `#818cf8` ➔ `#c084fc` ➔ `#f472b6`).
  - Deep Obsidian palette (`#14161b` / `#181b22`) blending seamlessly into the IDE.
  - Hairline 4px progress bars, micro badges, and live model chips.
  - Fluid 220ms slide-in / slide-out animations powered by `QVariantAnimation` with `OutCubic` easing.
- **🔄 Automated OAuth & Session Resumption**:
  - Full automation: Signs out of Antigravity ➔ Selects account via visual computer vision and keyboard navigation in the browser ➔ Confirms session ➔ Automatically injects a resumption prompt into the active chat so work continues uninterrupted.
- **🔒 100% Local Privacy & Security**:
  - Zero cloud relay. All configuration stays on your local machine (`accounts_config.json` is strictly ignored by Git).
  - Works with any number of Google AI Pro or standard accounts.

---

## 🖥 Architecture

```text
┌──────────────────────────────────────────────────────────┐
│                   Google Antigravity IDE                 │
│      (Electron / React Fiber / CDP on Port 59123)        │
└──────────────────────────┬───────────────────────────────┘
                           │
             Win32 Events  │  Live Quota Scrapes
         (Location Change) │  (authService / state)
                           ▼
┌──────────────────────────────────────────────────────────┐
│              ✦ Antigravity Token Dock Widget              │
│       - 28px Slim Edge Pill Handle                       │
│       - 360px Minimalist Flyout Panel                    │
│       - Dynamic Sorting (Active Top ➔ Exhausted Bottom)  │
│       - Pulsing Live Health Heartbeat                    │
└──────────────────────────┬───────────────────────────────┘
                           │
             1-Click Switch│ Auto-Rotation Trigger
                           ▼
┌──────────────────────────────────────────────────────────┐
│             Autonomous Background Daemon & Rotator       │
│       - Quota Detector (CDP Inspector)                   │
│       - External Browser OAuth Handler (Vision + Win32)   │
│       - Task Resumer (Restores Active Conversation)      │
│       - SQLite / JSON Persistent State Memory            │
└──────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Requirements
- Windows 10 or Windows 11 (64-bit)
- Python 3.10+
- Google Antigravity IDE

### 2. Installation

Clone this repository:
```bash
git clone https://github.com/BryanGM12/antigravity-token-dock.git
cd antigravity-token-dock
```

Install the dependencies:
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure Your Accounts

Copy the configuration template:
```bash
cp accounts_config.example.json accounts_config.json
```

Edit `accounts_config.json` with your own accounts:
```json
{
  "accounts": [
    {
      "email": "primary.pro@gmail.com",
      "name": "Primary Account",
      "tier": "👑 Pro",
      "tab_index": 1,
      "row_offset": 0
    },
    {
      "email": "backup.pro@gmail.com",
      "name": "Backup Account",
      "tier": "👑 Pro",
      "tab_index": 2,
      "row_offset": 61
    }
  ],
  "monitoring": {
    "poll_interval_sec": 20,
    "hud_port": 59123
  }
}
```

> [!NOTE]
> `accounts_config.json` is included in `.gitignore` to guarantee your credentials and email addresses are never pushed to any remote repository.

---

## ➕ Adding & Managing Accounts

Antigravity Token Dock supports 4 effortless methods to configure your accounts:

### Method 1: Directly from the Docked Overlay (GUI)
Click the **`+`** button in the header bar of the expanded overlay panel. A minimalist dialog will prompt you for the Google email, display name, and Pro tier option. The account is added immediately and the widget updates in real time.

### Method 2: Interactive Console Wizard
Run the built-in step-by-step CLI wizard:
```powershell
python config_manager.py --interactive
# or via PowerShell:
.\antigravity-monitor.ps1 add
```

### Method 3: One-Line PowerShell / Terminal Commands
```powershell
# Add account with display name and Pro tier
.\antigravity-monitor.ps1 add new.account@gmail.com "Cuenta 5" "👑 Pro"

# List all configured accounts
.\antigravity-monitor.ps1 list

# Remove an account
.\antigravity-monitor.ps1 remove old.account@gmail.com
```

### Method 4: Edit `accounts_config.json`
Directly modify the JSON file to define custom tab indexes, nicknames, and offsets.

---

## 💻 Usage

### Run the Docked Widget
```powershell
python antigravity_docked_overlay.py
```
A sleek minimalist pill tab `✦` will attach itself to the right edge of your Antigravity window. Click it to expand the full dashboard; click again or outside to collapse it.

### Monitor & Control via PowerShell
Use the included controller script to manage background processes:
```powershell
# Check live status across all accounts
.\antigravity-monitor.ps1 status

# Start daemon and docked widget
.\antigravity-monitor.ps1 start

# Restart all services
.\antigravity-monitor.ps1 restart

# Stop services
.\antigravity-monitor.ps1 stop
```

### CLI Command Options
```bash
# Display live token status table in terminal
python daemon_service.py --status

# Switch to the next optimal account automatically
python daemon_service.py --switch-now

# Switch to a specific account
python daemon_service.py --switch-to user@example.com

# Start continuous daemon loop
python daemon_service.py --daemon
```

---

## 🛡 Security & Privacy

- **Local Execution**: All processes run strictly as local user-space scripts. No external servers, analytics, or telemetry are used.
- **Git Hygiene**: Sensitive config files (`accounts_config.json`), token databases, screenshots, and logs are automatically excluded by `.gitignore`.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
