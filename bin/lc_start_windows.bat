@echo off

REM Stand-alone starting script for remote drivers hosted on a Windows machine
REM Environment preparation should be done during login.

REM Check if the first argument (lab_name) is provided
IF "%~1"=="" (
    echo Usage: %~0 lab_name driver_name
    exit /b 1
)

REM Check if the second argument (driver_name) is provided
IF "%~2"=="" (
    echo Usage: %~0 lab_name driver_name
    exit /b 1
)

REM Run the Python module with the provided arguments
powershell -Command "Invoke-WmiMethod -Path Win32_Process -Name Create -ArgumentList 'python -m lclib %1 start %2'"
