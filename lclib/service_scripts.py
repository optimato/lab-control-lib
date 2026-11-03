"""
Generation of the scripts that install the lclib daemon as a service
(a Scheduled Task on Windows, a systemd service on Linux), used by `lc --install-daemon`.

This file is part of lab-control-lib
"""
import sys
import os
import subprocess
from pathlib import Path
import textwrap

# The scripts are written for the current user and interpreter, next to the daemon files
SCRIPTS_DIR = os.path.join(os.path.expanduser('~'), '.lclib', 'scripts')


def generate_service_scripts():
    """
    Write the install and remove scripts of the daemon for the current platform, user and
    Python interpreter. Return their paths (install_path, remove_path).
    """
    python_exe = sys.executable
    user = os.getenv("USER") or os.getenv("USERNAME")
    home = os.getenv("HOME") or str(Path.home())
    service = 'lclib-daemon'
    system = sys.platform

    base_path = SCRIPTS_DIR
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
        use_conda = (conda_env and conda_prefix)

        if use_conda:
            # Activate by prefix (unambiguous). Load conda's PowerShell hook from the conda
            # executable found now, so activation works also without `conda init powershell`
            # or a profile for this user.
            prefix_ps = conda_prefix.replace("'", "''")
            conda_exe = os.getenv("CONDA_EXE")
            if conda_exe:
                conda_exe_ps = conda_exe.replace("'", "''")
                activate_cmd = (f"(& '{conda_exe_ps}' 'shell.powershell' 'hook') | Out-String | Invoke-Expression; "
                                f"conda activate '{prefix_ps}'")
            else:
                activate_cmd = f"conda activate '{prefix_ps}'"
        else:
            activate_cmd = 'Write-Host "No conda environment detected"'

        # The interpreter running this, so the daemon does not depend on the PATH order
        python_ps = python_exe.replace("'", "''")

        # Define log path
        log_path = Path.home() / "lclib_daemon.log"
        log_path_str = str(log_path).replace("\\", "/")

        # Generate the PowerShell script
        ps_script = textwrap.dedent(f"""\
            # Auto-generated script to run lclib daemon in a loop
            $ErrorActionPreference = 'Continue'
            Start-Transcript -Path "{log_path_str}" -Append
            {activate_cmd}

            while ($true) {{
                Write-Host "Starting lclib daemon..."
                try {{
                    & '{python_ps}' -m lclib -d
                }} catch {{
                    Write-Host "Daemon crashed: $($_.Exception.Message)"
                }}
                Write-Host "Restarting in 5 seconds..."
                Start-Sleep -Seconds 5
            }}
            Stop-Transcript
        """)

        # Generate install and remove scripts
        win_install_content = textwrap.dedent(f"""\
            # This script was generated automatically
            # It installs the lclib-daemon as a Scheduled Task, started at logon.
            # Running it again replaces an existing installation.
            $taskName = "{service}"
            $scriptPath = "{user_task_ps1_path}"
            $user = "$env:USERDOMAIN\\$env:USERNAME"

            # Stop a running daemon, so that the new settings apply
            # (the drivers it started are stopped too)
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

            $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`""
            $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
            $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

            # Run indefinitely (the default limit is 3 days), also on battery power (some UPS
            # report as batteries), never start a second instance, and restart the task if it fails.
            $settings = New-ScheduledTaskSettingsSet `
                -ExecutionTimeLimit ([TimeSpan]::Zero) `
                -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries `
                -MultipleInstances IgnoreNew `
                -RestartCount 999 `
                -RestartInterval (New-TimeSpan -Minutes 1)

            Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
            Write-Host "Daemon '$taskName' installed as scheduled task."
            Write-Host "Execution time limit: $((Get-ScheduledTask -TaskName $taskName).Settings.ExecutionTimeLimit) (PT0S means no limit)"

            Start-ScheduledTask -TaskName $taskName
            Write-Host "Scheduled Task Started. Logs are at {log_path_str}"
            """)
        win_remove_content = textwrap.dedent(f"""\
            # This script was generated automatically
            # It removes the lclib-daemon Scheduled Task
            $taskName = "{service}"

            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Host "Scheduled Task '$taskName' removed."
            """)
        Path(user_task_ps1_path).write_text(ps_script, encoding="utf-8")
        Path(win_install_path).write_text(win_install_content, encoding="utf-8")
        Path(win_remove_path).write_text(win_remove_content, encoding="utf-8")

        print(f"Windows daemon task installation scripts written to {base_path}")
        return win_install_path, win_remove_path

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
        return linux_install_path, linux_remove_path

    raise RuntimeError(f"Unsupported OS: {system}. Only Windows and Linux are supported.")


def run_script(path):
    """
    Run a script generated by generate_service_scripts, and return its exit code.
    """
    if sys.platform.startswith("win"):
        cmd = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path]
    else:
        cmd = ['bash', path]
    return subprocess.call(cmd)

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

