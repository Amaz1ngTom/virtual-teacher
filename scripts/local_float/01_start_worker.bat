@echo off
setlocal
set "WORKER_PORT=%~1"
if not defined WORKER_PORT set "WORKER_PORT=8011"
call "%~dp0..\launch.bat" worker --port %WORKER_PORT%
exit /b %ERRORLEVEL%
