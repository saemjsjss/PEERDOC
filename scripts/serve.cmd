@echo off
rem Start the HKLV API (inside WSL, where the OCR models run). Then open http://127.0.0.1:8010/docs
rem Stop it with Ctrl+C.
for %%I in ("%~dp0..") do set "REPO=%%~fI"
set "DRIVE=%REPO:~0,1%"
set "REST=%REPO:~2%"
set "REST=%REST:\=/%"
for /f %%D in ('powershell -NoProfile -Command "'%DRIVE%'.ToLower()"') do set "DRIVE=%%D"
wsl -d Ubuntu --exec bash "/mnt/%DRIVE%%REST%/scripts/wsl/serve.sh"
exit /b %ERRORLEVEL%
