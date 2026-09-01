@echo off
setlocal
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
if exist "%~dp0local.settings.bat" call "%~dp0local.settings.bat"
if not defined VT_WEB_PYTHON set "VT_WEB_PYTHON=python"
cd /d "%PROJECT_ROOT%"
"%VT_WEB_PYTHON%" -m app.launch %*
exit /b %ERRORLEVEL%
