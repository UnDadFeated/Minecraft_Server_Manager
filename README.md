# Minecraft Server Updater & Installer

**Version:** 2.1  
**Author:** UnDadFeated  

A powerful, cross-platform Python utility designed to streamline the installation, updating, and management of Minecraft servers. This tool supports **Windows** and **Linux** environments and is compatible with **Vanilla**, **Forge**, and **NeoForge** server setups.

---

## 🚀 Key Features

### 🛠️ Dual-Mode Functionality

- **Smart Installation Wizard:** Automatically detects missing server components and guides you through a clean, guided installation process.
- **Automated Updates:** Seamlessly checks Mojang's version manifest to keep your Vanilla server running the latest version.

### 💻 Cross-Platform Compatibility

- **Windows:** Installs dynamically to your chosen directory.
- **Linux:** Automatically provisions to `/home/{username}/MCServer/`.

### 🧩 Comprehensive Loader Support

- **Vanilla Setup:** Features automatic version matching and downloading directly from official sources.
- **Forge & NeoForge Integration:** Supports robust installer execution while implementing **Safe Update Protection** to prevent unintended data loss or broken mods.

### ⚙️ Intelligent Dependency Management

- **Java Version Verification:** Automatically validates the presence of the correct Java Runtime Environment (Java 8, 16, 17, or 21) based on the target Minecraft version.
- **EULA & Script Generation:** Automatically accepts the Minecraft EULA and generates OS-specific startup scripts (`Manual_Run.bat` or `Manual_Run.sh`).

### 📦 Automated Backups

- Safely archives the current `minecraft_server.jar` and `world` directory before performing any major version upgrades or operations.

---

## ⚙️ Configuration

You can customize the tool's behavior by editing the constants at the top of `MS_Update.py`:

```python
UPDATE_TO_SNAPSHOT = False    # Set to True to allow updates to developmental snapshots (Vanilla only)
BACKUP_DIR = 'world_backups'  # Directory for storing world archives
SERVER_JAR = 'minecraft_server.jar' # The expected name of your server executable
START_BATCH_FILE = 'Manual_Run.bat' # The default startup script name
```

---

## 📖 Usage Guide

### 1. Install Prerequisites

Ensure you have Python installed, then install the required `requests` library:

```bash
pip install requests
```

### 2. Execute the Tool

Run the script to begin management:

```bash
python MS_Update.py
```

- **If no server is detected:** The interactive **Installer Wizard** will launch.
- **If an existing server is found:** The tool will check for **Vanilla Updates** or ensure **Modded Servers** boot safely.

---

## ⚠️ Important Considerations
>
> [!WARNING]
> This script utilizes OS-level process management (`wmic` on Windows, `pkill` on Linux) to gracefully terminate the server preceding an update. Ensure this automated shutdown behavior aligns with your operational environment to prevent unintended interruptions.
