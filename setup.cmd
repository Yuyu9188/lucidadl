@echo off
REM One-time: open the browser, pass Cloudflare, cache the cookie.
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m lucidadl setup
) else (
  python -m lucidadl setup
)
echo.
pause
