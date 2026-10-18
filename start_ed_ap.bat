@echo off
setlocal
REM EDAPGui Startup Script
REM Creates a Python venv (prefers 3.11, then 3.10, 3.9, then any) on first start and runs EDAPGui.
cd /d "%~dp0"

REM Setup is complete when the marker file exists (a previous aborted setup is redone)
if exist "venv\.setup_complete" goto run

set "PYTHON_CMD="
py -3.11 --version >nul 2>&1 && set "PYTHON_CMD=py -3.11" && goto found
py -3.10 --version >nul 2>&1 && set "PYTHON_CMD=py -3.10" && goto found
py -3.9 --version >nul 2>&1 && set "PYTHON_CMD=py -3.9" && goto found
py --version >nul 2>&1 && set "PYTHON_CMD=py" && goto found
python --version >nul 2>&1 && set "PYTHON_CMD=python" && goto found

echo Error: No Python installation found. Please install Python 3.11:
echo     winget install -e --id Python.Python.3.11
pause
exit /b 1

:found
echo Using: %PYTHON_CMD%
%PYTHON_CMD% --version

if not exist "venv\Scripts\python.exe" (
    echo Creating Python virtual environment, please wait...
    %PYTHON_CMD% -m venv venv
)
if not exist "venv\Scripts\python.exe" (
    echo Error: Failed to create virtual environment
    pause
    exit /b 1
)

echo Installing requirements, this can take several minutes...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Error: Failed to install requirements. See the messages above.
    echo Tip: EDAP needs Python 3.11 ^(winget install -e --id Python.Python.3.11^),
    echo      then delete the 'venv' folder and run this file again.
    pause
    exit /b 1
)
echo done> "venv\.setup_complete"
echo Virtual environment setup complete!

:run
echo Starting EDAPGui...
venv\Scripts\python.exe EDAPGui.py
if errorlevel 1 (
    echo.
    echo EDAPGui exited with an error. See the messages above.
    pause
)
endlocal
