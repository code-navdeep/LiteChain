@echo off

REM Change to script directory
cd /d "%~dp0"

echo Stopping LiteChain...
echo ========================================

REM Stop Docker container
docker-compose down

echo.
echo LiteChain stopped
echo Port 8501 freed
echo.
echo You can now safely close this window.
echo.
pause
