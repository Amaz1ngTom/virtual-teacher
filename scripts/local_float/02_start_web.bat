@echo off
setlocal

rem GitHub/default mode: local FLOAT Worker shares Windows file paths.
set "VT_FLOAT_WORKER_URL=http://127.0.0.1:8011"
set "VT_FLOAT_TRANSFER_MODE=path"

call "%~dp0..\no_float\01_start_web.bat" %*

endlocal
