@echo off
rem Run the master pipeline from cmd or PowerShell, whatever the PowerShell execution policy.
rem   scripts\run_case.cmd "C:\dcSS\SAMPLE DOC" [--date YYYY-MM-DD]
rem Exit code: 0 PASS, 1 FLAG, 2 FAIL, 3 error.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_case.ps1" %*
exit /b %ERRORLEVEL%
