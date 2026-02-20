<div align="center">
  <h1>🎮 Minecraft Server Manager</h1>

  <p>
    <b>A robust, Python-based automation script designed for managing Dedicated Minecraft Servers with a focus on reliability, performance, and remote management.</b>
  </p>

  <p>
    <img alt="Version" src="https://img.shields.io/badge/version-3.1.0-blue.svg" />
    <img alt="Python" src="https://img.shields.io/badge/python-3.8%2B-yellow.svg" />
    <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg" />
  </p>

</div>

---

## ✨ Key Features

- 🖥️ **Dual Interfaces:** Launch via the modern, user-friendly graphical interface (GUI), or utilize the headless console mode (`-nogui`) for streamlined server environments.
- 🔄 **Automated Updates:** Seamlessly checks the Mojang manifest API. When a Vanilla update is detected, it automatically downloads the JAR and restarts.
- 🛡️ **Crash Detection & Auto-Restart:** Continually monitors the server process and issues automatic restarts to maintain high uptime.
- ⏱️ **Scheduled Restarts:** Set specific intervals for automated, clean server reboots to prevent memory saturation and degradation over time.
- 💾 **Automated World Backups:** Archives the local server world directory into a `.zip` file prior to initialization. Prevents catastrophic data loss.
- 💬 **Discord Integration:** Features integrated Discord Webhooks to instantly alert your community on server status changes (Startup, Shutdown, Crashes). Includes a threaded bot for chat commands (`!start`, `!stop`, `!restart`, `!status`).
- 📡 **Background Polling:** Periodically scans for new official Minecraft server versions, downloading and replacing engine files as necessary.
- 🔧 **Modded Support:** Fully compatible with Forge and NeoForge installations.

---

## 🛠️ Technical Prerequisites

### Minimum Requirements

| Requirement | Details |
| :--- | :--- |
| **Operating System** | Windows, Linux, or macOS |
| **Memory** | At least `2G` allocated to the server heap (`4G+` recommended for modded) |
| **Java Environment** | **Java 17 or Java 21** depending on your Minecraft version. |
| **Python** | Python 3.8 or higher |

---

## 🚀 Installation Guide

1. **Clone the Repository:** Download the repository source code.
2. **Locate Server Path:** Move the script `mcsm.py` into the root directory where you intend to run (or are currently running) your Minecraft server.
3. **Run Application:** Launch the program via your command line interface.

---

## 📖 Operational Guide

### Graphical Mode (Default)

Running the script parameter-free initializes the Graphical User Interface.

```bash
python mcsm.py
```

- **Real-time Output:** View live stdout and stderr streams directly in the application pane.
- **Visual Configurations:** Toggle crucial behaviors like Backups, Discord Webhooks, and Auto-Restart intervals directly through application checkboxes.
- **Path Shortcuts:** Provides native file-explorer context buttons to rapidly open your Server Root, Worlds directory, and Backups archive.
- **Theming Options:** Supports dynamically un-toggling light and dark mode elements.

### Headless Console Mode

Targeting headless environments, the application can bypass the `tkinter` dependency completely. All required values are read directly from `mcsm.conf` upon boot sequence.

```bash
python mcsm.py -nogui
```

---

## ⚙️ Configuration Reference

Changes made to the server logic are primarily driven by the `mcsm.conf` configuration file auto-generated in the application root directory.

```json
{
  "manager_auto_update": true,
  "check_updates": true,
  "auto_start": false,
  "server_memory": "4G",
  "enable_backups": true,
  "max_backups": 3,
  "enable_auto_restart": true,
  "enable_schedule": false,
  "restart_interval": 12.0,
  "enable_discord": false,
  "discord_webhook": "YOUR_WEBHOOK_URL",
  "discord_token": "YOUR_BOT_TOKEN",
  "discord_channel_id": 1234567890,
  "update_to_snapshot": false
}
```

> **Note:** For the basic discord chatbot commands, verify your application's `Message Content Intent` is marked to `ON` within the Discord Developer portal.

---

## 🏷️ Versioning

**Current Version:** `3.1.0`

<div align="center">
  <i>Developed and maintained by <b>UnDadFeated</b></i>
</div>
