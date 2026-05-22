# Minecraft Server Manager

A Python-based management tool for dedicated Minecraft servers with automated updates, backups, and griefing protection via a modern PySide6 GUI or headless console mode.

[![Version](https://img.shields.io/badge/version-5.1.1-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.8%2B-yellow.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

---

## Screenshot

![Minecraft Server Manager](assets/screenshot.png)

---

## Features

### Server Management
- **Automated updates** — Downloads the latest Minecraft server JAR from Mojang manifest API
- **Single-instance lock** — Prevents multiple instances from controlling the same server
- **Crash recovery** — Monitors process health and performs automatic restarts on crash
- **Scheduled restarts** — Configurable intervals for clean server reboots

### Backup System
- **Pre-start backups** — Automatically archives the world directory before server startup
- **Backup retention** — Configurable number of backups to keep on disk
- **One-click restore** — Restore from any previous backup through the GUI

### Security (v5.1.1)
- **Online mode toggle** — Enable/disable `online-mode` directly from the GUI
- **Whitelist enforcement** — Toggle server whitelist from the GUI
- **Security status indicator** — Real-time display of protection status (Secure/Warning/Danger)
- **Pre-startup security check** — Warns if protections are disabled before starting the server

### Integrations
- **Discord bot** — Chat commands: `!start`, `!stop`, `!restart`, `!status`, `!players`
- **Discord webhooks** — Notifications for player joins, crashes, and updates
- **Linux service** — Install as a systemd service (`-install-service`)
- **Desktop autostart** — Launch on desktop login (`-enable-autostart`)

### User Interface
- **Dual interfaces** — PySide6 GUI or headless console mode (`-nogui`)
- **Real-time monitoring** — CPU, RAM, and uptime display while running
- **Light/dark theme** — Toggle between themes in the footer
- **Folder shortcuts** — Quick access to Server, Worlds, and Backups directories

---

## Requirements

| Requirement | Details |
| :--- | :--- |
| **Operating system** | Windows, Linux, or macOS |
| **Java** | Java 17 or Java 21 (depends on server version) |
| **Python** | 3.8 or higher |
| **Python packages** | `psutil`, `PySide6` |
| **Optional** | `discord.py` for Discord bot, `rich` for console formatting |

Install dependencies:
```bash
pip install psutil PySide6
# Optional:
pip install discord.py rich
```

---

## Installation

1. Place `mcsm.pyw` in your Minecraft server root directory.
2. Run the script to start the GUI:
   ```bash
   python mcsm.pyw
   ```
3. On first run, it creates `mcsm.conf` with default settings.

For Linux systemd service:
```bash
sudo python mcsm.pyw -install-service
```

---

## Usage

### Graphical Mode

```bash
python mcsm.pyw
```

Launches the PySide6 GUI with:
- Config, Security, and Server Details panels
- Real-time console output
- One-click start/stop buttons
- Inline configuration and security toggles

### Headless Mode

```bash
python mcsm.pyw -nogui
```

Runs without a GUI, reading settings from `mcsm.conf`. Ideal for headless servers.

### Command-Line Options

| Option | Description |
| :--- | :--- |
| `-nogui` | Run in console-only mode |
| `-install-service` | (Linux) Install as systemd service |
| `-enable-autostart` | (Linux) Add to desktop autostart |
| `-help` | Display help and exit |

---

## Configuration

Settings are stored in `mcsm.conf` (created on first run).

| Setting | Description | Default |
| :--- | :--- | :--- |
| `server_memory` | Java heap size (e.g., `4G`, `8G`) | `4G` |
| `check_updates` | Check for Minecraft updates on startup | `true` |
| `update_to_snapshot` | Use latest snapshot instead of release | `false` |
| `modded_do_not_update` | Skip updates when mods are detected | `false` |
| `enable_backups` | Create backup before starting server | `true` |
| `max_backups` | Number of backups to retain | `3` |
| `enable_auto_restart` | Restart server on crash | `true` |
| `enable_schedule` | Enable scheduled restarts | `false` |
| `restart_interval` | Hours between scheduled restarts | `12` |
| `enable_discord` | Enable Discord webhooks/bot | `false` |
| `dark_mode` | Use dark theme | `true` |

> **Discord bot:** Enable **Message Content Intent** in the Discord Developer Portal for chat commands.

---

## Security Features

When hosting a server exposed to the internet (via port forwarding, e4mc, Hamachi, etc.):

1. **Keep Online Mode enabled** — Prevents anyone from connecting with a spoofed username
2. **Enable Whitelist** — Only listed players can join
3. The Security panel shows your protection status in real-time

The GUI warns you before starting the server if protections are disabled.

---

## License

MIT License — See [LICENSE](LICENSE) for details.

---

*Developed and maintained by **UnDadFeated***