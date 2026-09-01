@echo off
setlocal

rem Optional acceleration mode: WAV/MP4 transfer through the SSH tunnel.
set "VT_FLOAT_WORKER_URL=http://127.0.0.1:18011"
set "VT_FLOAT_TRANSFER_MODE=upload"

call "%~dp0..\no_float\01_start_web.bat" %*

endlocal
