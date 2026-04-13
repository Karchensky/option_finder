@echo off
:: Keeps the Streamlit dashboard running. Restarts automatically on crash.
:: Register with Task Scheduler to start on login:
::   schtasks /create /tn "OptionFinderDashboard" /tr "D:\Scripts\option_finder\scripts\run_dashboard.bat" /sc onlogon /rl highest

cd /d D:\Scripts\option_finder

:loop
echo [%date% %time%] Starting Streamlit dashboard...
.venv\Scripts\streamlit.exe run src\dashboard\app.py --server.port 8501 --server.headless true
echo [%date% %time%] Streamlit exited (code %errorlevel%). Restarting in 5s...
timeout /t 5 /nobreak >nul
goto loop
