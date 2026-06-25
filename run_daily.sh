#!/usr/bin/env bash
# Run this every morning. Picks up any new lead-drop files sitting in
# data/incoming/, then builds today's outreach queue. Safe to run more than
# once a day - both steps are idempotent (see README/ARCHITECTURE for why).
#
# Local cron example (runs at 7am every day):
#   0 7 * * * cd /path/to/fleek-pipeline-tool && ./run_daily.sh >> logs/daily.log 2>&1
#
# In CI, .github/workflows/daily_plan.yml runs this same script on a schedule.
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p logs output
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> logs/daily.log

python3 -m src.cli auto-ingest --folder data/incoming 2>&1 | tee -a logs/daily.log
python3 -m src.cli plan --date "$(date -u +%Y-%m-%d)" 2>&1 | tee -a logs/daily.log
python3 -m src.cli visit-plan 2>&1 | tee -a logs/daily.log

echo "Done. See output/ for today's CSVs." | tee -a logs/daily.log
