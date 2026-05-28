#!/bin/bash
# scripts/run-sonar-scan.sh
# Piece 1: Triggers SonarQube Scanner directly on the codebase.

set -e
set -o pipefail

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]:-$0}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"

# Load Environment
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Sourcing environment from $PROJECT_ROOT/.env"
    source "$PROJECT_ROOT/.env"
else
    echo "Warning: .env file not found at $PROJECT_ROOT/.env"
fi

# Inputs
REPO_URL=$1
BRANCH=${2:-"main"}
PROJECT_KEY=${3:-$SONAR_PROJECT_KEY}
PR_NUMBER=${4:-0}

# SonarConfig
SONAR_HOST_URL=${SONAR_HOST_URL:-"http://localhost:9000"}
SONAR_TOKEN=${SONAR_TOKEN}
SONAR_SCANNER_BIN=${SONAR_SCANNER_BIN:-"sonar-scanner"}
SONAR_EDITION=${SONAR_EDITION:-"community"}

# Setup Workspace
WORKSPACE_DIR="${WORKSPACE_PATH:-$PROJECT_ROOT/workspace}"
SCAN_ID=$(date +%s)
SCAN_DIR="$WORKSPACE_DIR/$SCAN_ID"
mkdir -p "$SCAN_DIR"

echo "--- SONAR SCAN CONFIGURATION ---"
echo "Project: $PROJECT_KEY"
echo "Branch:  $BRANCH"
echo "PR:      $PR_NUMBER"
echo "Edition: $SONAR_EDITION"
echo "Host:    $SONAR_HOST_URL"
echo "--------------------------------"

echo "Cloning repository $REPO_URL (branch: $BRANCH)..."
# Handle GITHUB_TOKEN if available
if [ ! -z "$GITHUB_TOKEN" ] && [[ "$REPO_URL" == *"github.com"* ]]; then
    AUTH_REPO_URL=$(echo "$REPO_URL" | sed "s|https://github.com/|https://$GITHUB_TOKEN@github.com/|")
    git clone --depth 1 --branch "$BRANCH" "$AUTH_REPO_URL" "$SCAN_DIR"
else
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SCAN_DIR"
fi

cd "$SCAN_DIR"

echo "🔍 Running SonarQube Analysis..."
SCANNER_FLAGS=(
  "-Dsonar.projectKey=$PROJECT_KEY"
  "-Dsonar.sources=."
  "-Dsonar.host.url=$SONAR_HOST_URL"
  "-Dsonar.token=$SONAR_TOKEN"
  "-Dsonar.sourceEncoding=UTF-8"
  "-Dsonar.exclusions=**/vendor/**,**/node_modules/**,**/*.pb.go,**/*.min.js"
)

# Add PR flags if applicable (Only for Developer/Enterprise editions)
if [ "$PR_NUMBER" != "0" ] && [ "$SONAR_EDITION" != "community" ]; then
  echo "Using Native PR Analysis (Developer/Enterprise Mode)..."
  SCANNER_FLAGS+=(
    "-Dsonar.pullrequest.key=$PR_NUMBER"
    "-Dsonar.pullrequest.branch=$BRANCH"
    "-Dsonar.pullrequest.base=main"
  )
else
  echo "Standard Branch Analysis (PR flags disabled for $SONAR_EDITION)..."
fi

"$SONAR_SCANNER_BIN" "${SCANNER_FLAGS[@]}"

echo "Analysis complete. Waiting for SonarQube to process..."
# Short sleep to allow SonarQube background tasks to start
sleep 10
