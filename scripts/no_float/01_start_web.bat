@echo off
setlocal
set "WEB_PORT=%~1"
if not defined WEB_PORT set "WEB_PORT=8000"
call "%~dp0..\launch.bat" web --port %WEB_PORT%
exit /b %ERRORLEVEL%
