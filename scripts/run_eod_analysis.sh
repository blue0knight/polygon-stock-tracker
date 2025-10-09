#!/bin/bash
#
# Run End-of-Day Analysis
# Automatically analyzes today's scanner log and generates reports
# Run this at 4:05 PM ET daily (after market close)
#

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

# Change to project directory
cd "$PROJECT_DIR"

# Activate virtual environment
source .venv/bin/activate

# Get today's date
TODAY=$(date +%Y-%m-%d)

echo "==================================="
echo "End-of-Day Analysis - $TODAY"
echo "==================================="
echo ""

# Run the EOD analysis script
python3 scripts/analyze_eod.py --date "$TODAY"

echo ""
echo "==================================="
echo "Analysis complete!"
echo "==================================="
