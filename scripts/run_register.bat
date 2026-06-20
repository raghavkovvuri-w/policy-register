@echo off
echo ============================================
echo  Policy Register - Inspire Education Group
echo ============================================
echo.

echo [1/5] Fetching policies from public sources...
python scripts\fetch_policies.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: fetch_policies.py failed.
    pause
    exit /b 1
)
echo.

echo [2/5] Extracting metadata from PDFs...
python scripts\process_policies.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: process_policies.py failed.
    pause
    exit /b 1
)
echo.

echo [3/5] Building register...
python scripts\build_register.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: build_register.py failed.
    pause
    exit /b 1
)
echo.

echo [4/5] Running analysis...
python scripts\analyze_policies.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: analyze_policies.py failed.
    pause
    exit /b 1
)
echo.

echo [5/5] Generating dashboard...
python scripts\generate_dashboard.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: generate_dashboard.py failed.
    pause
    exit /b 1
)
echo.

echo ============================================
echo  COMPLETE. Open output\dashboard.html
echo ============================================
pause
