@echo off
REM ================================================================================
REM  DB Sync Tool - Server Startup Script with Email Monitoring (Windows)
REM ================================================================================
REM  This script starts the Django development server with automatic email alerts.
REM  When you press Ctrl+C, an email will be sent BEFORE the server shuts down.
REM
REM  Usage:
REM    - Double-click this file
REM    - Or run: start_server.bat [port]
REM    - Default port: 8004
REM
REM  Examples:
REM    start_server.bat        (runs on port 8004)
REM    start_server.bat 8000   (runs on port 8000)
REM ================================================================================

setlocal

REM Get port from argument or use default
set PORT=%1
if "%PORT%"=="" set PORT=8004

echo.
echo ========================================================================
echo   DB Sync Tool - Server with Email Monitoring
echo ========================================================================
echo.
echo   Server will run on: http://127.0.0.1:%PORT%/
echo   Email alerts: ENABLED
echo   Recipients: Configured at /notifications/ page
echo.
echo   Press Ctrl+C to stop (email will be sent before shutdown)
echo.
echo ========================================================================
echo.

cd /d "%~dp0dbsync_tool"
python manage.py runserver_monitored --port %PORT%

echo.
echo ========================================================================
echo   Server stopped.
echo   Check your email for shutdown notification!
echo ========================================================================
echo.
pause
endlocal
