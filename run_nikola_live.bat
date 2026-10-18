@echo off
REM === Nikola Live Trading — Windows One-Click Launcher ===
REM Run from the nikola/ directory. LIVE mode = REAL orders on Kraken Pro.
REM Ensure kraken.env is configured BEFORE running.
cd /d "%~dp0"
python -u nikola.py --live --cycles 9999 > live_nikola.log 2>&1
pause
