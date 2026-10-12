@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  start "NorthUpper Local Server" cmd /k "cd /d ""%~dp0"" && py -m http.server 8000"
  timeout /t 2 /nobreak >nul
  start "" http://127.0.0.1:8000/index.html
  exit /b
)
where python >nul 2>nul
if %errorlevel%==0 (
  start "NorthUpper Local Server" cmd /k "cd /d ""%~dp0"" && python -m http.server 8000"
  timeout /t 2 /nobreak >nul
  start "" http://127.0.0.1:8000/index.html
  exit /b
)
echo Python is not installed. For shared demo data between pages, install Python or use the hosted test environment.
echo You can still open index.html for a visual-only review, but local file storage may not be shared across pages.
pause
