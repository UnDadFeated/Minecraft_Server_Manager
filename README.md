<div align="center">

# 🎮 Minecraft Server Updater & Installer

**The all-in-one Python utility for deploying, managing, and updating Minecraft servers across Windows and Linux.**

![Version](https://img.shields.io/badge/version-2.1-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-yellow.svg)
![Platform](https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey.svg)

</div>

---

A robust, cross-platform tool designed to remove the friction from hosting a Minecraft server. Whether you are running a lightweight Vanilla instance or a heavily modded Forge/NeoForge network, this utility ensures your server stays updated, backed up, and securely managed.

---

## ✨ Features

### 🛠️ Smart Deployment & Updates

- **Interactive Installer:** Automatically detects missing server components and provisions a clean environment with an easy-to-use wizard.
- **Zero-Touch Updates:** Interfaces directly with Mojang's API manifest to seamlessly upgrade Vanilla servers to the latest release.

### 🧩 Multi-Loader Architecture

- **Vanilla Integration:** Full support for version matching and direct jar downloading.
- **Forge & NeoForge Support:** Handles complex modded and third-party installers while enforcing **Safe Update Protection** to guarantee your mod lists and custom configs are never overwritten.

### ⚙️ System Intelligence

- **Java Validation:** Automatically checks your system's environment to ensure the correct Java Runtime Environment (Java 8, 16, 17, or 21) is installed based on the target Minecraft version constraints.
- **Automated Provisioning:** Seamlessly accepts the Minecraft EULA and generates OS-specific startup scripts (`Manual_Run.bat` or `Manual_Run.sh`) pre-configured with optimized memory flags.

### 🛡️ Built-In Resilience

- **Automated Backups:** Safely archives the existing `minecraft_server.jar` and creates timestamped copies of your `world` directory before executing major version upgrades.
- **Graceful Termination:** Safely halts running server processes (`wmic` on Windows, `pkill` on Linux) before modifying system files.

---

## 🚀 Getting Started

To ensure maximum compatibility and easy configuration, this tool is distributed as a source script. There are no compiled executables to download.

### 1. Prerequisites & Environment Setup

Ensure you have [Python 3.8+](https://www.python.org/downloads/) installed.

Clone this repository to your local machine:

```bash
git clone https://github.com/Ascendin81/Minecraft_Server_Updater.git
cd Minecraft_Server_Updater
```

Install the required dependencies:

```bash
pip install requests
```

### 2. Initializing the Manager

Run the core script to begin:

```bash
python MS_Update.py
```

- **Clean Environments:** The interactive **Installer Wizard** will take over, allowing you to select your server type, OS path, and version.
- **Existing Environments:** The tool will analyze your current `minecraft_server.jar` checksum against Mojang's API, backup your world, and perform an update if one is available.

### 3. Routine Operation
>
> [!NOTE]
> Once the installation or update process is complete, you do not need to run `MS_Update.py` every time you want to play.
> Instead, navigate to your server directory and execute the generated **`Manual_Run.bat`** (Windows) or **`Manual_Run.sh`** (Linux) to boot your server quickly and safely.

---

## 🔧 Configuration Options

Advanced users can customize the tool's behavior by modifying the constants at the top of the `MS_Update.py` script:

```python
# Enable if you want to automatically download the latest Mojang testing snapshots
UPDATE_TO_SNAPSHOT = False    

# Directory where timestamped world archives will be placed
BACKUP_DIR = 'world_backups'  

# The target binary the script interfaces with for updates and process management
SERVER_JAR = 'minecraft_server.jar' 

# The name of the automated start script generated during installation
START_BATCH_FILE = 'Manual_Run.bat' 
```

---

## ⚠️ Important Considerations

> [!WARNING]
> **Process Management:** This script utilizes OS-level process management to cleanly terminate the server prior to updates. Ensure this behavior aligns with your environment, particularly if hosting multiple instances on a single machine.
>
> **Modded Environments:** The updater logic skips automatic jar replacements for Forge/NeoForge to prevent fatal data loss. It will instead boot the server normally.

---
<div align="center">
  <i>Developed and maintained by <b>UnDadFeated</b></i>
</div>
