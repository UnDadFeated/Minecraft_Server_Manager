# Conversation Log

## 2025-03-21 (Audit: Minecraft-appropriate fixes)

- **Audit:** Double-checked mcsm.pyw against Hytale reference; applied Minecraft-appropriate fixes.
- **run_update_installer:** script_ext for mcsm.py/.pyw; CREATE_NO_WINDOW; pythonw restart; except Exception; time buffer.
- **check_self_update:** script_ext; improved parsing; "Could not parse"/"Manager is up to date" messages.
- **stop_existing_server_process:** $_.Name -eq 'java.exe'; startupinfo; "Found running server" log.
- **Backup prune:** startswith("world_") filter.
- **INSTALL_REQUIREMENTS:** requirements.txt hint.
- **Cleanup:** Removed unused signal, contextlib.
- **Version:** 5.0.0 → 5.0.1 (PATCH)

---

## 2025-03-21 (Hytale parity update)

- **Reference:** Hytale_Server_Updater used as source for improvements.
- **PySide6 migration:** GUI migrated from Tkinter/sv_ttk to PySide6 for consistency with Hytale manager.
- **Changes:** Single-instance lock, debug.log, IS_LINUX/IS_DARWIN, background update restart, Check for updates button, Linux systemd/autostart, bare except fixes, optional psutil, requirements.txt.
- **Version:** 4.1.3 → 5.0.0 (MINOR – feature parity with Hytale manager)

---
