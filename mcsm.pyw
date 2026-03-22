"""
Minecraft Server Manager - GUI and console automation for Minecraft dedicated servers.

Manages server lifecycle, Mojang updates, backups, Discord integration, and systemd/autostart.
"""
import os
import sys
import datetime

_script_dir = os.path.dirname(os.path.abspath(__file__))
DEBUG_LOG = os.path.join(_script_dir, "debug.log")
_debug_handle = None

def _debug(event, msg):
    """Write timestamped debug event to debug.log (overwritten each launch)."""
    global _debug_handle
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{ts}] [{event}] {msg}\n"
        if _debug_handle is None:
            _debug_handle = open(DEBUG_LOG, "w", encoding="utf-8")
        _debug_handle.write(line)
        _debug_handle.flush()
    except Exception:
        pass

_debug("START", f"Process started | PID={os.getpid()} | argv={sys.argv!r} | cwd={os.getcwd()}")
_debug("START", f"executable={sys.executable} | pythonw={('pythonw' in sys.executable.lower())}")

import subprocess
import time
import shutil
import atexit
import urllib.request
import zipfile
import threading
import queue
import platform
import re
import json
import traceback
import webbrowser
import hashlib

_debug("IMPORT", "core stdlib imports done")
try:
    import psutil
    HAS_PSUTIL = True
    _debug("IMPORT", "psutil OK")
except ImportError as e:
    HAS_PSUTIL = False
    psutil = None
    _debug("IMPORT", f"psutil FAIL: {e}")

# --- Constants ---
if platform.system() == "Windows":
    CREATE_NO_WINDOW = 0x08000000
else:
    CREATE_NO_WINDOW = 0

__version__ = "5.0.5"

JAVA_VERSION_REQ = 21  # Minecraft 1.17+ requires 16/17, 1.20.5+ requires 21
SERVER_JAR = "minecraft_server.jar"
MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
IS_WINDOWS = platform.system() == "Windows"
IS_DARWIN = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
BACKUP_DIR = "world_backups"
WORLD_DIR = "world"
MODS_DIR = "mods"

# Always resolve paths relative to the script's own directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHECK_WHITE_PNG = os.path.join(BASE_DIR, ".check_white.png")
CHECK_BLACK_PNG = os.path.join(BASE_DIR, ".check_black.png")
LOG_FILE = os.path.join(BASE_DIR, "mcsm.log")
CONFIG_FILE = os.path.join(BASE_DIR, "mcsm.conf")
LOCK_FILE = os.path.join(BASE_DIR, ".mcsm.lock")

try:
    from rich.console import Console
    console = Console()
except ImportError:
    console = None

try:
    import discord
    from discord.ext import commands
    HAS_DISCORD = True
    _debug("IMPORT", "discord OK")
except ImportError:
    HAS_DISCORD = False
    _debug("IMPORT", "discord skip (optional)")

# --- Locking ---
def _acquire_single_instance_lock():
    """Returns (True, None) if we got the lock, else (False, error_msg)."""
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            if HAS_PSUTIL and psutil.pid_exists(old_pid):
                return False, f"Another instance is already running (PID {old_pid}). Close it first."
            try:
                os.remove(LOCK_FILE)
            except OSError:
                pass
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        def _release():
            try:
                if os.path.exists(LOCK_FILE):
                    os.remove(LOCK_FILE)
            except OSError:
                pass
        atexit.register(_release)
        return True, None
    except Exception as e:
        _debug("LOCK", f"acquire failed: {e}")
        return True, None

def _check_gui_requirements():
    """Returns list of missing packages required for GUI."""
    missing = []
    try:
        import PySide6  # noqa: F401
    except ImportError:
        missing.append("PySide6")
    if not HAS_PSUTIL:
        missing.append("psutil")
    return missing

def _show_missing_deps_and_offer_install(missing):
    """Show warning that deps are missing and offer to install. Returns True if user chose Install and succeeded."""
    pkg_list = ", ".join(missing)
    msg = (
        f"Minecraft Server Manager cannot start the GUI.\n\n"
        f"Missing: {pkg_list}\n\n"
        f"Would you like to install them now?"
    )
    def do_install():
        exe = sys.executable
        if IS_WINDOWS and "pythonw" in exe.lower():
            exe = exe.replace("pythonw.exe", "python.exe").replace("pythonw", "python.exe")
        cmd = [exe, "-m", "pip", "install"] + missing
        _debug("DEPS", f"Running: {cmd}")
        try:
            r = subprocess.run(cmd)
            return r.returncode == 0
        except Exception as e:
            _debug("DEPS", f"pip failed: {e}")
            return False

    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if messagebox.askyesno("Minecraft Server Manager - Missing Requirements", msg):
            root.destroy()
            ok = do_install()
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("Minecraft Server Manager", "Restart the application." if ok else f"Install failed. Run: pip install {pkg_list}")
            root.destroy()
            return ok
        root.destroy()
        return False
    except Exception as e:
        _debug("DEPS", f"tkinter failed: {e}")

    if IS_WINDOWS:
        try:
            import ctypes
            MB_YESNO = 0x4
            IDYES = 6
            r = ctypes.windll.user32.MessageBoxW(0, msg, "Minecraft Server Manager - Missing Requirements", MB_YESNO)
            if r != IDYES:
                return False
            ok = do_install()
            ctypes.windll.user32.MessageBoxW(0, "Installation complete. Restart the application." if ok else f"Installation failed. Try: pip install {pkg_list}", "Minecraft Server Manager", 0x40)
            return ok
        except Exception as e:
            _debug("DEPS", f"MessageBox fallback failed: {e}")

    if IS_DARWIN:
        try:
            msg_esc = msg.replace('"', "'").replace("\n", " ")[:200]
            script = f'display dialog "{msg_esc}" with title "Minecraft Server Manager" buttons {{"Install", "Cancel"}} default button "Install"'
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            if "Install" not in (r.stdout or ""):
                return False
            ok = do_install()
            result_msg = ("Restart the application." if ok else f"Install failed. Run: pip install {pkg_list}").replace('"', "'")
            subprocess.run(["osascript", "-e", f'display dialog "{result_msg}" with title "Minecraft Server Manager" buttons {{"OK"}}'], capture_output=True)
            return ok
        except Exception as e:
            _debug("DEPS", f"osascript failed: {e}")

    if IS_LINUX:
        try:
            for cmd in ["zenity", "kdialog"]:
                try:
                    r = subprocess.run([cmd, "--question", "--text=" + msg[:500], "--title=Minecraft Server Manager"], capture_output=True)
                    if r.returncode == 0:
                        ok = do_install()
                        subprocess.run([cmd, "--msgbox", "Restart the application." if ok else f"Install failed. Run: pip install {pkg_list}"], capture_output=True)
                        return ok
                    return False
                except FileNotFoundError:
                    continue
        except Exception as e:
            _debug("DEPS", f"Linux dialog failed: {e}")

    help_path = os.path.join(BASE_DIR, "INSTALL_REQUIREMENTS.txt")
    try:
        with open(help_path, "w", encoding="utf-8") as f:
            f.write(f"Minecraft Server Manager - Missing: {pkg_list}\n\n")
            f.write("Run: pip install " + pkg_list + "\n")
            f.write("Or: pip install -r requirements.txt\n")
        if IS_WINDOWS:
            os.startfile(help_path)
        elif IS_DARWIN:
            subprocess.run(["open", help_path])
        else:
            subprocess.run(["xdg-open", help_path], capture_output=True)
    except Exception as e:
        _debug("DEPS", f"Could not write help file: {e}")
    return False

