@echo off
setlocal

rem Prefer python3; fall back to python (common on Windows)
where python3 >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=python3
) else (
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo Error: Python is not available. Please install Python 3 and ensure it is on your PATH.
        pause
        exit /b 1
    )
    set PYTHON=python
)

%PYTHON% "%~dp0src\vscode_chat_browser\workspace_chat_browser.py"