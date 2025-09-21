## [0.1.3] – 2025-09-21
### Added
- Added `schemas/watchlist_template.csv` and `schemas/missed_template.csv` with clean headers and working Excel/Sheets formulas.
  - `watchlist_template.csv`: auto-calculates `total_cost`, P/L $, and P/L %; falls back to T1 target if no exit price.
  - `missed_template.csv`: auto-calculates `total_cost`, P/L $, and P/L %; falls back to exit_target if no close price.

## [0.2.0] – 2025-09-21
### Added
- Introduced `src/scanner/scanner.py` with the initial premarket scanner loop skeleton:
  - Loads configuration from `scanner.yaml`.
  - Sets up logging to `logs/scanner.log`.
  - Runs a loop between configured `start_time` and `end_time`.
- Extended `scanner.yaml` with:
  - `output` block (paths for watchlist, missed, logs, schema).
  - `pump_prone` block (earliest_entry, time_stop).
  - `targets` block (T1, T2, stretch levels).
