# Changelog

## 5.1.1 (2026-05-22)

- **fix:** Point auto-updater GitHub URL to `main` branch instead of legacy `master` branch.
- **fix:** Remove mutual exclusivity between "Check for Server Updates" and "Skip if Modded" GUI checkboxes.
- **fix:** Extract backup files into the `world` folder rather than dumping them at the server's root level.
- **fix:** Rename casing of `assets/Screenshot.png` to lowercase `assets/screenshot.png` to resolve case-sensitivity issues on Linux.

## 5.1.0 (2026-04-19)

- **feat:** Add security box with online mode and whitelist toggles, reorganizing UI into a modern 3-column layout.
- **fix:** Clarify config labels for RAM, Updates, and scheduled restarts.
- **docs:** Rewrite README with comprehensive features and setup guides.

## 5.0.9 (2025-03-21)

- **fix:** Control config box uses footer darker grey (#181818); input fields and buttons pop against it

## 5.0.8 (2025-03-21)

- **fix:** Dark theme – button bg matches Discord input grey (#222222); CPU/RAM stats transparent bg; config/command boxes same color

## 5.0.7 (2025-03-21)

- **fix:** "Check for updates" button no longer logs "Manager is up to date." twice

## 5.0.6 (2025-03-21)

- **fix:** Dark theme – config box, command box, footer use #222222/#181818 to match Hytale (restore layered grey, not transparent)

## 5.0.5 (2025-03-21)

- **fix:** Footer "Check for updates" button checks manager from GitHub only (not Minecraft server JAR); match Hytale behavior

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
