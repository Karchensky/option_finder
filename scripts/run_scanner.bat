@echo off
:: Keeps the market scan loop running. Restarts automatically on crash.
:: Register with Task Scheduler to start on login:
::   schtasks /create /tn "OptionFinderScanner" /tr "D:\Scripts\option_finder\scripts\run_scanner.bat" /sc onlogon /rl highest

cd /d D:\Scripts\option_finder

:loop
echo [%date% %time%] Starting scan loop...
.venv\Scripts\python.exe -m src.main
echo [%date% %time%] Scanner exited (code %errorlevel%). Restarting in 5s...
timeout /t 5 /nobreak >nul
goto loop
