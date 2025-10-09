#!/bin/bash
#
# Filter missed.csv for specific criteria
# Usage:
#   ./scripts/filter_missed.sh           # Show all
#   ./scripts/filter_missed.sh 15        # Show gains > 15%
#   ./scripts/filter_missed.sh 20        # Show gains > 20%
#

CSV="output/missed.csv"
MIN_GAIN=${1:-0}

echo "=========================================="
echo "MISSED OPPORTUNITIES (Gain > ${MIN_GAIN}%)"
echo "=========================================="
echo ""

# Print header
head -1 "$CSV" | awk -F',' '{printf "%-12s %-6s %8s %12s %12s\n", $1, $2, $8, $10, $11}'

echo "----------------------------------------"

# Print filtered rows
awk -F',' -v min="$MIN_GAIN" '
NR > 1 && $8 > min {
    # Extract entry and exit times from windows
    split($10, entry_parts, " ")
    split($11, exit_parts, " ")
    printf "%-12s %-6s %7s%% %12s %12s\n", $1, $2, $8, entry_parts[1], exit_parts[1]
}
' "$CSV"

echo ""
echo "Total: $(awk -F',' -v min="$MIN_GAIN" 'NR > 1 && $8 > min' "$CSV" | wc -l | tr -d ' ') picks above ${MIN_GAIN}%"
