@echo off
title LiteChain

REM Change to script directory
cd /d "%~dp0"

echo Starting LiteChain...
echo ======================================

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo Docker Desktop is not running!
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo Docker is running
echo Building and starting LiteChain...
echo.

REM Start the service
docker-compose up -d --build

REM Wait for app to be ready
echo Waiting for application to start...
timeout /t 6 /nobreak >nul

REM Open browser
start http://localhost:8501

echo.
echo LiteChain is running!
echo Dashboard: http://localhost:8501
echo.
echo To stop: Run STOP-lite.bat
echo ======================================
echo.
pause
