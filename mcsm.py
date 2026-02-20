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
import hashlib
import requests

__version__ = "3.0.1"

SERVER_JAR = "minecraft_server.jar"
MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
IS_WINDOWS = platform.system() == "Windows"
LOG_FILE = "mcsm.log"
CONFIG_FILE = "mcsm.conf"
BACKUP_DIR = "world_backups"
WORLD_DIR = "world"
VERSION_FILE = 'version_info.txt'
SERVER_TYPE_FILE = 'server_type.txt'

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
    mem = str(config.get("server_memory", "2G"))
    if not re.match(r"(?i)^\d+[GM]$", mem):
        config["server_memory"] = "2G"
    else:
        config["server_memory"] = mem.upper()

    try:
        float(config.get("restart_interval", 12))
    except ValueError:
        config["restart_interval"] = 12.0

    return config

def load_config():
    default_config = {
        "last_server_version": "0.0.0",
        "dark_mode": True,
        "enable_logging": True,
        "check_updates": True,
        "auto_start": False,
        "enable_backups": True,
        "enable_discord": False,
        "discord_webhook": "",
        "discord_token": "",
        "discord_channel_id": 0,
        "enable_auto_restart": True,
        "enable_schedule": False,
        "restart_interval": 12,
        "server_memory": "2G",
        "max_backups": 3,
        "update_to_snapshot": False
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                loaded = json.load(f)
                default_config.update(loaded)
        except Exception: pass
    
    return validate_config(default_config)

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception: pass

class MinecraftUpdaterCore:
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
                print(f'Discord Bot logged in as {self.user}')
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
        async def start_server(ctx):
            if self.server_process:
                await ctx.send("Server is already running.")
            else:
                await ctx.send("🚀 Starting server...")
                self.start_server_sequence()

        @self.discord_bot.command(name="stop")
        async def stop_server(ctx):
            if self.server_process:
                await ctx.send("🛑 Stopping server...")
                self.stop_server()
            else:
                await ctx.send("Server is already stopped.")
        
        @self.discord_bot.command(name="restart")
        async def restart_server(ctx):
            await ctx.send("🔄 Restarting server...")
            self.stop_server()
            threading.Timer(5.0, self.start_server_sequence).start()

        def run_bot():
            try:
                self.discord_bot.run(token)
            except Exception as e:
                print(f"Discord Bot Error: {e}")

        threading.Thread(target=run_bot, daemon=True).start()

    def get_server_type(self):
        if os.path.exists(SERVER_TYPE_FILE):
            try:
                with open(SERVER_TYPE_FILE, "r") as f:
                    return f.read().strip()
            except: pass
        return "Vanilla"

    def is_installed(self):
        return os.path.exists(SERVER_JAR) or os.path.exists("server.properties") or os.path.exists("eula.txt") or os.path.exists(SERVER_TYPE_FILE)

    def download_file(self, url, filename):
        self.log(f'Downloading {filename} from {url}...')
        try:
            headers = {'User-Agent': 'MinecraftServerUpdater/3.0'}
            response = requests.get(url, headers=headers, stream=True, timeout=10)
            response.raise_for_status()
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            self.log('Downloaded successfully.')
            return True
        except Exception as e:
            self.log(f"Failed to download {filename}: {e}")
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
        try:
            response = requests.get(MANIFEST_URL, timeout=10)
            response.raise_for_status()
            data = response.json()
            minecraft_ver = data['latest']['snapshot'] if self.config.get("update_to_snapshot") else data['latest']['release']
            for version in data['versions']:
                if version['id'] == minecraft_ver:
                    return minecraft_ver, version['url']
        except Exception as e:
            self.log(f"Failed to retrieve version manifest: {e}")
        return None, None

    def update_server(self, is_initial=False):
        server_type = self.get_server_type()
        if server_type in ["Forge", "NeoForge"] and not is_initial:
            self.log(f"Detected {server_type} Server. Skipping Vanilla auto-update.")
            return True

        if server_type == "Vanilla":
            target_ver, json_url = self.get_remote_version_info()
            if not target_ver or not json_url:
                self.log("Could not retrieve version info.")
                return False

            try:
                jar_data = requests.get(json_url, timeout=10).json()
                remote_sha = jar_data['downloads']['server']['sha1']
                download_url = jar_data['downloads']['server']['url']
            except Exception as e:
                self.log(f"Failed to get jar info: {e}")
                return False

            local_sha = self.get_local_sha1(SERVER_JAR)
            
            if local_sha != remote_sha or is_initial:
                if not is_initial:
                    self.log(f"Update available -> {target_ver}")
                    self.stop_existing_server_process()
                else:
                    self.log(f"Installing Vanilla Version -> {target_ver}")

                if self.download_file(download_url, SERVER_JAR):
                    try:
                        with open(VERSION_FILE, "w") as f: f.write(target_ver)
                    except: pass
                    self.config["last_server_version"] = target_ver
                    save_config(self.config)
                    return True
                else:
                    self.log("Update download failed.")
                    return False
            else:
                self.log("Server is up to date.")
                return True
        return True

    def run_installer_wizard_console(self):
        self.log("=== Minecraft Server Installer ===")
        # Automatic Snapshot prompt
        auto_snap = input("No server detected. Do you want to automatically download the newest Vanilla Snapshot? (y/n): ").strip().lower()
        if auto_snap == 'y':
            self.config["update_to_snapshot"] = True
            save_config(self.config)
            try:
                with open(SERVER_TYPE_FILE, "w") as f: f.write("Vanilla")
            except: pass
            
            self.log("Installing latest Vanilla Snapshot...")
            if self.update_server(is_initial=True):
                 self.log("Accepting EULA...")
                 with open("eula.txt", "w") as f: f.write("eula=true\n")
                 return True
            return False

        print("\nSelect Server Installer Type:\n1) Vanilla\n2) Forge\n3) NeoForge")
        choice = input("Choice (1-3): ").strip()
        server_type = "Vanilla"
        if choice == '2': server_type = "Forge"
        elif choice == '3': server_type = "NeoForge"
        
        try:
            with open(SERVER_TYPE_FILE, "w") as f: f.write(server_type)
        except: pass

        if server_type == "Vanilla":
            self.config["update_to_snapshot"] = False
            save_config(self.config)

            if self.update_server(is_initial=True):
                 self.log("Accepting EULA...")
                 with open("eula.txt", "w") as f: f.write("eula=true\n")
                 return True
            return False
        else:
            installer_url = input(f"Please paste the full direct download URL for the {server_type} Installer (ends in .jar): ").strip()
            installer_filename = "installer.jar"
            if self.download_file(installer_url, installer_filename):
                self.log(f"Running {server_type} Installer...")
                subprocess.run(['java', '-jar', installer_filename, '--installServer'])
                self.log("Accepting EULA...")
                with open("eula.txt", "w") as f: f.write("eula=true\n")
                self.log("Installer finished. Note: Modded servers may need different startup jars.")
                return True
            return False


    def stop_existing_server_process(self):
        if IS_WINDOWS:
            try:
                os.system(f'wmic process where "commandline like \'%%{SERVER_JAR}%%\'" call terminate >nul 2>&1')
            except: pass
        else:
             try:
                os.system(f"pkill -f {SERVER_JAR}")
             except: pass

    def send_command(self, command):
        if self.server_process and self.server_process.poll() is None:
            try:
                self.log(f"> {command}")
                msg = (command + "\n").encode('utf-8')
                self.server_process.stdin.write(msg)
                self.server_process.stdin.flush()
            except Exception as e:
                self.log(f"Failed to send command: {e}")
        else:
             self.log("Server is not running.")


    def backup_world(self):
        if not self.config.get("enable_backups", True): return
        if not os.path.exists(WORLD_DIR): return

        self.log(f"Creating world backup from {WORLD_DIR}...")
        if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_name = os.path.join(BACKUP_DIR, f"world_backup_{timestamp}")
        
        try:
            shutil.make_archive(backup_name, 'zip', WORLD_DIR)
            self.log(f"Backup created: {backup_name}.zip")
            
            max_b = int(self.config.get("max_backups", 3))
            backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith("world_backup_") and f.endswith(".zip")])
            if len(backups) > max_b:
                for old in backups[:-max_b]:
                    try: os.remove(os.path.join(BACKUP_DIR, old))
                    except: pass
        except Exception as e:
            self.log(f"Backup failed: {e}")

    def send_discord_webhook(self, message):
        if not self.config.get("enable_discord", False): return
        url = self.config.get("discord_webhook", "").strip()
        if not url: return

        try:
            data = json.dumps({"content": message}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'MinecraftUpdater'})
            with urllib.request.urlopen(req) as r: pass
        except Exception as e:
            self.log(f"Discord Webhook Failed: {e}")

    def start_server_sequence(self):
        t = threading.Thread(target=self._start_server_thread)
        t.daemon = True
        t.start()

    def _start_server_thread(self):
        self.stop_requested = False
        
        if not self.is_installed():
            if self.input_callback:
                self.log("Server not installed. Use GUI Installer or run console mode.")
                return
            else:
                 if not self.run_installer_wizard_console(): return
                 
        if self.config.get("check_updates", True):
            self.stop_existing_server_process()
            self.update_server(is_initial=False)

        self.stop_existing_server_process()
        self.backup_world()

        self.log("Starting Server...")
        self.send_discord_webhook("🟢 Minecraft Server Starting...")

        memory = self.config.get("server_memory", "2G")
        
        env = os.environ.copy()
        
        # Use java command or custom script? We launch the JAR directly for parity
        # Modded servers might use forge-xxx.jar, let's detect the best jar or bat.
        target_executable = SERVER_JAR
        
        # Custom jar detection
        jars = [f for f in os.listdir() if f.endswith(".jar")]
        forge_jars = [j for j in jars if "forge" in j.lower() or "neoforge" in j.lower()]
        if forge_jars: target_executable = forge_jars[0]
        
        cmd = ["java", f"-Xmx{memory}", f"-Xms{memory}", "-jar", target_executable, "nogui"]

        # If a run.bat or run.sh exists (common for Forge >= 1.17), try running that instead to ensure args are passed.
        if IS_WINDOWS and os.path.exists("run.bat"):
            cmd = ["run.bat"]
        elif not IS_WINDOWS and os.path.exists("run.sh"):
            cmd = ["./run.sh"]

        self.log(f"Execute -> {' '.join(cmd)}")

        try:
            startupinfo = subprocess.STARTUPINFO() if IS_WINDOWS else None
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
            
            self.server_process = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
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
            self.log(f"Failed to start server: {e}")
            self.update_status({"state": "Stopped"})

    def _read_stream(self, stream, tag):
        try:
            for line_bytes in iter(stream.readline, b''):
                if line_bytes:
                    line = line_bytes.decode('utf-8', errors='replace').strip()
                    if line: self.log(line, tag)
        except: pass
        finally: stream.close()

    def _monitor_loop(self):
        if not self.server_process: return
        
        while self.server_process and self.server_process.poll() is None:
            if self.start_time:
                uptime = datetime.datetime.now() - self.start_time
                uptime_str = str(uptime).split('.')[0]
                self.update_status({
                    "state": "Running",
                    "pid": self.server_process.pid,
                    "uptime": uptime_str
                })
            time.sleep(1)

        rc = self.server_process.returncode
        self.log(f"Server exited with code {rc}")
        self.server_process = None
        self.update_status({"state": "Stopped"})
        self.send_discord_webhook(f"🔴 Server Stopped (Code {rc})")

        if rc != 0 and not self.stop_requested and self.config.get("enable_auto_restart", True):
             self.log("Crash detected! Restarting in 10 seconds...")
             self.send_discord_webhook("⚠️ Crash detected. Restarting in 10s...")
             time.sleep(10)
             self.start_server_sequence()

    def start_update_checker(self):
        if not self.config.get("check_updates", True): return
        if self.get_server_type() != "Vanilla": return

        interval = 1800
        self.log(f"Starting background update checker (every {interval}s).")
        
        def update_task():
            if self.stop_requested or not self.server_process: return
            self._run_background_update_check()
            if not self.stop_requested and self.server_process:
                self.update_timer = threading.Timer(interval, update_task)
                self.update_timer.daemon = True
                self.update_timer.start()

        self.update_timer = threading.Timer(interval, update_task)
        self.update_timer.daemon = True
        self.update_timer.start()

    def _run_background_update_check(self):
        try:
            target_ver, json_url = self.get_remote_version_info()
            local_version = self.config.get("last_server_version", "0.0.0")

            if target_ver and target_ver != local_version:
                 self.log(f"[Background Check] New Vanilla version found ({target_ver}). Restarting to update...")
                 self.send_discord_webhook(f"🚀 New update found ({target_ver})! Restarting server...")
                 self.restart_server()
            else:
                 self.log(f"[Background Check] Server is up to date.")

        except Exception as e:
            self.log(f"Background update check failed: {e}")

    def restart_server(self):
        self.log("Restarting server...")
        self.stop_server()
        def delayed_start():
            time.sleep(5) 
            self.start_server_sequence()
        threading.Thread(target=delayed_start, daemon=True).start()

    def stop_server(self):
        self.stop_requested = True
        if self.restart_timer: self.restart_timer.cancel()
        if self.update_timer: self.update_timer.cancel()

        if self.server_process:
            self.log("Stopping server...")
            try:
                self.server_process.stdin.write(b"stop\n")
                self.server_process.stdin.flush()
            except:
                if self.server_process: self.server_process.kill()
    
    def _schedule_restart(self):
        hours = float(self.config.get("restart_interval", 12))
        seconds = hours * 3600
        self.log(f"Scheduled restart in {hours} hours.")
        def restart_task():
            self.log("Executing scheduled restart...")
            self.send_discord_webhook("⏰ Executing scheduled restart...")
            self.stop_server()
            time.sleep(10)
            self.start_server_sequence()

        self.restart_timer = threading.Timer(seconds, restart_task)
        self.restart_timer.start()

