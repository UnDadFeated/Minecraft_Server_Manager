# Changelog

## 5.0.4 (2025-03-21)

- **fix:** Dark theme – transparent backgrounds for QFrame, QGroupBox, and footer; remove black box appearance

## 5.0.3 (2025-03-21)

- **fix:** CPU/RAM use direct psutil calls in _refresh_uptime (match Hytale)
- **fix:** Check layout – Do not update if modded under Check for updates; mutually exclusive
- **fix:** Remove redundant modded hint; align checkboxes with indent

## 5.0.2 (2025-03-21)

- **fix:** CPU/RAM display stuck at 0% – use `cpu_percent(interval=0.1)` in background thread

## 5.0.1 (2025-03-21)

- **fix:** run_update_installer: use script_ext for mcsm.py/mcsm.pyw; CREATE_NO_WINDOW; pythonw restart handling
- **fix:** check_self_update: use script_ext; improved version parsing and error messages
- **fix:** stop_existing_server_process: align with Hytale (java.exe, startupinfo, "Found running server" log)
- **fix:** Backup prune: filter by startswith("world_") for consistency
- **fix:** INSTALL_REQUIREMENTS: add "pip install -r requirements.txt" hint
- **chore:** Remove unused signal, contextlib imports; add docstrings

## 5.0.0 (2025-03-21)

- **feat:** GUI migrated from Tkinter to PySide6 (matches Hytale Server Manager)
- **feat:** Single-instance lock (PID-based .mcsm.lock) to prevent multiple manager instances
- **feat:** debug.log with timestamped startup and lifecycle events
- **feat:** IS_LINUX, IS_DARWIN platform constants; use `open` on macOS for folder shortcuts
- **feat:** Background update checker now restarts server when new Minecraft JAR is applied
- **feat:** "Check for updates" button in GUI footer (manager + server)
- **feat:** Linux `-install-service` (systemd) and `-enable-autostart` (desktop) CLI options
- **feat:** requirements.txt (psutil, discord.py, sv_ttk)
- **fix:** Replace bare `except:` with `except OSError` or `except Exception`
- **fix:** Optional psutil (HAS_PSUTIL); CPU/RAM show "N/A" when psutil unavailable

## 4.1.3 (prior)

- Dual interfaces (GUI + headless)
- Mojang manifest API updates, SHA1 verification
- Mod detection, Forge/NeoForge support
- Discord webhook + bot integration
- World backups, scheduled restarts, crash auto-restart
