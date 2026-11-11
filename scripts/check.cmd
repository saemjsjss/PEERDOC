@echo off
rem Run every check, stopping at the first failure: Python tests and lint, then the web UI
rem build, tests and lint. Usage: scripts\check.cmd   (from anywhere; exit code 0 = all passed)
setlocal
for %%I in ("%~dp0..") do set "REPO=%%~fI"
cd /d "%REPO%" || exit /b 1

echo === pytest
".venv\Scripts\python.exe" -m pytest -q || exit /b 1
echo === ruff
".venv\Scripts\python.exe" -m ruff check . || exit /b 1

cd /d "%REPO%\frontend" || exit /b 1
echo === npm run build
call npm run build || exit /b 1
echo === vitest
call npx vitest run || exit /b 1
echo === oxlint
call npx oxlint || exit /b 1

echo All checks passed.
exit /b 0
