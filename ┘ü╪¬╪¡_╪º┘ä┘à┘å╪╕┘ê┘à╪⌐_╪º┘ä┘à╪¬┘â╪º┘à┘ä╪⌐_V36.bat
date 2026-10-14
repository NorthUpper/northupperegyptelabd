@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  start "NorthUpper V36 Local Server" cmd /k "cd /d ""%~dp0"" && py -m http.server 8000"
  timeout /t 2 /nobreak >nul
  start "" http://127.0.0.1:8000/management-dashboard.html
  exit /b
)
where python >nul 2>nul
if %errorlevel%==0 (
  start "NorthUpper V36 Local Server" cmd /k "cd /d ""%~dp0"" && python -m http.server 8000"
  timeout /t 2 /nobreak >nul
  start "" http://127.0.0.1:8000/management-dashboard.html
  exit /b
)
echo Python غير مثبت. افتحي index.html للموقع العام، أو ثبتي Python لتجربة التخزين المشترك محليًا.
pause
