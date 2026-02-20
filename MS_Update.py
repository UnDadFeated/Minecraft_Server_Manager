import os
import time
import shutil
import hashlib
import subprocess
import logging
import requests
import platform
import sys
import re
from datetime import datetime

"""
Minecraft Server Updater & Installer
------------------------------------
A utility to check for Minecraft server updates, backup data, 
and auto-update the server jar file. Also supports clean installations.

Author: UnDadFeated
Version: 2.1
"""

# CONFIGURATION
UPDATE_TO_SNAPSHOT = False
MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
BACKUP_DIR = 'world_backups'
JARBACKUP_DIR = 'previous_jars'
LOG_FILENAME = 'Update_Log.log'
SERVER_JAR = 'minecraft_server.jar'
START_BATCH_FILE = 'Manual_Run.bat'
VERSION_FILE = 'version_info.txt'

# Setup Logging
logging.basicConfig(
    filename=LOG_FILENAME, 
    level=logging.INFO, 
    format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def get_java_version():
    """Checks the installed Java version."""
    try:
        # java -version prints to stderr
        result = subprocess.run(['java', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output = result.stderr
        
        # Parse version string (e.g., "java version \"1.8.0_202\"" or "openjdk 17.0.1")
        match = re.search(r'version "(\d+)(?:\.(\d+))?(?:\.(\d+))?.*"', output)
        if not match:
             match = re.search(r'version "(\d+)"', output) # simple version like "21"
        
        if match:
            major = int(match.group(1))
            if major == 1: # Handle 1.8 as 8
                return int(match.group(2))
            return major
        return 0
    except FileNotFoundError:
        return None
    except Exception as e:
        logging.error(f"Error checking Java version: {e}")
        return None

def get_required_java_micr_version(mc_version_str):
    """Determines required Java version based on Minecraft version."""
    try:
        # Basic heuristic parsing
        parts = list(map(int, mc_version_str.split('.')))
        major, minor = parts[0], parts[1]
        
        if major == 1:
            if minor >= 20:
                if len(parts) > 2 and parts[2] >= 5: # 1.20.5+ -> Java 21
                     return 21
                if minor > 20: # 1.21+ -> Java 21
                    return 21
                return 17 # 1.18 to 1.20.4
            elif minor >= 18:
                return 17
            elif minor == 17:
                return 16
            else:
                return 8
        return 8 # Fallback
    except:
        return 17 # Safer modern default if parse fails

def get_remote_version_info(update_to_snapshot):
    """Retrieves the latest version info from Mojang."""
    try:
        response = requests.get(MANIFEST_URL)
        response.raise_for_status()
        data = response.json()
        
        if update_to_snapshot:
            minecraft_ver = data['latest']['snapshot']
        else:
            minecraft_ver = data['latest']['release']
            
        for version in data['versions']:
            if version['id'] == minecraft_ver:
                return minecraft_ver, version['url']
        return None, None
    except Exception as e:
        logging.error(f"Failed to retrieve version manifest: {e}")
        return None, None

def get_local_sha1(filename):
    """Calculates SHA1 of a local file efficiently."""
    if not os.path.exists(filename):
        return ""
    
    sha = hashlib.sha1()
    try:
        with open(filename, 'rb') as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()
    except Exception as e:
        logging.error(f"Error calculating SHA1 for {filename}: {e}")
        return ""

def get_current_version_name(local_sha):
    """Retrieves the cached version name, falling back to truncated SHA."""
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, 'r') as f:
                return f.read().strip()
        except:
            pass
    
    return f"Unknown (SHA: {local_sha[:7]})" if local_sha else "None"

def save_current_version_name(version_name):
    """Saves the current version name to file."""
    try:
        with open(VERSION_FILE, 'w') as f:
            f.write(str(version_name))
    except Exception as e:
        logging.error(f"Failed to save version info: {e}")

def stop_server():
    """Stops the Minecraft server gracefully."""
    logging.info('Stopping server...')
    print('Stopping server...')
    
    # OS Specific Kill
    try:
        if platform.system() == "Windows":
            os.system(f'wmic process where "commandline like \'%{SERVER_JAR}%\'" call terminate >nul 2>&1')
        else:
            # Linux implementation
            os.system(f"pkill -f {SERVER_JAR}")
    except Exception as e:
        logging.error(f"Failed to stop server: {e}")
        
    print('Waiting for server to stop...')
    # Active wait for the jar to not be locked or process to end
    max_wait = 30
    for i in range(max_wait):
        try:
            # Try to rename the jar to itself as a simple lock check, if the system allows
            if os.path.exists(SERVER_JAR):
                os.rename(SERVER_JAR, SERVER_JAR)
            break # Not locked
        except OSError:
            time.sleep(1)
    else:
        logging.warning("Server took too long to shutdown or file is still locked.")

def backup_server_jar(current_sha):
    """Backs up the current server jar."""
    if not os.path.exists(JARBACKUP_DIR):
        os.makedirs(JARBACKUP_DIR)

    backup_path = os.path.join(JARBACKUP_DIR, f"minecraft_server_sha={current_sha}.jar")
    try:
        shutil.copy(SERVER_JAR, backup_path)
        logging.info(f"Backed up {SERVER_JAR} to {backup_path}")
    except Exception as e:
        logging.error(f"Failed to backup server jar: {e}")

def download_file(url, filename):
    """Generic download helper."""
    logging.info(f'Downloading {filename} from {url}...')
    print(f'Downloading {filename}...')
    try:
        headers = {'User-Agent': 'MinecraftServerUpdater/2.0'}
        response = requests.get(url, headers=headers, stream=True, timeout=10)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logging.info('Downloaded successfully.')
        print('Downloaded successfully.')
        return True
    except Exception as e:
        logging.error(f"Failed to download {filename}: {e}")
        print(f"Failed to download {filename}: {e}")
        return False

def backup_world(current_sha):
    """Backs up the world directory."""
    if not os.path.exists('world'):
        logging.warning("No 'world' folder found to backup.")
        return

    logging.info('Backing up world...')
    print('Backing up world...')
    
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    timestamp = datetime.now().isoformat().replace(':', '-')
    backup_name = f"world_backup_{timestamp}_sha={current_sha}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    
    try:
        shutil.copytree("world", backup_path)
        logging.info('Backed up world.')
        print('Backed up world.')
    except Exception as e:
        logging.error(f"Failed to backup world: {e}")
        print(f"Failed to backup world: {e}")

def start_server():
    """Starts the Minecraft server."""
    logging.info('Starting server...')
    print('Starting server...')
    logging.info('=' * 78)
    
    if os.path.exists(START_BATCH_FILE):
        if platform.system() == "Windows":
             os.system(f'start "" "{START_BATCH_FILE}"')
        else:
             # Make executable just in case
             os.system(f'chmod +x {START_BATCH_FILE}')
             # Run in background or standard? User asked for update script, usually ran in screen or background
             print(f"Please run ./{START_BATCH_FILE} to start your server.")
    else:
        logging.error(f"Startup script {START_BATCH_FILE} not found!")
        print(f"Startup script {START_BATCH_FILE} not found!")


def save_server_type(server_type):
    """Saves the server type (Vanilla, Forge, NeoForge)."""
    try:
        with open("server_type.txt", "w") as f:
            f.write(server_type)
    except Exception as e:
        logging.error(f"Failed to save server type: {e}")

def get_server_type():
    """Reads the server type."""
    if os.path.exists("server_type.txt"):
        try:
            with open("server_type.txt", "r") as f:
                return f.read().strip()
        except:
            pass
    return "Vanilla" # Default to Vanilla for legacy compatibility

def install_logic():
    print("\n=== Minecraft Server Installer ===\n")
    
    # 1. OS Detection & Directory
    os_type = platform.system()
    install_dir = ""
    
    if os_type == "Windows":
        print("Detected OS: Windows")
        install_dir = input("Enter the folder path to install the server in: ").strip()
    elif os_type == "Linux":
        print("Detected OS: Linux")
        username = input("Enter your username: ").strip()
        install_dir = f"/home/{username}/MCServer/"
    else:
        print(f"Unsupported OS: {os_type}")
        sys.exit("Unsupported OS")

    # Create Directory
    if not os.path.exists(install_dir):
        try:
            os.makedirs(install_dir)
            print(f"Created directory: {install_dir}")
        except Exception as e:
            print(f"Error creating directory: {e}")
            return
    
    # Change working directory to install_dir and migrate script
    if os.path.abspath(install_dir) != os.path.abspath(os.getcwd()):
        try:
            # Copy self to the target directory if we're not running from it or it's a frozen executable
            current_script = os.path.abspath(sys.argv[0])
            dest_script = os.path.join(install_dir, os.path.basename(current_script))
            if current_script != dest_script:
                shutil.copy2(current_script, dest_script)
                print(f"Copied {os.path.basename(current_script)} to new directory.")
        except Exception as e:
            print(f"Could not copy script/executable to {install_dir}: {e}")

    os.chdir(install_dir)
    
    # 2. Server Type Selection
    print("\nSelect Server Installer Type:")
    print("1) Vanilla")
    print("2) Forge")
    print("3) NeoForge")
    choice = input("Choice (1-3): ").strip()
    
    server_type = "Vanilla"
    if choice == '2': server_type = "Forge"
    elif choice == '3': server_type = "NeoForge"
    
    # Save Type Immediately
    save_server_type(server_type)
    
    # 3. Version Selection
    mc_version = input("\nEnter Minecraft Version (e.g., 1.20.1): ").strip()
    
    # 4. Java Check
    req_java = get_required_java_micr_version(mc_version)
    current_java = get_java_version()
    
    print(f"\nChecking Java... Required: {req_java}, Found: {current_java if current_java else 'None'}")
    
    java_ok = False
    if current_java and current_java >= req_java:
        java_ok = True
    
    if not java_ok:
        print(f"WARNING: Correct Java version not found. You need Java {req_java}.")
        if os_type == "Linux":
            print(f"Install command (Ubuntu/Debian): sudo apt install openjdk-{req_java}-jre-headless")
        else:
            print(f"Please download and install Java {req_java} from Adoptium or Oracle.")
    
    print(f"\nInstalling in: {os.getcwd()}")
    
    # 5. Download & Install
    if server_type == "Vanilla":
        # Find URL
        print("Fetching Vanilla version manifest...")
        try:
            resp = requests.get(MANIFEST_URL, timeout=10)
            data = resp.json()
            ver_url = None
            for v in data['versions']:
                if v['id'] == mc_version:
                    ver_url = v['url']
                    break
            
            if not ver_url:
                print(f"Version {mc_version} not found in manifest.")
                return

            v_data = requests.get(ver_url, timeout=10).json()
            download_url = v_data['downloads']['server']['url']
            
            if download_file(download_url, SERVER_JAR):
                save_current_version_name(mc_version)
                if java_ok:
                    print("Running server to generate EULA...")
                    subprocess.run(['java', '-Xmx1024M', '-Xms1024M', '-jar', SERVER_JAR, 'nogui'], input=b'\n')
                    
                    # Fix EULA
                    if os.path.exists("eula.txt"):
                        with open("eula.txt", "r") as f: content = f.read()
                        with open("eula.txt", "w") as f: f.write(content.replace("eula=false", "eula=true"))
                        print("EULA accepted automatically.")
                        
                        # Create Batch Script
                        create_startup_script(os_type, SERVER_JAR)
                        print("Installation Complete! You can now run the server.")
                else:
                    print("\nInstallation paused. Please install Java and then run the following command manually:")
                    print(f"java -Xmx1024M -Xms1024M -jar {SERVER_JAR} nogui")

        except Exception as e:
            print(f"Error installing Vanilla: {e}")

    elif server_type in ["Forge", "NeoForge"]:
        # Forge/NeoForge require installer download
        print(f"\nFor {server_type}, exact version matching is strict.")
        installer_url = input(f"Please paste the full direct download URL for the {server_type} Installer (ends in .jar): ").strip()
        
        installer_filename = "installer.jar"
        if download_file(installer_url, installer_filename):
            if java_ok:
                print(f"Running {server_type} Installer...")
                try:
                    # Forge installer usually creates the server jar.
                    subprocess.run(['java', '-jar', installer_filename, '--installServer'], check=True)
                    
                    # Cleanup
                    print("Installer finished.")
                    
                    print("Setting up EULA...")
                    with open("eula.txt", "w") as f: f.write("eula=true\n")
                    
                    print(f"Note: {server_type} usually creates its own startup scripts (run.bat/run.sh).")
                    print("Please check the folder for the generated startup script.")
                    
                except Exception as e:
                    print(f"Installer failed: {e}")
            else:
                print(f"\nPlease install Java {req_java}, then run:")
                print(f"java -jar {installer_filename} --installServer")

def create_startup_script(os_type, jar_name):
    """Creates a default startup script."""
    if os_type == "Windows":
        with open("Manual_Run.bat", "w") as f:
            f.write(f"java -Xmx2048M -Xms1024M -jar {jar_name} nogui\npause\n")
    else:
        with open("Manual_Run.sh", "w") as f:
            f.write("#!/bin/bash\n")
            f.write(f"java -Xmx2048M -Xms1024M -jar {jar_name} nogui\n")
        os.system("chmod +x Manual_Run.sh")

def update_logic():
    # Existing Update Logic adapted
    
    # Check Server Type
    server_type = get_server_type()
    
    if server_type in ["Forge", "NeoForge"]:
        print(f"Detected {server_type} Server. Skipping auto-update to prevent data loss.")
        print("Ensuring server starts...")
        start_server()
        return

    # VANILLA UPDATE LOGIC
    target_ver, json_url = get_remote_version_info(UPDATE_TO_SNAPSHOT)
    if not target_ver or not json_url:
        print("Could not retrieve version info.")
        return

    try:
        jar_data = requests.get(json_url).json()
        remote_sha = jar_data['downloads']['server']['sha1']
        download_url = jar_data['downloads']['server']['url']
    except Exception as e:
        logging.error(f"Failed to get jar info: {e}")
        return

    local_sha = get_local_sha1(SERVER_JAR)
    
    if local_sha != remote_sha:
        current_version_name = get_current_version_name(local_sha)
        
        logging.info('Update Found.')
        print(f"Update available: {current_version_name} -> {target_ver}")
        
        stop_server()
        
        if local_sha: 
            backup_server_jar(local_sha)
        
        if download_file(download_url, SERVER_JAR):
            backup_world(local_sha)
            save_current_version_name(target_ver)
            start_server()
        else:
            print("Update failed.")
    else:
        print("Server is up to date.")
        start_server()

def main():
    # Ensure we are working from the script's directory for detection safely
    if getattr(sys, 'frozen', False):
        app_path = os.path.dirname(sys.executable)
    else:
        app_path = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_path)

    # Check if we are in an installed environment 
    # Logic: If 'server.properties' exists OR 'minecraft_server.jar' exists OR 'eula.txt' exists, we assume installed.
    # Note: Forge often doesn't use minecraft_server.jar as the main entry, but creates one.
    is_installed = os.path.exists(SERVER_JAR) or os.path.exists("server.properties") or os.path.exists("eula.txt") or os.path.exists("server_type.txt")
    
    if is_installed:
        update_logic()
    else:
        install_logic()

if __name__ == "__main__":
    main()
