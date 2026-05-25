@echo off
REM ================================================================================
REM  DB Sync Tool - Monitored Server Startup Script (Windows)
REM ================================================================================
REM  This script starts the Django development server with email monitoring.
REM  When you press Ctrl+C, an email alert will be sent BEFORE shutdown.
REM
REM  Usage: Double-click this file or run from command prompt: start_server.bat
REM ================================================================================

echo.
echo ========================================================================
echo   DB Sync Tool - Starting Monitored Server
echo ========================================================================
echo.
echo   [INFO] Email alerts enabled for server shutdown/crashes
echo   [INFO] Recipients configured in: /notifications/ page
echo   [INFO] Press Ctrl+C to stop (email will be sent before shutdown)
echo.
echo ========================================================================
echo.

cd /d "%~dp0dbsync_tool"
python manage.py runserver_monitored

echo.
echo ========================================================================
echo   Server stopped. Check your email for shutdown notification.
echo ========================================================================
echo.
pause