def run_console_mode():
    def console_logger(message, tag=None):
        timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        if not console: print(f"{timestamp} {message}")
        with open(LOG_FILE, "a") as f: f.write(f"{timestamp} {message}\n")
    
    config = load_config()
    core = MinecraftUpdaterCore(console_logger, input_callback=input, config=config)
    
    print("--- Console Mode ---")
    core.start_server_sequence()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        core.stop_server()

def run_gui_mode():
    import tkinter as tk
    from tkinter import scrolledtext, messagebox, ttk, simpledialog

    class MinecraftGUI:
        def __init__(self, root):
            self.root = root
            self.root.title(f"Minecraft Server Manager v{__version__}")
            self.root.geometry("1000x800")
            self.config = load_config()
            self.is_dark = self.config.get("dark_mode", True)
            
            self.var_logging = tk.BooleanVar(value=self.config.get("enable_logging", True))
            self.var_check_upd = tk.BooleanVar(value=self.config.get("check_updates", True))
            self.var_snapshot = tk.BooleanVar(value=self.config.get("update_to_snapshot", False))
            self.var_autostart = tk.BooleanVar(value=self.config.get("auto_start", False))
            self.var_backup = tk.BooleanVar(value=self.config.get("enable_backups", True))
            self.var_discord = tk.BooleanVar(value=self.config.get("enable_discord", False))
            self.var_restart = tk.BooleanVar(value=self.config.get("enable_auto_restart", True))
            self.var_schedule = tk.BooleanVar(value=self.config.get("enable_schedule", False))
            self.var_discord_url = tk.StringVar(value=self.config.get("discord_webhook", ""))
            self.var_discord_token = tk.StringVar(value=self.config.get("discord_token", ""))
            self.var_discord_channel = tk.StringVar(value=str(self.config.get("discord_channel_id", 0)))
            self.var_schedule_time = tk.StringVar(value=str(self.config.get("restart_interval", 12)))
            self.var_memory = tk.StringVar(value=self.config.get("server_memory", "2G"))
            self.var_max_backups = tk.StringVar(value=str(self.config.get("max_backups", 3)))
            
            self.var_memory.trace_add("write", self.on_config_change)
            self.status_var = tk.StringVar(value="Status: Stopped")
            self.uptime_var = tk.StringVar(value="Uptime: 00:00:00")

            self.log_queue = queue.Queue()
            self.core = MinecraftUpdaterCore(self.log_queue_wrapper, None, self.config, self.update_stats)

            self.setup_ui()
            self.apply_theme()
            self.update_log_loop()

            if not self.core.is_installed():
                self.show_installer()

            elif self.var_autostart.get():
                self.root.after(1000, self.start_server)

            self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        def setup_ui(self):
            header = ttk.Frame(self.root, padding="5")
            header.pack(fill=tk.X)
            title = ttk.Label(header, text=f"Minecraft Server Manager v{__version__}", font=("Segoe UI", 16, "bold"))
            title.pack(side=tk.LEFT)
            
            controls_frame = ttk.LabelFrame(self.root, text="Controls & Configuration", padding="5")
            controls_frame.pack(fill=tk.X, padx=10, pady=2)
            
            left_container = ttk.Frame(controls_frame)
            left_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            options_row = ttk.Frame(left_container)
            options_row.pack(fill=tk.X, anchor="w")

            c_col1 = ttk.Frame(options_row)
            c_col1.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))
            
            ttk.Checkbutton(c_col1, text="Enable File Logging", variable=self.var_logging, command=self.save).pack(anchor="w")
            ttk.Checkbutton(c_col1, text="Auto-Start Server", variable=self.var_autostart, command=self.save).pack(anchor="w")
            ttk.Checkbutton(c_col1, text="Auto-Restart on Crash", variable=self.var_restart, command=self.save).pack(anchor="w")

            mem_frame = ttk.Frame(c_col1)
            mem_frame.pack(anchor="w", pady=2)
            ttk.Label(mem_frame, text="Server RAM:").pack(side=tk.LEFT)
            ttk.Entry(mem_frame, textvariable=self.var_memory, width=6).pack(side=tk.LEFT, padx=5)
            self.lbl_reboot = ttk.Label(mem_frame, text="⚠ Reboot Required", foreground="orange")
            
            c_col2 = ttk.Frame(options_row)
            c_col2.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))
            
            ttk.Checkbutton(c_col2, text="Check for updates", variable=self.var_check_upd, command=self.save).pack(anchor="w")
            ttk.Checkbutton(c_col2, text="Update to Snapshots", variable=self.var_snapshot, command=self.save).pack(anchor="w")
            
            bkp_frame = ttk.Frame(c_col2)
            bkp_frame.pack(anchor="w")
            ttk.Checkbutton(bkp_frame, text="Backup World", variable=self.var_backup, command=self.save).pack(side=tk.LEFT)
            ttk.Label(bkp_frame, text="Max:").pack(side=tk.LEFT, padx=(5,2))
            ttk.Entry(bkp_frame, textvariable=self.var_max_backups, width=3).pack(side=tk.LEFT)

            sch_frame = ttk.Frame(c_col2)
            sch_frame.pack(anchor="w", pady=2)
            ttk.Checkbutton(sch_frame, text="Schedule Restart (Hrs)", variable=self.var_schedule, command=self.save).pack(side=tk.LEFT)
            ttk.Entry(sch_frame, textvariable=self.var_schedule_time, width=5).pack(side=tk.LEFT, padx=5)

            c_col3_center = ttk.Frame(options_row)
            c_col3_center.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

            dsc_frame = ttk.Frame(c_col3_center, padding=5, borderwidth=1, relief="solid")
            dsc_frame.pack(anchor="w", pady=2, fill=tk.X)

            ttk.Checkbutton(dsc_frame, text="Discord Integration", variable=self.var_discord, command=self.save).pack(anchor="w", pady=(0, 5))

            def add_dsc_row(label_text, var, is_secure=False):
                row = ttk.Frame(dsc_frame)
                row.pack(fill=tk.X, pady=1)
                ttk.Label(row, text=label_text, width=10).pack(side=tk.LEFT)
                entry = ttk.Entry(row, textvariable=var, width=18, show="*" if is_secure else None)
                entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

            add_dsc_row("Webhook:", self.var_discord_url)
            add_dsc_row("Token:", self.var_discord_token, is_secure=True)
            add_dsc_row("Channel:", self.var_discord_channel)

            c_col3 = ttk.Frame(controls_frame)
            c_col3.pack(side=tk.RIGHT, fill=tk.Y)
            
            def open_dir(path):
                try:
                    p = os.path.abspath(path)
                    if not os.path.exists(p): os.makedirs(p)
                    os.startfile(p) if IS_WINDOWS else subprocess.run(["xdg-open", p])
                except Exception as e: pass

            qa_buttons_frame = ttk.Frame(c_col3)
            qa_buttons_frame.grid(row=0, column=0, sticky="n", padx=(0, 10), pady=0)
            
            action_buttons_frame = ttk.Frame(c_col3)
            action_buttons_frame.grid(row=0, column=1, sticky="n", pady=0)

            ttk.Button(qa_buttons_frame, text="Server", width=10, command=lambda: open_dir(".")).pack(fill=tk.X, pady=1)
            ttk.Button(qa_buttons_frame, text="Worlds", width=10, command=lambda: open_dir(WORLD_DIR)).pack(fill=tk.X, pady=1)
            ttk.Button(qa_buttons_frame, text="Backups", width=10, command=lambda: open_dir(BACKUP_DIR)).pack(fill=tk.X, pady=1)

            self.btn_start = ttk.Button(action_buttons_frame, text="START SERVER", command=self.start_server, width=20)
            self.btn_start.pack(pady=1)
            self.btn_stop = ttk.Button(action_buttons_frame, text="STOP SERVER", command=self.stop_server, state=tk.DISABLED, width=20)
            self.btn_stop.pack(pady=1)

            self.lbl_status = ttk.Label(c_col3, textvariable=self.status_var, font=("Consolas", 9))
            self.lbl_status.grid(row=1, column=0, pady=2)
            
            self.lbl_uptime = ttk.Label(c_col3, textvariable=self.uptime_var, font=("Consolas", 9))
            self.lbl_uptime.grid(row=1, column=1, pady=2)
            
            self.console = scrolledtext.ScrolledText(self.root, font=("Consolas", -10), state=tk.DISABLED)
            self.console.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 0))
            self.setup_tags()

            input_frame = ttk.Frame(self.root)
            input_frame.pack(fill=tk.X, padx=10, pady=(2, 5))
            
            ttk.Label(input_frame, text="Command:").pack(side=tk.LEFT, padx=(0, 5))
            self.input_var = tk.StringVar()
            self.entry_cmd = ttk.Entry(input_frame, textvariable=self.input_var)
            self.entry_cmd.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.entry_cmd.bind("<Return>", lambda e: self.send_command_ui())
            
            footer = ttk.Frame(self.root, padding="10")
            footer.pack(fill=tk.X)
            
            ttk.Button(footer, text="Toggle Theme", command=self.toggle_theme).pack(side=tk.LEFT)

        def show_installer(self):
            inst_win = tk.Toplevel(self.root)
            inst_win.title("Setup Wizard")
            inst_win.geometry("400x250")
            inst_win.transient(self.root)
            inst_win.grab_set()

            ttk.Label(inst_win, text="Welcome to Minecraft Server Manager!", font=("Arial", 12, "bold")).pack(pady=10)
            ttk.Label(inst_win, text="No server detected. Please choose a flavor to install:").pack(pady=5)

            def install_auto(snapshot=False):
                try: 
                    with open(SERVER_TYPE_FILE, "w") as f: f.write("Vanilla")
                except: pass
                self.config["update_to_snapshot"] = snapshot
                self.save()
                
                self.core.log(f"Installing automatic Vanilla {'Snapshot' if snapshot else 'Release'}...")
                if self.core.update_server(is_initial=True):
                     with open("eula.txt", "w") as f: f.write("eula=true\n")
                     self.core.log("Installation Complete. You can start the server.")
                inst_win.destroy()

            def install_manual(flav):
                try: 
                    with open(SERVER_TYPE_FILE, "w") as f: f.write(flav)
                except: pass

                url = simpledialog.askstring("Installer URL", f"Paste the full direct download URL for the {flav} installer (.jar) from their official website:")
                if url:
                     if self.core.download_file(url, "installer.jar"):
                          self.core.log(f"Running {flav} Installer...")
                          subprocess.Popen(['java', '-jar', 'installer.jar', '--installServer']).wait()
                          with open("eula.txt", "w") as f: f.write("eula=true\n")
                          self.core.log("Modded installation complete.")
                inst_win.destroy()

            # Automatic Prompt immediately if Vanilla is desired
            if messagebox.askyesno("No Server Found", "No server jar was found.\n\nWould you like to automatically download the newest Vanilla Snapshot?\n(Selecting 'No' allows you to choose Vanilla Release, Forge, or NeoForge.)"):
                inst_win.destroy()
                install_auto(snapshot=True)
                return

            ttk.Button(inst_win, text="Vanilla Release (Automatic)", command=lambda: install_auto(snapshot=False)).pack(fill=tk.X, padx=50, pady=5)
            ttk.Button(inst_win, text="Forge", command=lambda: install_manual("Forge")).pack(fill=tk.X, padx=50, pady=5)
            ttk.Button(inst_win, text="NeoForge", command=lambda: install_manual("NeoForge")).pack(fill=tk.X, padx=50, pady=5)

        def send_command_ui(self):
            cmd = self.input_var.get().strip()
            if cmd:
                self.core.send_command(cmd)
                self.input_var.set("")
                self.entry_cmd.focus()

        def on_config_change(self, *args):
            self.save()
            if self.core.server_process:
                 self.lbl_reboot.pack(side=tk.LEFT, padx=5)
            else:
                 self.lbl_reboot.pack_forget()

        def start_server(self):
            self.lbl_reboot.pack_forget()
            self.save()
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.core.start_server_sequence()

        def stop_server(self):
            self.core.stop_server()
            self.btn_stop.config(state=tk.DISABLED)

        def save(self):
            self.config.update({
                "enable_logging": self.var_logging.get(),
                "check_updates": self.var_check_upd.get(),
                "update_to_snapshot": self.var_snapshot.get(),
                "auto_start": self.var_autostart.get(),
                "enable_backups": self.var_backup.get(),
                "enable_discord": self.var_discord.get(),
                "enable_auto_restart": self.var_restart.get(),
                "enable_schedule": self.var_schedule.get(),
                "discord_webhook": self.var_discord_url.get(),
                "discord_token": self.var_discord_token.get(),
                "discord_channel_id": int(self.var_discord_channel.get()) if self.var_discord_channel.get().isdigit() else 0,
                "restart_interval": self.var_schedule_time.get(),
                "server_memory": self.var_memory.get(),
                "max_backups": int(self.var_max_backups.get()) if self.var_max_backups.get().isdigit() else 3,
            })
            self.core.config = self.config
            save_config(self.config)

        def update_stats(self, status):
            state = status.get("state", "Unknown")
            if state == "Stopped":
                 self.root.after(0, lambda: self.btn_start.config(state=tk.NORMAL))
                 self.root.after(0, lambda: self.btn_stop.config(state=tk.DISABLED))
                 self.root.after(0, lambda: self.status_var.set("Status: Stopped"))
                 self.root.after(0, lambda: self.uptime_var.set("Uptime: 00:00:00"))
            elif state == "Running":
                 uptime = status.get("uptime", "00:00:00")
                 self.root.after(0, lambda: self.status_var.set("Status: Running"))
                 self.root.after(0, lambda: self.uptime_var.set(f"Uptime: {uptime}"))

        def log_queue_wrapper(self, msg, tag=None):
            timestamp = datetime.datetime.now().strftime("[%H:%M:%S]")
            self.log_queue.put((f"{timestamp} {msg}\n", tag))
            if self.var_logging.get():
                clean_msg = re.sub(r'\x1b\[[0-9;]*m', '', f"{timestamp} {msg}\n")
                with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(clean_msg)

        def update_log_loop(self):
            while not self.log_queue.empty():
                msg, tag = self.log_queue.get()
                self.console.config(state=tk.NORMAL)
                self.insert_colored(msg, tag)
                if float(self.console.index('end-1c')) > 1000:
                    self.console.delete('1.0', '50.0')
                self.console.see(tk.END)
                self.console.config(state=tk.DISABLED)
            self.root.after(100, self.update_log_loop)

        def insert_colored(self, text, tag):
             parts = re.split(r'(\x1b\[[0-9;]*m)', text)
             current_tag = tag if tag == "stderr" else None
             for part in parts:
                 if part.startswith('\x1b['):
                     code = part.strip()[2:-1]
                     if code == "0": current_tag = None
                     elif code in ["31","91"]: current_tag = "red"
                     elif code in ["32","92"]: current_tag = "green"
                     elif code in ["33","93"]: current_tag = "yellow"
                     elif code in ["36","96"]: current_tag = "cyan"
                 else:
                     if part: self.console.insert(tk.END, part, (current_tag,) if current_tag else ())

        def setup_tags(self):
            self.console.tag_config("stderr", foreground="#ff5555")
            self.console.tag_config("red", foreground="#ff5555")
            self.console.tag_config("green", foreground="#55ff55" if self.is_dark else "#00aa00")
            self.console.tag_config("yellow", foreground="#ffff55" if self.is_dark else "#aaaa00")
            self.console.tag_config("cyan", foreground="#55ffff" if self.is_dark else "#00aaaa")

        def apply_theme(self):
            bg, fg = ("#1e1e1e", "#d4d4d4") if self.is_dark else ("#f0f0f0", "#000000")
            txt_bg, txt_fg = bg, fg
            
            style = ttk.Style()
            style.theme_use('clam')
            style.configure(".", background=bg, foreground=fg)
            style.configure("TLabel", background=bg, foreground=fg)
            style.configure("TFrame", background=bg)
            style.configure("TLabelFrame", background=bg, foreground=fg)
            style.configure("TButton", background="#3c3c3c" if self.is_dark else "#e0e0e0", foreground=fg, borderwidth=1)
            style.map("TButton", background=[("active", "#0078d7")], foreground=[("active", "white")])
            style.configure("TCheckbutton", background=bg, foreground=fg)
            style.configure("TEntry", foreground="black", fieldbackground="white")
            
            self.root.configure(bg=bg)
            self.console.config(bg=txt_bg, fg=txt_fg, insertbackground=fg)

        def toggle_theme(self):
            self.is_dark = not self.is_dark
            self.config["dark_mode"] = self.is_dark
            self.apply_theme()
            self.save()

        def on_close(self):
            if self.core.server_process:
                if messagebox.askokcancel("Quit", "Server is running. Do you want to stop it and quit?"):
                    self.core.stop_server()
                    self.root.destroy()
                    os._exit(0)
            else:
                self.root.destroy()
                os._exit(0)

    root = tk.Tk()
    app = MinecraftGUI(root)
    root.mainloop()

def print_help():
    print(f"Minecraft Server Manager v{__version__}")
    print("=" * 60)
    print("Usage: python mcsm.py [options]")
    print("\nCommand Line Options:")
    print("  -nogui             : Run in console-only mode (headless). Useful for servers.")
    print("  -help, --help      : Show this help message.")
    print("\nDescription:")
    print("  Manages the Minecraft Dedicated Server life-cycle.")
    print("=" * 60)
    sys.exit(0)

def main():
    if "-help" in sys.argv or "--help" in sys.argv:
        print_help()

    # Move to script directory
    if getattr(sys, 'frozen', False):
        app_path = os.path.dirname(sys.executable)
    else:
        app_path = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_path)

    if "-nogui" in sys.argv:
        run_console_mode()
    else:
        try:
            run_gui_mode()
        except ImportError:
            print("GUI libraries not found. Falling back to console mode...")
            run_console_mode()
        except Exception:
             traceback.print_exc()
             input("GUI Start Failed! Press Enter to exit...")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        input("Critical Crash! Press Enter to exit...")
