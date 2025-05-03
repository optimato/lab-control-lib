import sys
import os
import subprocess
from pathlib import Path
import textwrap

# Function to generate installation and removal scripts for the daemon
def generate_service_scripts():
    python_exe = sys.executable
    user = os.getenv("USER") or os.getenv("USERNAME")
    home = os.getenv("HOME") or str(Path.home())
    service = 'lclib-daemon'
    system = sys.platform

    base_path = os.path.join(os.path.dirname(__file__), 'scripts')
    os.makedirs(base_path, exist_ok=True)

    if system.startswith("win"):

        # Windows-specific paths
        user_task_ps1_path = os.path.join(base_path, 'lclib_daemon_user_task.ps1')
        win_install_path = os.path.join(base_path, 'windows_install_daemon.ps1')
        win_remove_path = os.path.join(base_path, 'windows_remove_daemon.ps1')

        # Check if the user is running in a conda environment
        use_conda = False
        conda_env = os.getenv("CONDA_DEFAULT_ENV")
        conda_prefix = os.getenv("CONDA_PREFIX")
        if conda_env and conda_prefix:
            activate_bat = os.path.join(conda_prefix, "Scripts", "activate.bat")
            use_conda = os.path.exists(activate_bat)

        if use_conda:
            activate_cmd = f'cmd /c """{activate_bat} {conda_env} && exit"""'
        else:
            activate_cmd = "REM No conda environment detected"

        # Define log path
        log_path = Path.home() / "lclib_daemon.log"
        log_path_str = str(log_path).replace("\\", "/")

        # Generate the PowerShell script
        ps_script = textwrap.dedent(f"""\
            # Auto-generated script to run lclib daemon in a loop
            $ErrorActionPreference = 'Continue'
            {activate_cmd}

            while ($true) {{
                Write-Host "Starting lclib daemon..."
                try {{
                    & python -m lclib -d *>> "{log_path_str}"
                }} catch {{
                    Write-Host "Daemon crashed: $($_.Exception.Message)"
                }}
                Write-Host "Restarting in 5 seconds..."
                Start-Sleep -Seconds 5
            }}
        """)

        # Generate install and remove scripts
        win_install_content = textwrap.dedent(f"""\
            # This script installs the lclib-daemon as a Scheduled Task
            $taskName = "{service}"
            $scriptPath = "{user_task_ps1_path}"

            schtasks /Create /SC ONLOGON /TN $taskName /TR "powershell.exe -ExecutionPolicy Bypass -File `"$scriptPath`"" /RL LIMITED /F
            Write-Host "Scheduled Task '$taskName' installed."
            """)
        win_remove_content = textwrap.dedent(f"""\
            # This script removes the lclib-daemon Scheduled Task
            $taskName = "{service}"

            schtasks /Delete /TN $taskName /F
            Write-Host "Scheduled Task '$taskName' removed."
            """)
        Path(user_task_ps1_path).write_text(ps_script, encoding="utf-8")
        Path(win_install_path).write_text(win_install_content, encoding="utf-8")
        Path(win_remove_path).write_text(win_remove_content, encoding="utf-8")

        print(f"Windows daemon task installation scripts written to {base_path}")

    elif system.startswith("linux"):
        # Linux-specific paths
        linux_install_path = os.path.join(base_path, 'linux_install_daemon.sh')
        linux_remove_path = os.path.join(base_path, 'linux_remove_daemon.sh')

        # Generate install and remove scripts
        Path(linux_install_path).write_text(linux_install_template.format(
            service=service,
            user=user,
            home=home,
            python_exe=python_exe
        ), encoding="utf-8")
        Path(linux_remove_path).write_text(linux_remove_template.format(
            service=service
        ), encoding="utf-8")

        print(f"Linux daemon installation scripts written to {base_path}")

    else:
        print(f"Unsupported OS: {system}. Only Windows and Linux are supported.")

if __name__ == "__main__":
    generate_service_scripts()


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

