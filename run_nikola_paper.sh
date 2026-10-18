#!/bin/bash
# Nikola — Paper Trading Mode
# Runs locally with simulated fills, $300 clean slate, ZERO API keys
# Usage: ./run_nikola_paper.sh

cd "$(dirname "$0")"
python -u nikola.py --paper --cycles 9999 > paper_nikola.log 2>&1
