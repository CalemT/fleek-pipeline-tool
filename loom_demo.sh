#!/usr/bin/env bash
# LOOM DEMO SCRIPT - not part of the project, just a recording aid.
# Run this from inside the fleek-pipeline-tool folder:  ./loom_demo.sh
# It runs each real command for you and pauses - just press Enter at each
# pause while you narrate from your phone script. Safe to run as many times
# as you want before the real take - it resets to a clean state every time.

set -e
cd "$(dirname "$0")"

pause() {
    echo
    read -p ">>> press Enter to continue <<< " _
    clear
}

run() {
    echo "\$ $1"
    echo
    eval "$1"
}

# Always start from a clean slate, so the numbers are identical every take
rm -rf output logs

clear
echo "Ready for Beat 1. Press Enter to begin."
read -p "" _
clear

# ---- BEAT 1 ----
run "python3 -m src.cli ingest --file data/pipeline_data.xlsx --sheet pipeline --batch initial_handover"
pause

run "python3 -m src.cli plan --date 2026-06-25"
echo
echo ">>> Now open outreach_instagram_2026-06-25.csv and read one drafted message out loud. <<<"
pause

# ---- BEAT 2 ----
run "python3 -m src.cli plan --date 2026-06-25"
echo
echo ">>> Point at: 0 new, 40 already queued. <<<"
pause

# ---- BEAT 3 ----
run "python3 -m src.cli ingest --file data/pipeline_data.xlsx --sheet new_drop_day2 --batch day2"
echo
echo ">>> Say slowly: 28 new, 2 merged - those 2 were already in the list under a different ID. <<<"
pause

echo "Terminal part done. Now switch to the browser for Beats 4 and 5 (dashboard + repo tour)."
