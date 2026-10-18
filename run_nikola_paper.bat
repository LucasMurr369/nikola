@echo off
REM === Nikola Paper Trading — Windows One-Click Launcher ===
REM Run from the nikola/ directory. Paper mode = SIMULATED orders, no real money.
cd /d "%~dp0"
python -u nikola.py --paper --cycles 9999 > paper_nikola.log 2>&1
pause
