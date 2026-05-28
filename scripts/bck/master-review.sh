#!/bin/bash
# scripts/master-review.sh
# Main orchestration script for the 4-piece AI Code Review system.

set -e
set -o pipefail

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]:-$0}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"

# Load Environment
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi

# Inputs
REPO_URL=$1
BRANCH=${2:-"main"}
PR_NUMBER=${3:-0}
PROJECT_KEY=${4:-$SONAR_PROJECT_KEY}

echo "[1/4] Starting SonarQube Scan..."
"$SCRIPT_DIR/run-sonar-scan.sh" "$REPO_URL" "$BRANCH" "$PROJECT_KEY" "$PR_NUMBER"

echo "[2/4] Building Smart Context Package..."
"$PYTHON_BIN" "$SCRIPT_DIR/fetch-sonar-results.py" \
    --project "$PROJECT_KEY" \
    --repo "$REPO_URL" \
    --branch "$BRANCH" \
    --pr "$PR_NUMBER" > "$PROJECT_ROOT/context.json"

echo "[3/4] Performing Gemini AI Review (CLI Mode)..."
"$PYTHON_BIN" "$SCRIPT_DIR/gemini-review.py" < "$PROJECT_ROOT/context.json" > "$PROJECT_ROOT/ai_review.json"

echo "[4/4] Generating Final HTML Report..."
"$PYTHON_BIN" "$SCRIPT_DIR/generate-report.py" < "$PROJECT_ROOT/ai_review.json" > "$PROJECT_ROOT/report_output.txt"

# Output the report path for N8N
REPORT_PATH=$(grep "--- REPORT_PATH_START ---" -A 1 "$PROJECT_ROOT/report_output.txt" | tail -n 1)
echo "--------------------------------------"
echo "PIPELINE COMPLETE"
echo "REPORT: $REPORT_PATH"
echo "--------------------------------------"
