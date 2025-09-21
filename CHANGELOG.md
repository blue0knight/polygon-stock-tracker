## [0.1.3] – 2025-09-21
### Added
- Added `schemas/watchlist_template.csv` and `schemas/missed_template.csv` with clean headers and working Excel/Sheets formulas.
  - `watchlist_template.csv`: auto-calculates `total_cost`, P/L $, and P/L %; falls back to T1 target if no exit price.
  - `missed_template.csv`: auto-calculates `total_cost`, P/L $, and P/L %; falls back to exit_target if no close price.
