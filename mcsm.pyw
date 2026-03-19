import os
import sys
import subprocess
import time
import datetime
import shutil
import urllib.request
import zipfile
import threading
import queue
import platform
import re
import signal
import json
import traceback
import webbrowser
import contextlib
import psutil
import hashlib

# Windows flag for hiding child console windows.
if platform.system() == "Windows":
    CREATE_NO_WINDOW = 0x08000000
    # Also optionally use STARTUPINFO to hide things deeper if needed.
else:
    CREATE_NO_WINDOW = 0

__version__ = "4.1.2"

JAVA_VERSION_REQ = 21  # Minecraft 1.17+ requires 16/17, 1.20.5+ requires 21
SERVER_JAR = "minecraft_server.jar"
MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
IS_WINDOWS = platform.system() == "Windows"
BACKUP_DIR = "world_backups"
WORLD_DIR = "world"
MODS_DIR = "mods"

# Always resolve paths relative to the script's own directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "mcsm.log")
CONFIG_FILE = os.path.join(BASE_DIR, "mcsm.conf")

try:
    from rich.console import Console
    console = Console()
except ImportError:
    console = None

try:
    import discord
    from discord.ext import commands
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False

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
        except: return ""

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
        if not self.config.get("manager_auto_update", True):
             return False

        def parse_ver(v): return [int(x) for x in v.split('.')]

        ts = int(time.time())
        # Placeholder URL - adjust to your actual repo
        MANAGER_URL = f"https://raw.githubusercontent.com/UnDadFeated/Minecraft_Server_Manager/master/mcsm.pyw?t={ts}"
        try:
            req = urllib.request.Request(MANAGER_URL, headers={'User-Agent': 'MinecraftManagerUpdater'})
            with urllib.request.urlopen(req, timeout=15) as response:
                remote_content = response.read().decode('utf-8')
            match = re.search(r'__version__\s*=\s*"([^"]+)"', remote_content)
            if match:
                remote_ver = match.group(1)
                if parse_ver(remote_ver) > parse_ver(__version__):
                    self.log(f"New manager version found ({remote_ver}). Downloading...")
                    new_file = "mcsm.pyw.new"
                    with open(new_file, "w", encoding='utf-8') as f:
                        f.write(remote_content)
                    return True
            return False
        except: return False

    def run_update_installer(self):
        args_repr = repr(sys.argv)
        installer_code = f'''
import os
import time
import sys
import subprocess

pid = {os.getpid()}
def is_pid_running(p):
    try:
        if os.name == 'nt':
            output = subprocess.check_output(f'tasklist /FI "PID eq {{p}}"', shell=True).decode()
            return str(p) in output
        else:
            os.kill(p, 0)
            return True
    except: return False

try:
    start_wait = time.time()
    while is_pid_running(pid) and time.time() - start_wait < 30:
        time.sleep(1)
            
    old_file = "mcsm.pyw"
    new_file = "mcsm.pyw.new"
    if os.path.exists(new_file):
        if os.path.exists(old_file): os.remove(old_file)
        os.rename(new_file, old_file)
    
    subprocess.Popen([sys.executable] + {args_repr})
except Exception as e:
    print(f"Update failed: {{e}}")
'''
        with open("updater_installer.py", "w") as f:
            f.write(installer_code)
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
        if self.has_mods() and self.config.get("modded_do_not_update", True):
            self.log("Mods detected and 'Do Not Update (Modded)' is active. Skipping server update.")
            return

        self.log("Checking for Minecraft updates...")
        target_ver, json_url = self.get_remote_version_info()
        if not target_ver: return

        local_ver = self.config.get("last_server_version", "0.0.0")
        if target_ver == local_ver:
            self.log(f"Minecraft {target_ver} is up to date.")
            return

        self.log(f"New Minecraft version available: {target_ver}")
        try:
            req = urllib.request.Request(json_url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                ver_data = json.loads(resp.read().decode())
            
            download_url = ver_data['downloads']['server']['url']
            remote_sha = ver_data['downloads']['server']['sha1']
            
            if self.get_local_sha1(SERVER_JAR) == remote_sha:
                self.log("Local JAR matches remote SHA1. Skipping download.")
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
        except Exception as e:
            self.log(f"Update failed: {e}")

    def stop_existing_server_process(self):
        self.log("Checking for running Minecraft server...")
        if IS_WINDOWS:
            try:
                cmd = f'powershell -NoProfile -Command "Get-WmiObject Win32_Process | Where-Object {{ $_.CommandLine -like \'*java*\' -and $_.CommandLine -like \'*{SERVER_JAR}*\' }} | Select-Object -ExpandProperty ProcessId"'
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True, creationflags=CREATE_NO_WINDOW)
                for pid in result.stdout.splitlines():
                    if pid.strip().isdigit():
                        subprocess.run(f"taskkill /PID {pid} /F", shell=True, creationflags=CREATE_NO_WINDOW)
            except: pass
        else:
             try:
                cmd = ["pgrep", "-f", SERVER_JAR]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    for pid in result.stdout.strip().splitlines():
                        subprocess.run(["kill", pid])
             except: pass

    def send_command(self, command):
        if self.server_process and self.server_process.poll() is None:
            try:
                self.log(f"> {command}")
                self.server_process.stdin.write((command + "\n").encode())
                self.server_process.stdin.flush()
            except: pass

    def backup_world(self):
        if not self.config.get("enable_backups", True): return
        if not os.path.exists(WORLD_DIR): return
        self.log("Creating world backup...")
        if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = os.path.join(BACKUP_DIR, f"world_{ts}")
        try:
            shutil.make_archive(name, 'zip', WORLD_DIR)
            max_b = int(self.config.get("max_backups", 3))
            backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")])
            if len(backups) > max_b:
                for old in backups[:-max_b]:
                    os.remove(os.path.join(BACKUP_DIR, old))
        except Exception as e: self.log(f"Backup error: {e}")

    def send_discord_webhook(self, message):
        if not self.config.get("enable_discord", False): return
        url = self.config.get("discord_webhook", "").strip()
        token = self.config.get("discord_token", "").strip()
        channel = self.config.get("discord_channel_id", 0)

        if url:
            try:
                data = json.dumps({"content": message}).encode()
                req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'MCSM-Bot'})
                with urllib.request.urlopen(req, timeout=10): pass
            except: pass
        elif token and channel:
            try:
                api_url = f"https://discord.com/api/v10/channels/{channel}/messages"
                data = json.dumps({"content": message}).encode()
                req = urllib.request.Request(api_url, data=data, headers={
                    'Authorization': f'Bot {token}',
                    'Content-Type': 'application/json',
                    'User-Agent': 'MCSM-Bot'
                })
                with urllib.request.urlopen(req, timeout=10): pass
            except: pass

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
        if not self.config.get("check_updates", True): return
        def update_task():
            if self.stop_requested or not self.server_process: return
            self.update_server()
            if not self.stop_requested and self.server_process:
                self.update_timer = threading.Timer(1800, update_task)
                self.update_timer.daemon = True
                self.update_timer.start()
        self.update_timer = threading.Timer(1800, update_task)
        self.update_timer.daemon = True
        self.update_timer.start()

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
    import tkinter as tk
    from tkinter import scrolledtext, messagebox, ttk, filedialog

    class MinecraftGUI:
        def __init__(self, root):
            self.root = root
            self.root.title(f"Minecraft Server Manager v{__version__}")
            self.root.geometry("1080x800")
            self.config = load_config()
            self.is_dark = self.config.get("dark_mode", True)
            
            self.var_logging = tk.BooleanVar(value=self.config.get("enable_logging", True))
            self.var_check_upd = tk.BooleanVar(value=self.config.get("check_updates", True))
            self.var_snapshot = tk.BooleanVar(value=self.config.get("update_to_snapshot", False))
            self.var_mod_no_upd = tk.BooleanVar(value=self.config.get("modded_do_not_update", True))
            self.var_autostart = tk.BooleanVar(value=self.config.get("auto_start", False))
            self.var_backup = tk.BooleanVar(value=self.config.get("enable_backups", True))
            self.var_discord = tk.BooleanVar(value=self.config.get("enable_discord", False))
            self.var_restart = tk.BooleanVar(value=self.config.get("enable_auto_restart", True))
            self.var_schedule = tk.BooleanVar(value=self.config.get("enable_schedule", False))
            self.var_discord_url = tk.StringVar(value=self.config.get("discord_webhook", ""))
            self.var_discord_token = tk.StringVar(value=self.config.get("discord_token", ""))
            self.var_discord_chan = tk.StringVar(value=str(self.config.get("discord_channel_id", 0)))
            self.var_sch_time = tk.StringVar(value=str(self.config.get("restart_interval", 12)))
            self.var_memory = tk.StringVar(value=self.config.get("server_memory", "4G"))
            self.var_max_bkp = tk.StringVar(value=str(self.config.get("max_backups", 3)))
            self.var_start_win = tk.BooleanVar(value=self.config.get("start_with_windows", False))
            self.var_mgr_upd = tk.BooleanVar(value=self.config.get("manager_auto_update", True))
            
            self.status_var = tk.StringVar(value="Status: Stopped")
            self.uptime_var = tk.StringVar(value="Uptime: 00:00:00")
            self.cpu_var = tk.StringVar(value="CPU: 0%")
            self.ram_var = tk.StringVar(value="RAM: 0%")

            self.log_queue = queue.Queue()
            self.core = MinecraftUpdaterCore(self.log_q, None, self.config, self.upd_stats)

            self.setup_ui()
            self.apply_theme()
            self.log_loop()
            if self.var_autostart.get(): self.root.after(1000, self.start_server)
            self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        def setup_ui(self):
            header = ttk.Frame(self.root, padding="5")
            header.pack(fill=tk.X)
            ttk.Label(header, text=f"Minecraft Server Manager v{__version__}", font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
            
            cfg_frame = ttk.LabelFrame(self.root, text="Controls & Configuration", padding="5")
            cfg_frame.pack(fill=tk.X, padx=10, pady=2)
            
            l_cont = ttk.Frame(cfg_frame)
            l_cont.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            rows = ttk.Frame(l_cont)
            rows.pack(fill=tk.X)

            c1 = ttk.Frame(rows); c1.pack(side=tk.LEFT, padx=5)
            ttk.Checkbutton(c1, text="Enable Logging", variable=self.var_logging, command=self.save).pack(anchor="w")
            ttk.Checkbutton(c1, text="Auto-Start", variable=self.var_autostart, command=self.save).pack(anchor="w")
            ttk.Checkbutton(c1, text="Auto-Restart", variable=self.var_restart, command=self.save).pack(anchor="w")
            
            m_f = ttk.Frame(c1); m_f.pack(anchor="w")
            ttk.Label(m_f, text="RAM:").pack(side=tk.LEFT)
            ttk.Entry(m_f, textvariable=self.var_memory, width=6).pack(side=tk.LEFT, padx=5)

            c2 = ttk.Frame(rows); c2.pack(side=tk.LEFT, padx=5)
            ttk.Checkbutton(c2, text="Check Updates", variable=self.var_check_upd, command=self.save).pack(anchor="w")
            ttk.Checkbutton(c2, text="Latest Snapshots", variable=self.var_snapshot, command=self.save).pack(anchor="w")
            ttk.Checkbutton(c2, text="Do Not Update if Modded", variable=self.var_mod_no_upd, command=self.save).pack(anchor="w")

            c3 = ttk.Frame(rows); c3.pack(side=tk.LEFT, padx=5)
            b_f = ttk.Frame(c3); b_f.pack(anchor="w")
            ttk.Checkbutton(b_f, text="Backups", variable=self.var_backup, command=self.save).pack(side=tk.LEFT)
            ttk.Entry(b_f, textvariable=self.var_max_bkp, width=3).pack(side=tk.LEFT, padx=5)
            
            s_f = ttk.Frame(c3); s_f.pack(anchor="w")
            ttk.Checkbutton(s_f, text="Restart (Hrs)", variable=self.var_schedule, command=self.save).pack(side=tk.LEFT)
            ttk.Entry(s_f, textvariable=self.var_sch_time, width=4).pack(side=tk.LEFT, padx=5)

            dsc = ttk.LabelFrame(rows, text="Discord"); dsc.pack(side=tk.LEFT, padx=5, fill=tk.Y)
            ttk.Checkbutton(dsc, text="Enable", variable=self.var_discord, command=self.save).pack(anchor="w")
            
            def add_row(lbl, var, secure=False):
                f = ttk.Frame(dsc); f.pack(fill=tk.X, pady=1)
                ttk.Label(f, text=lbl, width=8).pack(side=tk.LEFT)
                ttk.Entry(f, textvariable=var, width=12, show="*" if secure else None).pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            add_row("Webhook:", self.var_discord_url)
            add_row("Token:", self.var_discord_token, True)
            add_row("Channel:", self.var_discord_chan)

            r_cont = ttk.Frame(cfg_frame); r_cont.pack(side=tk.RIGHT, padx=5)
            
            # QA Buttons (Folder shortcuts)
            qa_f = ttk.Frame(r_cont); qa_f.pack(side=tk.LEFT, padx=5)
            def open_dir(p):
                try:
                    ap = os.path.abspath(p)
                    if not os.path.exists(ap): os.makedirs(ap)
                    if IS_WINDOWS: os.startfile(ap)
                    else: subprocess.run(["xdg-open", ap])
                except: pass
            
            ttk.Button(qa_f, text="Server", width=8, command=lambda: open_dir(".")).pack(pady=1)
            ttk.Button(qa_f, text="Worlds", width=8, command=lambda: open_dir(WORLD_DIR)).pack(pady=1)
            ttk.Button(qa_f, text="Backups", width=8, command=lambda: open_dir(BACKUP_DIR)).pack(pady=1)

            # Action Buttons
            act_f = ttk.Frame(r_cont); act_f.pack(side=tk.LEFT)
            self.btn_start = ttk.Button(act_f, text="START SERVER", command=self.start_server, width=18, style="StartPulse.TButton")
            self.btn_start.pack(pady=1)
            self.btn_stop = ttk.Button(act_f, text="STOP SERVER", command=self.stop_server, width=18, state=tk.DISABLED, style="StopAlert.TButton")
            self.btn_stop.pack(pady=1)
            
            ttk.Label(act_f, text=f"Version: {self.config.get('last_server_version', 'Unknown')}", font=("Consolas", 8), foreground="gray").pack()
            
            st_f = ttk.Frame(act_f); st_f.pack(pady=2)
            ttk.Label(st_f, textvariable=self.status_var, font=("Consolas", 8, "bold")).pack(side=tk.LEFT, padx=5)
            ttk.Label(st_f, textvariable=self.uptime_var, font=("Consolas", 8)).pack(side=tk.LEFT, padx=5)
            
            stat_row = ttk.Frame(act_f); stat_row.pack()
            ttk.Label(stat_row, textvariable=self.cpu_var, font=("Consolas", 8), foreground="gray").pack(side=tk.LEFT, padx=5)
            ttk.Label(stat_row, textvariable=self.ram_var, font=("Consolas", 8), foreground="gray").pack(side=tk.LEFT, padx=5)

            self.console = scrolledtext.ScrolledText(self.root, font=("Consolas", 9), state=tk.DISABLED, bg="#101010", fg="#d4d4d4", borderwidth=0, highlightthickness=0)
            self.console.pack(fill=tk.BOTH, expand=True, padx=10, pady=2)

            cmd_f = ttk.Frame(self.root); cmd_f.pack(fill=tk.X, padx=10, pady=5)
            self.cmd_var = tk.StringVar()
            ttk.Entry(cmd_f, textvariable=self.cmd_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Button(cmd_f, text="Send", command=self.send_cmd).pack(side=tk.LEFT)

            footer = ttk.Frame(self.root); footer.pack(fill=tk.X, padx=10, pady=5)
            ttk.Button(footer, text="Toggle Theme", command=self.toggle_theme).pack(side=tk.LEFT)
            ttk.Checkbutton(footer, text="Start with Windows", variable=self.var_start_win, command=self.save_win).pack(side=tk.LEFT, padx=10)
            ttk.Checkbutton(footer, text="Auto-Update Manager", variable=self.var_mgr_upd, command=self.save).pack(side=tk.LEFT, padx=10)
            ttk.Button(footer, text="☕ Support the Development", command=lambda: webbrowser.open("https://www.paypal.me/jscheema/5")).pack(side=tk.RIGHT, padx=10)

        def save(self):
            self.config.update({
                "enable_logging": self.var_logging.get(), "check_updates": self.var_check_upd.get(),
                "update_to_snapshot": self.var_snapshot.get(), "modded_do_not_update": self.var_mod_no_upd.get(),
                "auto_start": self.var_autostart.get(), "enable_backups": self.var_backup.get(),
                "enable_discord": self.var_discord.get(), "enable_auto_restart": self.var_restart.get(),
                "enable_schedule": self.var_schedule.get(), "discord_webhook": self.var_discord_url.get(),
                "restart_interval": self.var_sch_time.get(), "server_memory": self.var_memory.get(),
                "max_backups": int(self.var_max_bkp.get()) if self.var_max_bkp.get().isdigit() else 3,
                "start_with_windows": self.var_start_win.get(), "manager_auto_update": self.var_mgr_upd.get(),
                "dark_mode": self.is_dark,
                "discord_token": self.var_discord_token.get(),
                "discord_channel_id": int(self.var_discord_chan.get()) if self.var_discord_chan.get().isdigit() else 0
            })
            save_config(self.config)

        def save_win(self):
            self.save()
            if not IS_WINDOWS: return
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
                if self.var_start_win.get():
                    path = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}" --startup-delay'
                    winreg.SetValueEx(key, "MinecraftServerManager", 0, winreg.REG_SZ, path)
                else:
                    try: winreg.DeleteValue(key, "MinecraftServerManager")
                    except: pass
                winreg.CloseKey(key)
            except Exception as e:
                import tkinter as tk
                from tkinter import messagebox
                messagebox.showerror("Error", f"Failed to set registry key: {e}")

        def start_server(self):
            self.save(); self.btn_start.config(state=tk.DISABLED); self.btn_stop.config(state=tk.NORMAL)
            self.core.start_server_sequence()

        def stop_server(self): self.core.stop_server()

        def send_cmd(self):
            c = self.cmd_var.get().strip()
            if c: self.core.send_command(c); self.cmd_var.set("")

        def log_q(self, m, t=None):
            self.log_queue.put((m, t))
            if self.var_logging.get():
                try:
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {m}\n")
                except OSError: pass

        def log_loop(self):
            while not self.log_queue.empty():
                m, t = self.log_queue.get(); self.console.config(state=tk.NORMAL)
                self.console.insert(tk.END, f"{m}\n"); self.console.see(tk.END)
                self.console.config(state=tk.DISABLED)
            self.root.after(100, self.log_loop)

        def upd_stats(self, s):
            self.root.after(0, lambda: self.status_var.set(f"Status: {s.get('state', 'Stopped')}"))
            self.root.after(0, lambda: self.uptime_var.set(f"Uptime: {s.get('uptime', '00:00:00')}"))
            
            try:
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
                self.root.after(0, lambda: self.cpu_var.set(f"CPU: {cpu}%"))
                self.root.after(0, lambda: self.ram_var.set(f"RAM: {ram}%"))
            except: pass

            if s.get("state") == "Stopped":
                self.root.after(0, lambda: self.btn_start.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.btn_stop.config(state=tk.DISABLED))

        def apply_theme(self):
            theme = "dark" if self.is_dark else "light"
            # Antigravity Palette
            bg = "#181818" if self.is_dark else "#fdfdfd"
            fg = "#e0e0e0" if self.is_dark else "#202020"
            silver = "#707070" if self.is_dark else "#dcdcdc" # 1px silver lines feel
            accent = "#3498db" if self.is_dark else "#2980b9"
            
            style = ttk.Style()
            try:
                import sv_ttk
                sv_ttk.set_theme(theme)
            except Exception:
                try:
                    style.theme_use("clam")
                except Exception:
                    pass
            
            # Custom Antigravity Polish (Grey theme + 1px silver lines)
            style.configure(".", background=bg, foreground=fg, font=("Segoe UI", 8))
            style.configure("TFrame", background=bg)
            # 1px Silver line effect on LabelFrames
            style.configure("TLabelframe", background=bg, foreground=fg, bordercolor=silver, borderwidth=1)
            style.configure("TLabelframe.Label", background=bg, foreground=accent, font=("Segoe UI", 8, "bold"))
            style.configure("TButton", padding=2, font=("Segoe UI", 8))
            style.configure("TCheckbutton", background=bg, foreground=fg, font=("Segoe UI", 8))
            style.configure("TEntry", fieldbackground=bg if self.is_dark else "#ffffff", foreground=fg, bordercolor=silver, font=("Segoe UI", 8))
            
            # Colored Action Buttons
            style.configure("StartPulse.TButton", foreground="#107C10" if not self.is_dark else "#23D18B", font=("Segoe UI", 8, "bold"))
            style.configure("StopAlert.TButton", foreground="#D13438" if not self.is_dark else "#F14C4C", font=("Segoe UI", 8, "bold"))
            
            self.root.configure(bg=bg)
            self.console.config(bg="#0c0c0c" if self.is_dark else "#fcfcfc", 
                                fg="#d4d4d4" if self.is_dark else "#1a1a1a",
                                insertbackground=fg,
                                highlightbackground=silver, 
                                highlightthickness=1)
            
            style.map("TButton", background=[("active", accent)], foreground=[("active", "#ffffff")])
            
            # Explicitly recurse and update built-in tk widgets if any
            def _apply_to_child(w):
                try: 
                    if isinstance(w, tk.Label): w.configure(bg=bg, fg=fg)
                    elif isinstance(w, (tk.Frame, tk.Canvas)): w.configure(bg=bg)
                    elif isinstance(w, tk.Button): w.configure(bg=bg, fg=fg)
                except: pass
                for child in w.winfo_children(): _apply_to_child(child)
            
            _apply_to_child(self.root)

        def toggle_theme(self):
            self.is_dark = not self.is_dark; self.apply_theme(); self.save()

        def on_close(self):
            if self.core.server_process:
                if messagebox.askokcancel("Quit", "Stop server and quit?"):
                    self.core.stop_server(); self.root.destroy(); sys.exit(0)
            else: self.root.destroy(); sys.exit(0)

    root = tk.Tk(); app = MinecraftGUI(root); root.mainloop()

def main():
    os.chdir(BASE_DIR)
    if "--startup-delay" in sys.argv:
        time.sleep(30)
        sys.argv.remove("--startup-delay")
    if "-nogui" in sys.argv: run_console_mode()
    else: run_gui_mode()

if __name__ == "__main__":
    try: main()
    except Exception: traceback.print_exc(); input("Crash! Press Enter...")
