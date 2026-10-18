#!/bin/bash
# Nikola — Live Trading Mode (REAL MONEY on Kraken BTNL margin)
# REQUIRES: config/kraken.env with valid Kraken API keys (READ + TRADE + MARGIN)
# Usage:     ./run_nikola_live.sh
# WARNING:  This places REAL orders. Paper test for at least 2 weeks first.

cd "$(dirname "$0")"
python -u nikola.py --live --cycles 9999 > nikola_live.log 2>&1
