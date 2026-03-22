# TASKS

## Active

- (none)

## Completed by Version

### 5.0.1 (2025-03-21)

- [x] run_update_installer: script_ext, CREATE_NO_WINDOW, pythonw restart handling
- [x] check_self_update: script_ext; improved version parsing and error messages
- [x] stop_existing_server_process: java.exe match, startupinfo, "Found running server" log
- [x] Backup prune: filter by startswith("world_")
- [x] INSTALL_REQUIREMENTS: add requirements.txt hint
- [x] Remove unused signal, contextlib imports; add docstrings
- [x] entry_memory: editingFinished instead of textChanged

### 5.0.0 (2025-03-21)

- [x] Migrate GUI from Tkinter to PySide6
- [x] Add requirements.txt (psutil, PySide6, discord.py)
- [x] Add single-instance lock (PID-based .mcsm.lock)
- [x] Add debug.log with timestamps
- [x] Add IS_LINUX, IS_DARWIN; platform-specific handling (open on macOS)
- [x] Background update restart when new JAR applied
- [x] Add "Check for updates" button in GUI footer
- [x] Add Linux -install-service and -enable-autostart CLI options
- [x] Fix bare except blocks; optional psutil handling (HAS_PSUTIL)
- [x] Add TASKS.md, CHANGELOG.md, CONVERSATION_LOG.md
