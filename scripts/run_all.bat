@echo off
:: Launches both the scanner and dashboard in separate windows.
:: Register with Task Scheduler to start on login:
::   schtasks /create /tn "OptionFinder" /tr "D:\Scripts\option_finder\scripts\run_all.bat" /sc onlogon /rl highest

echo Starting Option Finder...
start "OptionFinder Scanner" cmd /c "D:\Scripts\option_finder\scripts\run_scanner.bat"
start "OptionFinder Dashboard" cmd /c "D:\Scripts\option_finder\scripts\run_dashboard.bat"
echo Both processes launched. You can close this window.
