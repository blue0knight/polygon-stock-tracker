## [0.2.4] – 2025-09-21
### Fixed
- `score_snapshots()` now supports Polygon’s `prev_close` / `last_price` fields and falls back to `todays_change_pct`.
- Top-5 movers now correctly scored and written into `output/watchlist.csv`.


## [0.2.3] – 2025-09-21
### Added
- `src/core/output.py`: helper to write Top-5 movers into `output/watchlist.csv` with schema headers.
- Integrated `write_watchlist()` into both scanner loop and `--once` dry-run.
- Appends targets (`t1`, `t2`, `stretch`) from `scanner.yaml`.

### Changed
- Updated `src/scanner/scanner.py` to handle snapshots as lists, convert to dict, and log + write Top-5 movers.


## [0.2.2] – 2025-09-21
### Added
- `src/core/scoring.py`: Scoring module with gap % calculation, Top-5 ranking, and logging helpers.
- `tests/test_scoring.py`: Unit tests validating gap %, ranking, and edge cases.

### Changed
- Integrated scoring into `src/scanner/scanner.py` (`--once` dry-run and loop mode now log Top-5 movers).

## [0.2.1] – 2025-09-21
### Added
- `src/adapters/polygon_adapter.py`: Polygon API adapter for snapshot fetching.
- `src/scanner/scanner.py`: added `--once` dry-run mode to fetch all tickers (~11,700) and log results.
- `scripts/test_fetch.py`: standalone script to validate Polygon connectivity.

### Changed
- Minor logging improvements in scanner for dry-run mode.

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

## [0.1.3] – 2025-09-21
### Added
- Added `schemas/watchlist_template.csv` and `schemas/missed_template.csv` with clean headers and working Excel/Sheets formulas.
  - `watchlist_template.csv`: auto-calculates `total_cost`, P/L $, and P/L %; falls back to T1 target if no exit price.
  - `missed_template.csv`: auto-calculates `total_cost`, P/L $, and P/L %; falls back to exit_target if no close price.




