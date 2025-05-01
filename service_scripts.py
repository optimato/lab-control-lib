import sys
import os

def generate_service_scripts():
    python_exe = sys.executable
    user = os.getenv("USER") or os.getenv("USERNAME")
    home = os.getenv('HOME')
    service = 'lclib-daemon'
    system = sys.platform

    # Create the base path for the scripts
    base_path = os.path.join(os.path.dirname(__file__), 'scripts')
    os.makedirs(base_path, exist_ok=True)

    # Create scripts based on OS
    if system.startswith("win"):
        # Path for Windows scripts
        win_service_path = os.path.join(base_path, 'lclib_service.py')
        win_install_path = os.path.join(base_path, 'windows_install_daemon.ps1')
        win_remove_path = os.path.join(base_path, 'windows_remove_daemon.ps1')          

        # Generate PowerShell scripts
        open(win_service_path, 'w').write(win_service_template.format(service=service,
                                                                      python_exe=python_exe))
        open(win_install_path, 'w').write(win_install_template.format(service=service,
                                                                      python_exe=python_exe,
                                                                      win_service_path=win_service_path))
        open(win_remove_path, 'w').write(win_remove_template.format(service=service,
                                                                      python_exe=python_exe,
                                                                      win_service_path=win_service_path))
        print(f"Windows daemon installation scripts have been generated")
        print(f"in {base_path}")
        print(f"using interpreter: {python_exe} for user: {user}")

    elif system.startswith("linux"):
        # Path for Linux scripts
        linux_install_path = os.path.join(base_path, 'linux_install_daemon.sh')
        linux_remove_path = os.path.join(base_path, 'linux_remove_daemon.sh')

        # Generate Linux scripts
        open(linux_install_path, 'w').write(linux_install_template.format(service=service,
                                                                          user=user,
                                                                          home=home,
                                                                          python_exe=python_exe))
        open(linux_remove_path, 'w').write(linux_remove_template.format(service=service))

        print(f"Linux daemon installation scripts have been generated")
        print(f"in {base_path}")
        print(f"using interpreter: {python_exe} for user: {user}")
    else:
        print(f"Unsupported OS: {system}. Only Windows and Linux are supported.")
        return

win_service_template = r'''
# This script was generated automatically.
"""
Install the lclib daemon as a Windows service.
"""
import win32serviceutil
import win32service
import win32event
import servicemanager
import subprocess
import os
import sys
import signal

class LclibDaemonService(win32serviceutil.ServiceFramework):
    _svc_name_ = "{service}"
    _svc_display_name_ = "Lab-control-lib Daemon Service"
    _svc_description_ = "Lab-control-lib daemon for process management."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.process = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        servicemanager.LogInfoMsg("Stopping {service}...")

        if self.process:
            self.process.terminate()
            self.process.wait()

        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("Starting {service}...")
        self.process = subprocess.Popen([r"{python_exe}", "-m", "lclib", "--daemon"])
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)


if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(LclibDaemonService)                                                
'''

win_install_template = r"""
# This script was generated automatically.
# It installs the lclib daemon as a Windows service.

try {{
    $Nssm = (Get-Command nssm -ErrorAction Stop).Source
}} catch {{
    Write-Error "nssm.exe not found in PATH. Please download it from and place it in your PATH."
    exit 1
}}

Write-Host "Installing the service..."
& $Nssm install {service} "{python_exe}" "lclib -d"
& $Nssm set {service} DisplayName "Lab-control-lib Daemon Service"

# Set the service to start automatically at boot
Write-Host "Setting service to start at boot..."
& $Nssm set {service} Start SERVICE_AUTO_START

# Configure the service to auto-restart on failure
Write-Host "Configuring service failure recovery..."
& $Nssm set {service} AppExit Default Restart

# Start the service
Write-Host "Starting the service..."
& $Nssm start {service}

Write-Host "Service '{service}' installed and running with auto-start and auto-recovery."
"""

win_remove_template = r"""
# This script was generated automatically.
# It removes the Windows service for the lclib daemon.

try {{
    $Nssm = (Get-Command nssm -ErrorAction Stop).Source
}} catch {{
    Write-Error "nssm.exe not found in PATH. Please download it from https://nssm.cc and place it in your PATH."
    exit 1
}}

Write-Host "Stopping the service if it's running..."
& $Nssm stop {service}

Write-Host "Removing the service..."
& $Nssm remove {service} confirm

Write-Host "Service '{service}' removed successfully."
"""

linux_install_template = r"""
#!/bin/bash
# This script was generated automatically. 
# It installs the lclib daemon as a systemd service.

SERVICE_FILE="/etc/systemd/system/{service}.service"

# ----------------------------
# CREATE SYSTEMD SERVICE FILE
# ----------------------------

echo "Creating systemd service file at $SERVICE_FILE..."

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Lab-control-lib daemon service
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={home}
ExecStart={python_exe} -m lclib --daemon
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ----------------------------
# ENABLE AND START SERVICE
# ----------------------------

echo "Reloading systemd daemon..."
sudo systemctl daemon-reexec
sudo systemctl daemon-reload

echo "Enabling and starting {service}..."
sudo systemctl enable "{service}"
sudo systemctl start "{service}"

echo "Service '{service}' installed and running."
"""

linux_remove_template = r"""
#!/bin/bash

SERVICE_FILE="/etc/systemd/system/{service}.service"

echo "Stopping and disabling {service}..."
sudo systemctl stop "{service}"
sudo systemctl disable "{service}"

if [ -f "$SERVICE_FILE" ]; then
    echo "Removing service file..."
    sudo rm "$SERVICE_FILE"
fi

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Service '{service}' removed."
"""