# --- Configuration ---
def validate_config(config):
    """Validates and corrects configuration values."""
    mem = str(config.get("server_memory", "4G"))
    if not re.match(r"(?i)^\d+[GM]$", mem):
        print(f"WARNING: Invalid server_memory format '{mem}'. Reverting to 4G.")
        config["server_memory"] = "4G"
    else:
        config["server_memory"] = mem.upper()

    try:
        float(config.get("restart_interval", 12))
    except ValueError:
        print("WARNING: Invalid restart_interval. Reverting to 12.0.")
        config["restart_interval"] = 12.0

    return config

def load_config():
    """Loads the server configuration from the JSON file."""
    default_config = {
        "last_server_version": "0.0.0",
        "dark_mode": True,
        "enable_logging": True,
        "check_updates": True,
        "update_to_snapshot": False,
        "modded_do_not_update": True,
        "auto_start": False,
        "enable_backups": True,
        "enable_discord": False,
        "discord_webhook": "",
        "discord_token": "",
        "discord_channel_id": 0,
        "enable_auto_restart": True,
        "enable_schedule": False,
        "restart_interval": 12,
        "server_memory": "4G",
        "max_backups": 3,
        "manager_auto_update": True,
        "start_with_windows": False
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                loaded = json.load(f)
                default_config.update(loaded)
        except Exception as e:
            print(f"Error loading config: {e}")
    
    return validate_config(default_config)

def save_config(config):
    """Saves the current configuration to the JSON file."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")

class MinecraftUpdaterCore:
    """Core logic controller for the Minecraft Server Manager."""
    
    def __init__(self, log_callback, input_callback=None, config=None, status_callback=None):
        self.log_callback = log_callback
        self.input_callback = input_callback
        self.status_callback = status_callback
        self.config = config if config else load_config()
        
        self.server_process = None
        self.stop_requested = False
        self.restart_timer = None
        self.update_timer = None
        self.monitor_thread = None
        self.start_time = None
        self.discord_bot = None

        self._lifecycle_lock = threading.Lock()
        self._starting = False

        if self.config.get("enable_discord", False) and HAS_DISCORD and self.config.get("discord_token"):
             self.start_discord_bot()

    def log(self, message, tag=None):
        self.log_callback(message, tag)
        if console and not tag:
             if not message.startswith("["):
                 ts = datetime.datetime.now().strftime("[%H:%M:%S]")
                 console.log(f"{ts} {message}")

    def update_status(self, status):
        if self.status_callback:
            self.status_callback(status)

    def get_uptime_str(self):
        """Returns current uptime string if server is running, else '00:00:00'."""
        if self.server_process and self.server_process.poll() is None and self.start_time:
            uptime = datetime.datetime.now() - self.start_time
            return str(uptime).split('.')[0]
        return "00:00:00"

    def start_discord_bot(self):
        token = self.config.get("discord_token")
        channel_id = self.config.get("discord_channel_id", 0)
        if not token: return

        class MinecraftBot(commands.Bot):
            def __init__(self, manager_core):
                intents = discord.Intents.default()
                if hasattr(intents, "message_content"):
                    intents.message_content = True
                super().__init__(command_prefix="!", intents=intents)
                self.manager = manager_core
            
            async def on_ready(self):
                self.manager.log(f"Discord Bot logged in as {self.user}")
                if channel_id:
                    channel = self.get_channel(int(channel_id))
                    if channel: await channel.send("🟢 **Minecraft Manager Connected!**")

        self.discord_bot = MinecraftBot(self)

        @self.discord_bot.command(name="status")
        async def status(ctx):
            if self.server_process:
                await ctx.send(f"✅ Server is **Running** (PID: {self.server_process.pid})")
            else:
                await ctx.send("🔴 Server is **Stopped**")

        @self.discord_bot.command(name="start")
        async def start_server_bot(ctx):
            if self.server_process:
                await ctx.send("Server is already running.")
            else:
                await ctx.send("🚀 Starting server...")
                self.start_server_sequence()

        @self.discord_bot.command(name="stop")
        async def stop_server_bot(ctx):
            if self.server_process:
                await ctx.send("🛑 Stopping server...")
                self.stop_server()
            else:
                await ctx.send("Server is already stopped.")
        
        @self.discord_bot.command(name="restart")
        async def restart_server_bot(ctx):
            await ctx.send("🔄 Restarting server...")
            self.stop_server()
            t = threading.Timer(5.0, self.start_server_sequence)
            t.daemon = True
            t.start()

        def run_bot():
            try:
                self.discord_bot.run(token)
            except Exception as e:
                print(f"Discord Bot Error: {e}")

        threading.Thread(target=run_bot, daemon=True).start()

    def check_java_version(self):
        self.log("Checking Java version...")
        try:
            kwargs = {}
            if IS_WINDOWS:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                kwargs["startupinfo"] = startupinfo
                kwargs["creationflags"] = CREATE_NO_WINDOW
                
            result = subprocess.run(["java", "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kwargs)
            output = result.stdout
            match = re.search(r'version "(?:1\.)?(\d+)', output)
            if match:
                major_version = int(match.group(1))
                if major_version >= JAVA_VERSION_REQ:
                    self.log(f"Java {major_version} detected.")
                    return True
                else:
                    self.log(f"WARNING: Java {major_version} detected, but Java {JAVA_VERSION_REQ}+ is required.")
                    return False
            return False
        except FileNotFoundError:
            self.log("ERROR: Java not found in PATH.")
            return False

    def get_local_sha1(self, filename):
        if not os.path.exists(filename): return ""
        sha = hashlib.sha1()
        try:
            with open(filename, 'rb') as f:
                while chunk := f.read(65536):
                    sha.update(chunk)
            return sha.hexdigest()
        except OSError:
            return ""

    def get_remote_version_info(self):
        """Queries Mojang for the latest server version info."""
        try:
            req = urllib.request.Request(MANIFEST_URL, headers={'User-Agent': 'MinecraftManager'})
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode())
            
            latest_type = "snapshot" if self.config.get("update_to_snapshot", False) else "release"
            target_ver_id = data['latest'][latest_type]
            
            for version in data['versions']:
                if version['id'] == target_ver_id:
                    return target_ver_id, version['url']
            return None, None
        except Exception as e:
            self.log(f"Version check failed: {e}")
            return None, None

    def check_self_update(self):
        """Checks the remote repo for a newer manager version. Returns True if update available and downloaded."""
        if not self.config.get("manager_auto_update", True):
            return False

        ts = int(time.time())
        MANAGER_URL = f"https://raw.githubusercontent.com/UnDadFeated/Minecraft_Server_Manager/master/mcsm.pyw?t={ts}"
        try:
            req = urllib.request.Request(MANAGER_URL, headers={'User-Agent': 'MinecraftManagerUpdater'})
            with urllib.request.urlopen(req, timeout=15) as response:
                remote_content = response.read().decode('utf-8')
            match = re.search(r'__version__\s*=\s*"([^"]+)"', remote_content)
            if not match:
                self.log("Could not parse remote version.")
                return False
            remote_ver = match.group(1)
            def parse_ver(v):
                return [int(x) for x in v.split('.')]
            if parse_ver(remote_ver) <= parse_ver(__version__):
                self.log("Manager is up to date.")
                return False
            self.log(f"New manager version found ({remote_ver}). Downloading...")
            script_ext = os.path.splitext(sys.argv[0])[1]
            if script_ext not in [".py", ".pyw"]:
                script_ext = ".py"
            new_file = f"mcsm{script_ext}.new"
            with open(new_file, "w", encoding='utf-8') as f:
                f.write(remote_content)
            self.log("File downloaded. Preparing installer...")
            return True
        except Exception as e:
            self.log(f"Failed to check/update manager: {e}")
            return False

    def run_update_installer(self):
        """Creates and runs a temporary script to replace the manager and restart. Waits for parent exit first."""
        args_repr = repr(sys.argv)
        installer_code = f'''
import os
import time
import sys
import subprocess

pid = {os.getpid()}
print(f"Waiting for parent process {{pid}} to close...")

def is_pid_running(p):
    try:
        if os.name == 'nt':
            output = subprocess.check_output(f'tasklist /FI "PID eq {{p}}"', shell=True, creationflags={CREATE_NO_WINDOW}).decode()
            return str(p) in output
        else:
            os.kill(p, 0)
            return True
    except Exception:
        return False

try:
    start_wait = time.time()
    while is_pid_running(pid):
        if time.time() - start_wait > 30:
            print("Timed out waiting for parent to close. Forcing update...")
            break
        time.sleep(1)

    print("Updating files...")
    time.sleep(2)

    script_ext = os.path.splitext({repr(sys.argv[0])})[1]
    if script_ext not in [".py", ".pyw"]:
        script_ext = ".py"
    old_file = f"mcsm{{script_ext}}"
    new_file = f"mcsm{{script_ext}}.new"
    if os.path.exists(new_file):
        if os.path.exists(old_file):
            os.remove(old_file)
        os.rename(new_file, old_file)
        print(f"Updated {{old_file}}")

    print("Files updated. Restarting manager...")
    if "pythonw" in sys.executable.lower():
        subprocess.Popen([sys.executable] + {args_repr}, creationflags={CREATE_NO_WINDOW})
    else:
        subprocess.Popen([sys.executable] + {args_repr})
except Exception as e:
    print(f"Update failed: {{e}}")
    if "pythonw" not in sys.executable.lower():
        input("Press Enter to exit...")
'''
        with open("updater_installer.py", "w") as f:
            f.write(installer_code)
        self.log("Launching installer and exiting...")
        if IS_WINDOWS:
            subprocess.Popen([sys.executable, "updater_installer.py"], creationflags=CREATE_NO_WINDOW)
        else:
            subprocess.Popen([sys.executable, "updater_installer.py"])
        os._exit(0)

    def has_mods(self):
        """Checks if mods are present in the mods folder."""
        if os.path.exists(MODS_DIR) and os.path.isdir(MODS_DIR):
            files = [f for f in os.listdir(MODS_DIR) if f.endswith(".jar")]
            return len(files) > 0
        return False

    def update_server(self):
        """Checks for and applies Minecraft server updates. Returns True if update was applied."""
        if self.has_mods() and self.config.get("modded_do_not_update", True):
            self.log("Mods detected and 'Do Not Update (Modded)' is active. Skipping server update.")
            return False

        self.log("Checking for Minecraft updates...")
        target_ver, json_url = self.get_remote_version_info()
        if not target_ver:
            return False

        local_ver = self.config.get("last_server_version", "0.0.0")
        if target_ver == local_ver:
            self.log(f"Minecraft {target_ver} is up to date.")
            return False

        self.log(f"New Minecraft version available: {target_ver}")
        try:
            req = urllib.request.Request(json_url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                ver_data = json.loads(resp.read().decode())
            
            download_url = ver_data['downloads']['server']['url']
            remote_sha = ver_data['downloads']['server']['sha1']
            
            if self.get_local_sha1(SERVER_JAR) == remote_sha:
                self.log("Local JAR matches remote SHA1. Skipping download.")
                self.config["last_server_version"] = target_ver
                save_config(self.config)
                return True
            else:
                self.log(f"Downloading {SERVER_JAR}...")
                req_dl = urllib.request.Request(download_url)
                with urllib.request.urlopen(req_dl, timeout=30) as dl_resp:
                    with open(SERVER_JAR, "wb") as f:
                        while chunk := dl_resp.read(65536):
                            f.write(chunk)
            
            self.config["last_server_version"] = target_ver
            save_config(self.config)
            self.log(f"Updated to version {target_ver}")
            return True
        except Exception as e:
            self.log(f"Update failed: {e}")
            return False

    def stop_existing_server_process(self):
        """Detects and stops any running instance of the Minecraft server."""
        self.log("Checking for running Minecraft server...")
        if IS_WINDOWS:
            try:
                kwargs = {}
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                kwargs["startupinfo"] = startupinfo
                kwargs["creationflags"] = CREATE_NO_WINDOW
                cmd = (
                    'powershell -NoProfile -Command "'
                    'Get-WmiObject Win32_Process | '
                    'Where-Object { $_.Name -eq \'java.exe\' -and $_.CommandLine -like \'*' + SERVER_JAR + '*\' } | '
                    'Select-Object -ExpandProperty ProcessId"'
                )
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True, **kwargs)
                for line in result.stdout.splitlines():
                    pid = line.strip()
                    if pid.isdigit():
                        self.log(f"Found running server (PID: {pid}). Stopping...")
                        subprocess.run(f"taskkill /PID {pid} /F", shell=True, creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass
        else:
            try:
                cmd = ["pgrep", "-f", SERVER_JAR]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0 and result.stdout.strip():
                    for pid in result.stdout.strip().splitlines():
                        self.log(f"Found running server (PID: {pid}). Stopping...")
                        subprocess.run(["kill", pid])
            except Exception:
                pass

    def send_command(self, command):
        if self.server_process and self.server_process.poll() is None:
            try:
                self.log(f"> {command}")
                self.server_process.stdin.write((command + "\n").encode())
                self.server_process.stdin.flush()
            except OSError:
                pass

    def backup_world(self):
        """Creates a backup of the world directory."""
        if not self.config.get("enable_backups", True):
            return
        if not os.path.exists(WORLD_DIR):
            self.log(f"Backup skipped: World directory not found at {WORLD_DIR}")
            return
        self.log("Creating world backup...")
        if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = os.path.join(BACKUP_DIR, f"world_{ts}")
        try:
            shutil.make_archive(name, 'zip', WORLD_DIR)
            max_b = int(self.config.get("max_backups", 3))
            backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("world_") and f.endswith(".zip")])
            if len(backups) > max_b:
                for old in backups[:-max_b]:
                    os.remove(os.path.join(BACKUP_DIR, old))
        except Exception as e:
            self.log(f"Backup error: {e}")

    def send_discord_webhook(self, message):
        """Sends a status message to the configured Discord webhook or bot."""
        if not self.config.get("enable_discord", False):
            return
        url = self.config.get("discord_webhook", "").strip()
        token = self.config.get("discord_token", "").strip()
        channel = self.config.get("discord_channel_id", 0)

        if url:
            try:
                data = json.dumps({"content": message}).encode()
                req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'MCSM-Bot'})
                with urllib.request.urlopen(req, timeout=10):
                    pass
            except Exception:
                pass
        elif token and channel:
            try:
                api_url = f"https://discord.com/api/v10/channels/{channel}/messages"
                data = json.dumps({"content": message}).encode()
                req = urllib.request.Request(api_url, data=data, headers={
                    'Authorization': f'Bot {token}',
                    'Content-Type': 'application/json',
                    'User-Agent': 'MCSM-Bot'
                })
                with urllib.request.urlopen(req, timeout=10):
                    pass
            except Exception:
                pass

    def start_server_sequence(self):
        threading.Thread(target=self._start_server_thread, daemon=True).start()

    def _start_server_thread(self):
        with self._lifecycle_lock:
            if self.server_process and self.server_process.poll() is None: return
            if getattr(self, '_starting', False): return
            self._starting = True
            self.stop_requested = False

        try:
            if self.check_self_update():
                self.run_update_installer()
                return

            if not self.check_java_version(): return

            if self.config.get("check_updates", True):
                self.update_server()

            self.stop_existing_server_process()
            self.backup_world()

            self.log("Starting Minecraft Server...")
            self.send_discord_webhook("🟢 Minecraft Server Starting...")

            mem = self.config.get("server_memory", "4G")
            cmd = ["java", f"-Xmx{mem}", f"-Xms{mem}", "-jar", SERVER_JAR, "nogui"]

            startupinfo = None
            creationflags = 0
            if IS_WINDOWS:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = CREATE_NO_WINDOW
            
            self.server_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                startupinfo=startupinfo, creationflags=creationflags
            )
            self.start_time = datetime.datetime.now()
            self.update_status({"state": "Running", "pid": self.server_process.pid})
            
            threading.Thread(target=self._read_stream, args=(self.server_process.stdout, "stdout"), daemon=True).start()
            threading.Thread(target=self._read_stream, args=(self.server_process.stderr, "stderr"), daemon=True).start()
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            self.start_update_checker()

            if self.config.get("enable_schedule", False):
                self._schedule_restart()
        except Exception as e:
            self.log(f"Startup failed: {e}")
        finally: self._starting = False

    def _read_stream(self, stream, tag):
        try:
            for line in iter(stream.readline, b''):
                if line: self.log(line.decode(errors='replace').strip(), tag)
        except Exception as e:
            self.log(f"Stream read error ({tag}): {e}", tag="stderr")
        finally: stream.close()

    def _monitor_loop(self):
        while self.server_process and self.server_process.poll() is None:
            if self.start_time:
                upt = str(datetime.datetime.now() - self.start_time).split('.')[0]
                self.update_status({"state": "Running", "pid": self.server_process.pid, "uptime": upt})
            time.sleep(1)
        
        rc = self.server_process.returncode if self.server_process else 0
        self.log(f"Server exited (Code {rc})")
        self.server_process = None
        self.update_status({"state": "Stopped"})
        self.send_discord_webhook(f"🔴 Server Stopped (Code {rc})")
        if rc != 0 and not self.stop_requested and self.config.get("enable_auto_restart", True):
            self.log("Crash detected. Restarting in 10s...")
            time.sleep(10)
            self.start_server_sequence()

    def start_update_checker(self):
        """Starts the background update checker (every 30 min). Restarts server when update applied."""
        if not self.config.get("check_updates", True):
            return
        interval = 1800
        self.log(f"Starting background update checker (every {interval}s).")

        def update_task():
            if self.stop_requested or not self.server_process:
                return
            self._run_background_update_check()
            if not self.stop_requested and self.server_process:
                self.update_timer = threading.Timer(interval, update_task)
                self.update_timer.daemon = True
                self.update_timer.start()

        self.update_timer = threading.Timer(interval, update_task)
        self.update_timer.daemon = True
        self.update_timer.start()

    def _run_background_update_check(self):
        """Checks for updates in background and restarts server if new JAR was applied."""
        try:
            if self.check_self_update():
                self.log("[Background Check] New manager version found! Restarting application to apply...")
                self.send_discord_webhook("🔄 New Manager Update found! Restarting application...")
                self.stop_server()

                def delayed_installer():
                    while self.server_process and self.server_process.poll() is None:
                        time.sleep(1)
                    self.run_update_installer()

                threading.Thread(target=delayed_installer, daemon=True).start()
                return

            updated = self.update_server()
            if updated:
                self.log("[Background Check] Server JAR updated. Restarting to apply...")
                self.send_discord_webhook("🚀 New Minecraft update applied! Restarting server...")
                self.restart_server()
        except Exception as e:
            self.log(f"Background update check failed: {e}")

    def restart_server(self):
        self.stop_server()
        timer = threading.Timer(5.0, self.start_server_sequence)
        timer.daemon = True
        timer.start()

    def stop_server(self):
        self.stop_requested = True
        if self.restart_timer: self.restart_timer.cancel()
        if self.update_timer: self.update_timer.cancel()
        if self.server_process:
            self.log("Stopping server...")
            try:
                if self.server_process.stdin:
                    self.server_process.stdin.write(b"stop\n")
                    self.server_process.stdin.flush()
                self.server_process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.log("Server did not stop in time. Killing process...")
                if self.server_process:
                    self.server_process.kill()
                    self.server_process.wait()
            except Exception as e:
                self.log(f"Error stopping server: {e}")
                if self.server_process: self.server_process.kill()

    def _schedule_restart(self):
        hrs = float(self.config.get("restart_interval", 12))
        self.restart_timer = threading.Timer(hrs * 3600, self.restart_server)
        self.restart_timer.daemon = True
        self.restart_timer.start()

# --- CLI Utilities ---
def install_service():
    """Installs the manager as a systemd service (Linux only)."""
    if not IS_LINUX:
        print("Service installation requires Linux with systemd.")
        if IS_DARWIN:
            print("On macOS, use launchd or add to Login Items manually.")
        return
    if os.geteuid() != 0:
        print("Error: This command must be run as root (sudo).")
        return
    service_path = "/etc/systemd/system/minecraft-manager.service"
    script_path = os.path.abspath(__file__)
    working_dir = os.path.dirname(script_path)
    user = os.environ.get('SUDO_USER', 'root')
    content = f"""[Unit]
Description=Minecraft Server Manager
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={working_dir}
ExecStart={sys.executable} {script_path} -nogui
Restart=always

[Install]
WantedBy=multi-user.target
"""
    try:
        with open(service_path, "w") as f:
            f.write(content)
        print(f"Service file created at {service_path}")
        subprocess.run(["systemctl", "daemon-reload"])
        subprocess.run(["systemctl", "enable", "minecraft-manager"])
        print("Service enabled! Start with: sudo systemctl start minecraft-manager")
    except Exception as e:
        print(f"Failed to install service: {e}")

def enable_autostart():
    """Enables auto-start for the current user (Linux Desktop)."""
    if IS_WINDOWS:
        print("Use the GUI 'Start with Windows' option on Windows.")
        return
    if IS_DARWIN:
        print("macOS CLI autostart is not supported. Add to System Preferences > Login Items.")
        return
    autostart_dir = os.path.expanduser("~/.config/autostart")
    if not os.path.exists(autostart_dir):
        os.makedirs(autostart_dir)
    desktop_file = os.path.join(autostart_dir, "minecraft-manager.desktop")
    script_path = os.path.abspath(__file__)
    working_dir = os.path.dirname(script_path)
    content = f"""[Desktop Entry]
Type=Application
Name=Minecraft Server Manager
Exec={sys.executable} {script_path}
Path={working_dir}
Terminal=false
"""
    try:
        with open(desktop_file, "w") as f:
            f.write(content)
        print(f"Auto-start entry created at {desktop_file}")
    except Exception as e:
        print(f"Failed to enable auto-start: {e}")

# --- Modes ---
def run_console_mode():
    def console_logger(msg, tag=None):
        ts = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        if not console: print(f"{ts} {msg}")
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{ts} {msg}\n")
        except OSError: pass
    config = load_config()
    core = MinecraftUpdaterCore(console_logger, input_callback=input, config=config)
    core.start_server_sequence()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt: core.stop_server()

def run_gui_mode():
    """Starts the graphical user interface using PySide6."""
    _debug("GUI", "run_gui_mode() entered")
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGroupBox, QLabel, QPushButton, QCheckBox, QLineEdit,
        QPlainTextEdit, QFrame, QMessageBox,
    )
    from PySide6.QtCore import Qt, QTimer, QUrl
    from PySide6.QtGui import QPalette, QColor, QFont, QTextCursor, QTextCharFormat, QImage, QPainter, QPen, QDesktopServices

    def ensure_check_icons():
        for path, fg in [(CHECK_WHITE_PNG, QColor(255, 255, 255)), (CHECK_BLACK_PNG, QColor(0, 0, 0))]:
            if os.path.exists(path):
                continue
            img = QImage(14, 14, QImage.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(fg, 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawLine(2, 7, 5, 10)
            p.drawLine(5, 10, 12, 2)
            p.end()
            img.save(path)

    class MinecraftGUI(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f"Minecraft Server Manager v{__version__}")
            self.setFixedSize(1080, 800)
            self.config = load_config()
            self.is_dark = self.config.get("dark_mode", True)
            self.log_queue = queue.Queue()
            self.core = MinecraftUpdaterCore(self.log_queue_wrapper, None, self.config, self.update_stats)
            self.setup_ui()
            self.apply_theme()
            self.log_timer = QTimer(self)
            self.log_timer.timeout.connect(self.drain_log_queue)
            self.log_timer.start(80)
            self.uptime_timer = QTimer(self)
            self.uptime_timer.timeout.connect(self._refresh_uptime)
            self.uptime_timer.start(1000)
            if self.config.get("auto_start", False):
                QTimer.singleShot(1000, self.start_server)

        def setup_ui(self):
            cw = QWidget()
            self.setCentralWidget(cw)
            main = QVBoxLayout(cw)
            main.setContentsMargins(6, 4, 6, 6)
            main.setSpacing(2)

            header = QHBoxLayout()
            title = QLabel(f"Minecraft Server Manager v{__version__}")
            title.setStyleSheet("font-weight: bold; font-size: 13px;")
            header.addWidget(title)
            header.addStretch()
            main.addLayout(header)

            controls = QGroupBox("Controls & Configuration")
            controls_layout = QHBoxLayout(controls)
            controls_layout.setContentsMargins(6, 10, 6, 6)
            controls_layout.setSpacing(16)

            col1 = QVBoxLayout()
            col1.setSpacing(6)
            self.cb_logging = QCheckBox("Enable File Logging")
            self.cb_logging.setChecked(self.config.get("enable_logging", True))
            self.cb_logging.stateChanged.connect(self.save)
            col1.addWidget(self.cb_logging)
            self.cb_autostart = QCheckBox("Auto-Start Server")
            self.cb_autostart.setChecked(self.config.get("auto_start", False))
            self.cb_autostart.stateChanged.connect(self.save)
            col1.addWidget(self.cb_autostart)
            self.cb_restart = QCheckBox("Auto-Restart on Crash")
            self.cb_restart.setChecked(self.config.get("enable_auto_restart", True))
            self.cb_restart.stateChanged.connect(self.save)
            col1.addWidget(self.cb_restart)
            ram_row = QHBoxLayout()
            ram_row.addWidget(QLabel("Server RAM:"))
            self.entry_memory = QLineEdit()
            self.entry_memory.setMaximumWidth(60)
            self.entry_memory.setText(self.config.get("server_memory", "4G"))
            self.entry_memory.editingFinished.connect(self.save)
            ram_row.addWidget(self.entry_memory)
            ram_row.addStretch()
            col1.addLayout(ram_row)
            controls_layout.addLayout(col1)

            col2 = QVBoxLayout()
            col2.setSpacing(6)
            self.cb_check_upd = QCheckBox("Check for new server updates")
            self.cb_check_upd.setChecked(self.config.get("check_updates", True))
            self.cb_check_upd.stateChanged.connect(self._on_check_updates_toggled)
            col2.addWidget(self.cb_check_upd)
            self.cb_mod_no_upd = QCheckBox("Do not update if modded")
            self.cb_mod_no_upd.setChecked(not self.config.get("check_updates", True))
            self.cb_mod_no_upd.stateChanged.connect(self._on_mod_no_upd_toggled)
            col2.addWidget(self.cb_mod_no_upd)
            self.cb_snapshot = QCheckBox("Latest Snapshots")
            self.cb_snapshot.setChecked(self.config.get("update_to_snapshot", False))
            self.cb_snapshot.stateChanged.connect(self.save)
            col2.addWidget(self.cb_snapshot)
            bkp_row = QHBoxLayout()
            self.cb_backup = QCheckBox("Backup World on Start")
            self.cb_backup.setChecked(self.config.get("enable_backups", True))
            self.cb_backup.stateChanged.connect(self.save)
            bkp_row.addWidget(self.cb_backup)
            bkp_row.addWidget(QLabel("Max:"))
            self.entry_max_backups = QLineEdit()
            self.entry_max_backups.setMaximumWidth(30)
            self.entry_max_backups.setText(str(self.config.get("max_backups", 3)))
            self.entry_max_backups.editingFinished.connect(self.save)
            bkp_row.addWidget(self.entry_max_backups)
            bkp_row.addStretch()
            col2.addLayout(bkp_row)
            sch_row = QHBoxLayout()
            self.cb_schedule = QCheckBox("Schedule Restart (Hrs)")
            self.cb_schedule.setChecked(self.config.get("enable_schedule", False))
            self.cb_schedule.stateChanged.connect(self.save)
            sch_row.addWidget(self.cb_schedule)
            self.entry_schedule = QLineEdit()
            self.entry_schedule.setMaximumWidth(45)
            self.entry_schedule.setText(str(self.config.get("restart_interval", 12)))
            self.entry_schedule.editingFinished.connect(self.save)
            sch_row.addWidget(self.entry_schedule)
            sch_row.addStretch()
            col2.addLayout(sch_row)
            controls_layout.addLayout(col2)

            dsc_box = QFrame()
            dsc_box.setFrameShape(QFrame.StyledPanel)
            dsc_layout = QVBoxLayout(dsc_box)
            dsc_layout.setContentsMargins(4, 4, 4, 4)
            dsc_layout.setSpacing(1)
            self.cb_discord = QCheckBox("Discord Integration")
            self.cb_discord.setChecked(self.config.get("enable_discord", False))
            self.cb_discord.stateChanged.connect(self.save)
            dsc_layout.addWidget(self.cb_discord)
            for lbl, attr, secure in [("Webhook:", "entry_webhook", False), ("Token:", "entry_token", True), ("Channel:", "entry_channel", False)]:
                row = QHBoxLayout()
                row.addWidget(QLabel(lbl))
                e = QLineEdit()
                if secure:
                    e.setEchoMode(QLineEdit.Password)
                setattr(self, attr, e)
                if attr == "entry_webhook":
                    e.setText(self.config.get("discord_webhook", ""))
                elif attr == "entry_token":
                    e.setText(self.config.get("discord_token", ""))
                else:
                    e.setText(str(self.config.get("discord_channel_id", 0)))
                e.setMinimumWidth(100)
                e.editingFinished.connect(self.save)
                row.addWidget(e)
                dsc_layout.addLayout(row)
            controls_layout.addWidget(dsc_box)

            def open_dir(path):
                try:
                    p = os.path.abspath(path)
                    if not os.path.exists(p):
                        os.makedirs(p)
                    QDesktopServices.openUrl(QUrl.fromLocalFile(p))
                except Exception as ex:
                    QMessageBox.critical(self, "Error", f"Could not open directory: {ex}")

            nav_col = QVBoxLayout()
            nav_col.setSpacing(1)
            for lbl, path in [("Server", "."), ("Worlds", WORLD_DIR), ("Backups", BACKUP_DIR)]:
                b = QPushButton(lbl)
                b.setFixedWidth(70)
                b.setFixedHeight(22)
                b.clicked.connect(lambda checked, p=path: open_dir(p))
                nav_col.addWidget(b)
            nav_col.addSpacing(4)
            self.lbl_status = QLabel("Status: <span style='color:#e53935'>Stopped</span>")
            self.lbl_status.setObjectName("statusLbl")
            self.lbl_status.setTextFormat(Qt.RichText)
            self.lbl_status.setStyleSheet("font-weight: bold;")
            nav_col.addWidget(self.lbl_status)
            controls_layout.addLayout(nav_col)

            action_col = QVBoxLayout()
            action_col.setSpacing(2)
            self.btn_start = QPushButton("START SERVER")
            self.btn_start.setFixedHeight(26)
            self.btn_start.setFixedWidth(140)
            self.btn_start.setObjectName("btnStart")
            self.btn_start.clicked.connect(self.start_server)
            action_col.addWidget(self.btn_start)
            self.btn_stop = QPushButton("STOP SERVER")
            self.btn_stop.setFixedHeight(26)
            self.btn_stop.setFixedWidth(140)
            self.btn_stop.setObjectName("btnStop")
            self.btn_stop.setEnabled(False)
            self.btn_stop.clicked.connect(self.stop_server)
            action_col.addWidget(self.btn_stop)
            ver_lbl = QLabel(f"Version: {self.config.get('last_server_version', 'Unknown')}")
            ver_lbl.setObjectName("mutedLbl")
            action_col.addWidget(ver_lbl, 0, Qt.AlignHCenter)
            stats_row = QHBoxLayout()
            self.lbl_cpu = QLabel("CPU: 0%")
            self.lbl_ram = QLabel("RAM: 0%")
            self.lbl_cpu.setObjectName("mutedLbl")
            self.lbl_ram.setObjectName("mutedLbl")
            stats_row.addWidget(self.lbl_cpu)
            stats_row.addWidget(self.lbl_ram)
            stats_container = QWidget()
            stats_container.setLayout(stats_row)
            action_col.addWidget(stats_container, 0, Qt.AlignHCenter)
            self.lbl_uptime = QLabel("Uptime: 00:00:00")
            self.lbl_uptime.setStyleSheet("font-size: 10px;")
            action_col.addWidget(self.lbl_uptime, 0, Qt.AlignHCenter)
            controls_layout.addLayout(action_col)

            main.addWidget(controls)

            self.console = QPlainTextEdit()
            self.console.setReadOnly(True)
            self.console.setFont(QFont("Consolas", 8))
            self.console.setMaximumBlockCount(1000)
            self.console.setMinimumHeight(300)
            main.addWidget(self.console, 1)

            cmd_frame = QFrame()
            cmd_frame.setObjectName("cmdBar")
            cmd_layout = QHBoxLayout(cmd_frame)
            cmd_layout.setContentsMargins(0, 2, 0, 2)
            cmd_layout.addWidget(QLabel("Command:"))
            self.entry_cmd = QLineEdit()
            self.entry_cmd.setPlaceholderText("Enter server command...")
            self.entry_cmd.returnPressed.connect(self.send_command_ui)
            cmd_layout.addWidget(self.entry_cmd)
            main.addWidget(cmd_frame)

            footer_frame = QFrame()
            footer_frame.setObjectName("footerBar")
            footer_frame.setMaximumHeight(35)
            footer = QHBoxLayout(footer_frame)
            footer.setSpacing(6)
            footer.setContentsMargins(3, 0, 3, 2)
            footer.setAlignment(Qt.AlignVCenter)
            theme_btn = QPushButton("Toggle Theme")
            theme_btn.setFixedHeight(24)
            theme_btn.clicked.connect(self.toggle_theme)
            footer.addWidget(theme_btn)
            btn_check = QPushButton("Check for updates")
            btn_check.setFixedHeight(24)
            btn_check.clicked.connect(self.check_updates_ui)
            self.cb_mgr_update = QCheckBox("Auto-Update Manager")
            self.cb_mgr_update.setChecked(self.config.get("manager_auto_update", True))
            self.cb_mgr_update.stateChanged.connect(self.save)
            footer.addWidget(self.cb_mgr_update)
            self.cb_start_win = QCheckBox("Start with Windows")
            self.cb_start_win.setChecked(self.config.get("start_with_windows", False))
            self.cb_start_win.stateChanged.connect(self.save_and_set_autostart)
            if not IS_WINDOWS:
                self.cb_start_win.setEnabled(False)
            footer.addWidget(self.cb_start_win)
            footer.addStretch()
            footer.addWidget(btn_check)
            btn_coffee = QPushButton("☕ Support the Development")
            btn_coffee.setFixedHeight(24)
            btn_coffee.clicked.connect(lambda: webbrowser.open("https://www.paypal.me/jscheema/5"))
            footer.addWidget(btn_coffee)
            main.addWidget(footer_frame)

        def check_updates_ui(self):
            self.core.log("Checking for manager updates...")
            if self.core.check_self_update():
                self.core.log("Manager update found. Restarting...")
                self.core.stop_server()
                def do_install():
                    while self.core.server_process and self.core.server_process.poll() is None:
                        time.sleep(0.5)
                    self.core.run_update_installer()
                threading.Thread(target=do_install, daemon=True).start()
            else:
                self.core.log("Manager is up to date.")

        def send_command_ui(self):
            cmd = self.entry_cmd.text().strip()
            if cmd:
                self.core.send_command(cmd)
                self.entry_cmd.clear()
                self.entry_cmd.setFocus()

        def start_server(self):
            self.save()
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.core.start_server_sequence()

        def stop_server(self):
            self.core.stop_server()
            self.btn_stop.setEnabled(False)

        def save(self):
            ch = self.entry_channel.text().strip()
            mb = self.entry_max_backups.text().strip()
            self.config.update({
                "enable_logging": self.cb_logging.isChecked(),
                "check_updates": self.cb_check_upd.isChecked(),
                "update_to_snapshot": self.cb_snapshot.isChecked(),
                "modded_do_not_update": self.cb_mod_no_upd.isChecked(),
                "auto_start": self.cb_autostart.isChecked(),
                "enable_backups": self.cb_backup.isChecked(),
                "enable_discord": self.cb_discord.isChecked(),
                "enable_auto_restart": self.cb_restart.isChecked(),
                "enable_schedule": self.cb_schedule.isChecked(),
                "discord_webhook": self.entry_webhook.text(),
                "discord_token": self.entry_token.text(),
                "discord_channel_id": int(ch) if ch.isdigit() else 0,
                "restart_interval": self.entry_schedule.text(),
                "server_memory": self.entry_memory.text(),
                "max_backups": int(mb) if mb.isdigit() else 3,
                "manager_auto_update": self.cb_mgr_update.isChecked(),
                "start_with_windows": self.cb_start_win.isChecked(),
                "dark_mode": self.is_dark,
            })
            self.core.config = self.config
            save_config(self.config)

        def save_and_set_autostart(self):
            self.save()
            if IS_WINDOWS:
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
                    if self.cb_start_win.isChecked():
                        script_path = os.path.abspath(sys.argv[0])
                        python_exe = sys.executable
                        if "pythonw.exe" not in python_exe.lower():
                            pw = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
                            python_exe = pw if os.path.exists(pw) else pw
                        cmd = f'"{python_exe}" "{script_path}" --startup-delay'
                        winreg.SetValueEx(key, "MinecraftServerManager", 0, winreg.REG_SZ, cmd)
                    else:
                        try:
                            winreg.DeleteValue(key, "MinecraftServerManager")
                        except OSError:
                            pass
                    winreg.CloseKey(key)
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to set registry key: {e}")

        def _refresh_uptime(self):
            running = self.core.server_process is not None and self.core.server_process.poll() is None
            if running:
                self.lbl_status.setText("Status: <span style='color:#43a047'>Running</span>")
                self.btn_start.setEnabled(False)
                self.btn_stop.setEnabled(True)
            else:
                self.lbl_status.setText("Status: <span style='color:#e53935'>Stopped</span>")
                self.btn_start.setEnabled(True)
                self.btn_stop.setEnabled(False)
            s = self.core.get_uptime_str()
            uptime_text = f"Uptime: {s}"
            if self.lbl_uptime.text() != uptime_text:
                self.lbl_uptime.setText(uptime_text)
            if HAS_PSUTIL:
                try:
                    cpu_load = psutil.cpu_percent(interval=0.1)
                    ram_load = psutil.virtual_memory().percent
                    self.lbl_cpu.setText(f"CPU: {cpu_load}%")
                    self.lbl_ram.setText(f"RAM: {ram_load}%")
                except Exception:
                    pass
            else:
                self.lbl_cpu.setText("CPU: N/A")
                self.lbl_ram.setText("RAM: N/A")

        def _on_check_updates_toggled(self):
            self.cb_mod_no_upd.blockSignals(True)
            self.cb_mod_no_upd.setChecked(not self.cb_check_upd.isChecked())
            self.cb_mod_no_upd.blockSignals(False)
            self.save()

        def _on_mod_no_upd_toggled(self):
            self.cb_check_upd.blockSignals(True)
            self.cb_check_upd.setChecked(not self.cb_mod_no_upd.isChecked())
            self.cb_check_upd.blockSignals(False)
            self.save()

        def update_stats(self, status):
            def apply():
                state = status.get("state", "Unknown")
                if not HAS_PSUTIL:
                    self.lbl_cpu.setText("CPU: N/A")
                    self.lbl_ram.setText("RAM: N/A")
                if state == "Stopped":
                    self.btn_start.setEnabled(True)
                    self.btn_stop.setEnabled(False)
                    self.lbl_status.setText("Status: <span style='color:#e53935'>Stopped</span>")
                    self.lbl_uptime.setText("Uptime: 00:00:00")
                elif state == "Running":
                    self.btn_start.setEnabled(False)
                    self.btn_stop.setEnabled(True)
                    self.lbl_status.setText("Status: <span style='color:#43a047'>Running</span>")
                    self.lbl_uptime.setText(f"Uptime: {status.get('uptime', '00:00:00')}")
            QTimer.singleShot(0, apply)

        def log_queue_wrapper(self, msg, tag=None):
            timestamp = datetime.datetime.now().strftime("[%H:%M:%S]")
            self.log_queue.put((f"{timestamp} {msg}\n", tag))
            if self.cb_logging.isChecked():
                clean_msg = re.sub(r"\x1b\[[0-9;]*m", "", f"{timestamp} {msg}\n")
                try:
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(clean_msg)
                except OSError:
                    pass

        def drain_log_queue(self):
            while not self.log_queue.empty():
                try:
                    msg, tag = self.log_queue.get_nowait()
                except queue.Empty:
                    break
                self.insert_colored(msg, tag)
                scrollbar = self.console.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

        def insert_colored(self, text, tag):
            cursor = self.console.textCursor()
            cursor.movePosition(QTextCursor.End)
            parts = re.split(r"(\x1b\[[0-9;]*m)", text)
            current_color = "#ff5555" if tag == "stderr" else None
            for part in parts:
                if part.startswith("\x1b["):
                    raw = part.strip()
                    code = raw[2:-1].split(";")[-1] if raw.endswith("m") and len(raw) > 2 else ""
                    if code == "0":
                        current_color = None
                    elif code in ("31", "91"):
                        current_color = "#ff5555"
                    elif code in ("32", "92"):
                        current_color = "#55ff55" if self.is_dark else "#00aa00"
                    elif code in ("33", "93"):
                        current_color = "#ffff55" if self.is_dark else "#aaaa00"
                    elif code in ("36", "96"):
                        current_color = "#55ffff" if self.is_dark else "#00aaaa"
                else:
                    if part:
                        fmt = QTextCharFormat()
                        if current_color:
                            fmt.setForeground(QColor(current_color))
                        cursor.setCharFormat(fmt)
                        cursor.insertText(part)

        def apply_theme(self):
            from urllib.parse import quote
            def icon_url(p):
                path = os.path.abspath(p).replace("\\", "/")
                return "file:///" + quote(path, safe="/:")
            check_w = icon_url(CHECK_WHITE_PNG)
            if self.is_dark:
                bg, fg = "#0b0b0b", "#e0e0e0"
                input_bg, input_fg = "#222222", "#e0e0e0"
                console_bg, console_fg = "#0c0c0c", "#d4d4d4"
                muted, cb_hover = "#9d9d9d", "#3fb950"
                btn_bg, btn_hover_bg, btn_border = "#181818", "#202020", "#333333"
                cb_checked = f"background: {cb_hover}; border-color: {cb_hover}; image: url({check_w!r});"
                input_border = f"border: 1px solid {btn_border};"
                group_border = f"border: 1px solid {btn_border}; border-radius: 4px; background: transparent;"
                frame_border = f"border: 1px solid {btn_border}; border-radius: 4px; background: transparent;"
                btn_border_style = f"border: 1px solid {btn_border}; border-radius: 4px;"
                footer_bg = "transparent"
            else:
                bg, fg = "#d4d0c8", "#000000"
                input_bg, input_fg = "#ffffff", "#000000"
                console_bg, console_fg = "#0c0c0c", "#d4d4d4"
                muted, cb_hover = "#404040", "#000080"
                btn_bg, btn_hover_bg, btn_border = "#d4d0c8", "#d4d0c8", "#808080"
                cb_checked = f"background: #404040; border: 1px solid #808080; border-radius: 0; image: url({check_w!r});"
                input_border = "border: 2px inset; border-color: #808080 #c0c0c0 #c0c0c0 #808080;"
                group_border = "border: 2px outset; border-color: #ffffff #808080 #808080 #ffffff; border-radius: 0;"
                frame_border = "border: 2px inset; border-color: #808080 #c0c0c0 #c0c0c0 #808080; border-radius: 0;"
                btn_border_style = "border: 2px outset; border-color: #ffffff #808080 #808080 #ffffff; border-radius: 0;"
                footer_bg = bg
            p = self.palette()
            p.setColor(QPalette.Window, QColor(bg))
            p.setColor(QPalette.WindowText, QColor(fg))
            p.setColor(QPalette.Base, QColor(input_bg))
            p.setColor(QPalette.Text, QColor(fg))
            p.setColor(QPalette.Button, QColor(bg))
            p.setColor(QPalette.ButtonText, QColor(fg))
            self.setPalette(p)
            qss = f"""
                QMainWindow, QWidget {{ background: {bg}; }}
                #footerBar, #cmdBar {{ background: {footer_bg}; }}
                #footerBar QPushButton {{ font-size: 10px; padding: 2px 6px; min-height: 20px; }}
                QCheckBox {{ color: {fg}; padding: 2px; background-color: transparent; }}
                QCheckBox::indicator {{ background: {input_bg}; border: 1px solid {btn_border}; border-radius: 2px; width: 13px; height: 13px; }}
                QCheckBox::indicator:checked {{ {cb_checked} }}
                QLineEdit {{ background: {input_bg}; color: {input_fg}; padding: 2px; {input_border} }}
                QGroupBox {{ color: {fg}; font-weight: bold; padding-top: 6px; margin-top: 4px; {group_border} }}
                QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {fg}; }}
                QFrame {{ color: {fg}; {frame_border} padding: 4px; }}
                QLabel {{ color: {fg}; border: none; background: transparent; }}
                #mutedLbl {{ font-size: 10px; color: {muted}; margin: 0; padding: 0; }}
                #statusLbl {{ border: none; background: transparent; padding: 2px 0; min-height: 1.2em; }}
                QPushButton {{ {btn_border_style} padding: 4px 8px; color: {fg}; background: {btn_bg}; }}
                QPushButton:hover {{ border: 2px solid {cb_hover}; background: {btn_hover_bg}; }}
                QPushButton:disabled {{ opacity: 0.5; }}
                #btnStart {{ font-weight: bold; color: #3fb950; }}
                #btnStart:hover {{ border: 2px solid #3fb950; background: #1a3d1a; }}
                #btnStart:disabled {{ color: #666; }}
                #btnStop {{ font-weight: bold; color: #D13438; }}
                #btnStop:hover {{ border: 2px solid #ff6b6b; background: #4d1a1a; }}
                #btnStop:disabled {{ color: #666; }}
            """
            self.setStyleSheet(qss)
            self.console.setStyleSheet(f"QPlainTextEdit {{ background: {console_bg}; color: {console_fg}; font-family: Consolas; font-size: 11px; }}")
            self._refresh_uptime()

        def toggle_theme(self):
            self.is_dark = not self.is_dark
            self.config["dark_mode"] = self.is_dark
            self.apply_theme()
            self.save()

        def closeEvent(self, event):
            if self.core.server_process and self.core.server_process.poll() is None:
                reply = QMessageBox.question(
                    self, "Quit",
                    "Server is running. Do you want to stop it and quit?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.core.stop_server()
                    event.accept()
                    QApplication.quit()
                else:
                    event.ignore()
            else:
                event.accept()
                QApplication.quit()

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setStyle("Fusion")
    ensure_check_icons()
    window = MinecraftGUI()
    window.show()
    sys.exit(app.exec())

def print_help():
    abs_config_path = os.path.abspath(CONFIG_FILE)
    print(f"Minecraft Server Manager v{__version__}")
    print("=" * 60)
    print("Usage: python mcsm.pyw [options]")
    print("\nCommand Line Options:")
    print("  -nogui             : Run in console-only mode (headless).")
    print("  -install-service   : (Linux) Installs systemd service.")
    print("  -enable-autostart  : (Linux) Adds to desktop auto-start.")
    print("  -help, --help      : Show this help message.")
    print("\nConfiguration File:")
    print(f"  {abs_config_path}")
    print("=" * 60)
    sys.exit(0)

# --- Main ---
IS_PYTHONW = IS_WINDOWS and "pythonw" in sys.executable.lower()

def main():
    _debug("MAIN", "entering main()")
    os.chdir(BASE_DIR)

    if "--startup-delay" in sys.argv:
        _debug("MAIN", "startup-delay: sleeping 30s")
        time.sleep(30)
        sys.argv.remove("--startup-delay")

    if os.path.exists("updater_installer.py"):
        try:
            os.remove("updater_installer.py")
        except OSError:
            pass
    for f in ["mcsm.py.new", "mcsm.pyw.new"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

    if "-help" in sys.argv or "--help" in sys.argv:
        print_help()

    if "-install-service" in sys.argv:
        install_service()
        sys.exit(0)

    if "-enable-autostart" in sys.argv:
        enable_autostart()
        sys.exit(0)

    ok, err = _acquire_single_instance_lock()
    if not ok:
        if IS_PYTHONW and IS_WINDOWS:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, err, "Minecraft Server Manager", 0x10)
            except Exception:
                pass
        else:
            print(err)
        sys.exit(1)

    if "-nogui" in sys.argv:
        _debug("MAIN", "starting console mode")
        run_console_mode()
    else:
        _debug("MAIN", "starting GUI mode")
        missing = _check_gui_requirements()
        while missing:
            if not _show_missing_deps_and_offer_install(missing):
                sys.exit(1)
            missing = _check_gui_requirements()
        try:
            run_gui_mode()
        except ImportError as e:
            if "PySide6" in str(e) or "PySide" in str(e):
                print("GUI libraries not found (PySide6 required). Run: pip install PySide6")
                if not IS_PYTHONW:
                    print("Falling back to console mode...")
                    run_console_mode()
                else:
                    sys.exit(1)
            else:
                raise
        except Exception as e:
            _debug("GUI", f"Exception: {e}\n{traceback.format_exc()}")
            if not IS_PYTHONW:
                traceback.print_exc()
                input("GUI Start Failed! Press Enter to exit...")
            else:
                sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _debug("CRASH", f"Unhandled: {e}\n{traceback.format_exc()}")
        if not IS_PYTHONW:
            traceback.print_exc()
            input("Critical Crash! Press Enter to exit...")
        sys.exit(1)
