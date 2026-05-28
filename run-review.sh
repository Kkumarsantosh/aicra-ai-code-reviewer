#!/bin/bash
# ═══════════════════════════════════════════════════════════
# AI CODE REVIEW PIPELINE
# SonarQube Scan → Preprocess → Gemini Deep Review → HTML Report
# ═══════════════════════════════════════════════════════════

set -uo pipefail

# ── CONFIGURATION ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
REPORTS_DIR="${SCRIPT_DIR}/reports"
WORK_DIR="${SCRIPT_DIR}/workspace/${TIMESTAMP}"


# Load credentials from .env
if [ -f "${SCRIPT_DIR}/config/.env" ]; then
    source "${SCRIPT_DIR}/config/.env"
else
    echo "❌ config/.env not found. Copy config/.env.example and fill in your values."
    exit 1
fi

export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT}"
export GOOGLE_CLOUD_PROJECT_ID="${GOOGLE_CLOUD_PROJECT_ID}"
export JAVA_HOME="${JAVA_HOME}"

# Output files
export SONAR_RAW="${WORK_DIR}/sonar_report_raw.json"
export SONAR_FILTERED="${WORK_DIR}/sonar_report_filtered.json"
export GEMINI_RAW="${WORK_DIR}/gemini_raw_output.txt"
export GEMINI_JSON="${WORK_DIR}/gemini_review.json"
REPORT_HTML="${REPORTS_DIR}/review_${TIMESTAMP}.html"
export GOOGLE_CLOUD_PROJECT="elab-code-assist"
export GOOGLE_CLOUD_PROJECT_ID="elab-code-assist"

# ── SETUP ──
mkdir -p "${REPORTS_DIR}" "${WORK_DIR}"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  🤖 AI CODE REVIEW PIPELINE"
echo "  Project: ${SONAR_PROJECT_NAME}"
echo "  Time: $(date)"
echo "═══════════════════════════════════════════════════════"
echo ""

PIPELINE_START=$(date +%s)

# ── DEPENDENCY CHECK ──
echo "🔎 Checking dependencies..."

check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "  ❌ $1 not found. $2"
        exit 1
    else
        echo "  ✅ $1"
    fi
}

check_command "python3" "Install Python 3"
check_command "curl" "Install curl"
check_command "jq" "Install jq: brew install jq"
check_command "gemini" "Install Gemini CLI: npm install -g @anthropic-ai/claude-code (or Google Gemini CLI)"

if [ ! -f "${SCANNER_PATH}" ]; then
    echo "  ❌ SonarScanner not found at: ${SCANNER_PATH}"
    exit 1
else
    echo "  ✅ SonarScanner"
fi

if [ ! -d "${PROJECT_BASE_DIR}" ]; then
    echo "  ❌ Project directory not found: ${PROJECT_BASE_DIR}"
    exit 1
else
    echo "  ✅ Project directory"
fi

echo ""


# ══════════════════════════════════════════════════════════
# STEP 1: RUN SONARQUBE SCAN
# ══════════════════════════════════════════════════════════

echo "═══════════════════════════════════════════════════════"
echo "  🔍 STEP 1: Running SonarQube Analysis..."
echo "═══════════════════════════════════════════════════════"
echo ""

SCAN_START=$(date +%s)

"${SCANNER_PATH}" \
    -Dsonar.projectName="${SONAR_PROJECT_NAME}" \
    -Dsonar.projectKey="${SONAR_PROJECT_KEY}" \
    -Dsonar.host.url="${SONAR_HOST}" \
    -Dsonar.token="${SONAR_TOKEN}" \
    -Dsonar.projectBaseDir="${PROJECT_BASE_DIR}" \
    -Dsonar.sources="${PROJECT_SOURCES}" \
    -Dsonar.go.exclusions="**/vendor/**,**/testdata/**,**/Dockerfile,**/*.pb.go,**/*.pb.gw.go" \
    -Dsonar.exclusions="**/Dockerfile,**/*.exe,**/tools/**,**/vendor/**" \
    -Dsonar.tests=. \
    -Dsonar.test.inclusions="**/*_test.go" \
    -Dsonar.sourceEncoding=UTF-8

SCAN_EXIT=$?

if [ $SCAN_EXIT -ne 0 ]; then
    echo ""
    echo "❌ SonarScanner failed with exit code: ${SCAN_EXIT}"
    echo "   Check SonarQube server status: ${SONAR_HOST}"
    exit 1
fi

SCAN_END=$(date +%s)
echo ""
echo "  ✅ Scanner finished in $((SCAN_END - SCAN_START))s"
echo ""


# ══════════════════════════════════════════════════════════
# STEP 2: WAIT FOR SERVER-SIDE ANALYSIS
# ══════════════════════════════════════════════════════════

echo "═══════════════════════════════════════════════════════"
echo "  ⏳ STEP 2: Waiting for SonarQube server analysis..."
echo "═══════════════════════════════════════════════════════"
echo ""

MAX_WAIT=180  # 3 minutes max
ELAPSED=0
ANALYSIS_DONE=false

while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Check CE (Compute Engine) task status
    CE_STATUS=$(curl -s -u "${SONAR_TOKEN}:" \
        "${SONAR_HOST}/api/ce/component?component=${SONAR_PROJECT_KEY}" \
        2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    current = data.get('current')
    if current:
        print(current.get('status', 'UNKNOWN'))
    else:
        queue = data.get('queue', [])
        if queue:
            print('IN_QUEUE')
        else:
            print('DONE')
except:
    print('ERROR')
" 2>/dev/null || echo "ERROR")

    case "$CE_STATUS" in
        "SUCCESS"|"DONE")
            ANALYSIS_DONE=true
            echo "  ✅ Analysis complete!"
            break
            ;;
        "FAILED")
            echo "  ❌ Server-side analysis FAILED."
            echo "     Check SonarQube: ${SONAR_HOST}/project/activity?id=${SONAR_PROJECT_KEY}"
            exit 1
            ;;
        "CANCELED")
            echo "  ❌ Analysis was canceled."
            exit 1
            ;;
        "PENDING"|"IN_PROGRESS"|"IN_QUEUE")
            echo "  ⏳ Analysis in progress... (${ELAPSED}s / ${MAX_WAIT}s)"
            sleep 10
            ELAPSED=$((ELAPSED + 10))
            ;;
        *)
            echo "  ⚠️  Unknown status: ${CE_STATUS}, waiting..."
            sleep 10
            ELAPSED=$((ELAPSED + 10))
            ;;
    esac
done

if [ "$ANALYSIS_DONE" != "true" ]; then
    echo ""
    echo "  ⚠️  Analysis may not be complete (timed out after ${MAX_WAIT}s)"
    echo "     Proceeding with available results..."
fi
echo ""


# ══════════════════════════════════════════════════════════
# STEP 3: FETCH SONARQUBE RESULTS
# ══════════════════════════════════════════════════════════

echo "═══════════════════════════════════════════════════════"
echo "  📥 STEP 3: Fetching SonarQube Results..."
echo "═══════════════════════════════════════════════════════"
echo ""

# Fetch issues (paginated, get up to 500)
curl -s -u "${SONAR_TOKEN}:" \
    "${SONAR_HOST}/api/issues/search?componentKeys=${SONAR_PROJECT_KEY}&ps=500&statuses=OPEN,CONFIRMED,REOPENED" \
    -o "${SONAR_RAW}"

# Validate we got valid JSON
if ! jq empty "${SONAR_RAW}" 2>/dev/null; then
    echo "  ❌ Invalid JSON response from SonarQube API"
    echo "     Response: $(head -c 200 ${SONAR_RAW})"
    exit 1
fi

TOTAL_ISSUES=$(jq '.total // 0' "${SONAR_RAW}")
echo "  📊 Total issues found: ${TOTAL_ISSUES}"
echo ""

# ══════════════════════════════════════════════════════════
# STEP 4: PREPROCESS & FILTER FOR AI REVIEW
# ══════════════════════════════════════════════════════════

echo "═══════════════════════════════════════════════════════"
echo "  🧹 STEP 4: Preprocessing SonarQube Report for AI..."
echo "═══════════════════════════════════════════════════════"
echo ""

# *** THE FIX: Export variables BEFORE Python runs ***
export SONAR_RAW="${SONAR_RAW}"
export SONAR_FILTERED="${SONAR_FILTERED}"
export MAX_ISSUES_FOR_AI="${MAX_ISSUES_FOR_AI:-80}"

# Debug: Verify paths exist
echo "  📂 Raw report path: ${SONAR_RAW}"
if [ ! -f "${SONAR_RAW}" ]; then
    echo "  ❌ Raw SonarQube report not found at: ${SONAR_RAW}"
    echo "     Checking current directory..."
    ls -la *.json 2>/dev/null || echo "     No JSON files in current directory"
    echo "     Checking workspace..."
    ls -la "${WORK_DIR}/"*.json 2>/dev/null || echo "     No JSON files in workspace"
    exit 1
fi

python3 << 'PREPROCESS_SCRIPT'
import json
import sys
import os

raw_path = os.environ.get('SONAR_RAW')
filtered_path = os.environ.get('SONAR_FILTERED')
max_issues = int(os.environ.get('MAX_ISSUES_FOR_AI', '80'))

# Safety check
if not raw_path or not os.path.exists(raw_path):
    print(f"  ❌ ERROR: Cannot find SonarQube report at: {raw_path}")
    print(f"     Current dir: {os.getcwd()}")
    print(f"     SONAR_RAW env: {raw_path}")
    sys.exit(1)

print(f"  📂 Reading: {raw_path}")

with open(raw_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

issues = data.get('issues', [])
original_count = len(issues)

if original_count == 0:
    print("  ⚠️  No issues in SonarQube report")

# Step 1: Remove closed/resolved issues
issues = [i for i in issues if i.get('status') in ('OPEN', 'CONFIRMED', 'REOPENED')]

# Step 2: Remove INFO severity (too noisy for AI)
issues = [i for i in issues if i.get('severity') != 'INFO']

# Step 3: Sort by severity (most critical first)
severity_order = {'BLOCKER': 0, 'CRITICAL': 1, 'MAJOR': 2, 'MINOR': 3}
issues.sort(key=lambda x: severity_order.get(x.get('severity', ''), 99))

# Step 4: Deduplicate (same rule + same file + same line)
seen = set()
unique_issues = []
for issue in issues:
    key = f"{issue.get('rule')}:{issue.get('component')}:{issue.get('line', 0)}"
    if key not in seen:
        seen.add(key)
        unique_issues.append(issue)
issues = unique_issues

# Step 5: Slim down each issue (remove unnecessary fields for AI)
slim_issues = []
for issue in issues[:max_issues]:
    component = issue.get('component', '')
    file_path = component.split(':')[-1] if ':' in component else component
    
    slim_issues.append({
        'rule': issue.get('rule', ''),
        'severity': issue.get('severity', ''),
        'type': issue.get('type', ''),
        'message': issue.get('message', ''),
        'file': file_path,
        'line': issue.get('line', 0),
        'effort': issue.get('effort', ''),
        'tags': issue.get('tags', [])
    })

# Build filtered report
filtered = {
    'metadata': {
        'original_issue_count': original_count,
        'filtered_issue_count': len(slim_issues),
        'filter_note': f'Top {max_issues} issues by severity. INFO excluded. Duplicates removed.'
    },
    'summary': {
        'blockers': len([i for i in slim_issues if i['severity'] == 'BLOCKER']),
        'criticals': len([i for i in slim_issues if i['severity'] == 'CRITICAL']),
        'majors': len([i for i in slim_issues if i['severity'] == 'MAJOR']),
        'minors': len([i for i in slim_issues if i['severity'] == 'MINOR']),
        'bugs': len([i for i in slim_issues if i['type'] == 'BUG']),
        'vulnerabilities': len([i for i in slim_issues if i['type'] == 'VULNERABILITY']),
        'code_smells': len([i for i in slim_issues if i['type'] == 'CODE_SMELL']),
    },
    'issues': slim_issues,
    'files_affected': sorted(set(i['file'] for i in slim_issues))
}

# Write filtered report
print(f"  📂 Writing: {filtered_path}")
os.makedirs(os.path.dirname(filtered_path) or '.', exist_ok=True)

with open(filtered_path, 'w', encoding='utf-8') as f:
    json.dump(filtered, f, indent=2)

s = filtered['summary']
print(f"  📊 Preprocessing complete:")
print(f"     Original issues:  {original_count}")
print(f"     After filtering:  {len(slim_issues)}")
print(f"     ─────────────────────────────")
print(f"     🔴 Blockers:      {s['blockers']}")
print(f"     🟠 Criticals:     {s['criticals']}")
print(f"     🟡 Majors:        {s['majors']}")
print(f"     🟢 Minors:        {s['minors']}")
print(f"     ─────────────────────────────")
print(f"     🐛 Bugs:          {s['bugs']}")
print(f"     🔒 Vulnerabilities: {s['vulnerabilities']}")
print(f"     💨 Code Smells:   {s['code_smells']}")
print(f"     📁 Files affected: {len(filtered['files_affected'])}")

PREPROCESS_SCRIPT

# Check if preprocessing succeeded
if [ $? -ne 0 ]; then
    echo ""
    echo "  ❌ Preprocessing failed"
    exit 1
fi

if [ ! -f "${SONAR_FILTERED}" ]; then
    echo "  ❌ Filtered report was not created at: ${SONAR_FILTERED}"
    exit 1
fi

echo ""

# ══════════════════════════════════════════════════════════
# STEP 5: GEMINI AI DEEP REVIEW
# ══════════════════════════════════════════════════════════

echo "═══════════════════════════════════════════════════════"
echo "  🤖 STEP 5: Running Gemini AI Deep Review..."
echo "═══════════════════════════════════════════════════════"
echo ""

GEMINI_START=$(date +%s)

PROMPT_FILE="${SCRIPT_DIR}/scripts/prompt.txt"
STANDARDS_FILE="${SCRIPT_DIR}/scripts/my_coding_standards.md"

if [ ! -f "${PROMPT_FILE}" ]; then
    echo "  ❌ Prompt not found: ${PROMPT_FILE}"
    exit 1
fi

if [ ! -f "${SONAR_FILTERED}" ]; then
    echo "  ❌ Filtered report not found: ${SONAR_FILTERED}"
    exit 1
fi

# ── Build a single combined input file ──
# Gemini CLI cannot use -p and @file together.
# So we combine prompt + standards + sonar report into ONE file.

COMBINED_INPUT="${WORK_DIR}/gemini_combined_input.txt"

echo "  📝 Building combined input file..."

# Start with the prompt
cat "${PROMPT_FILE}" > "${COMBINED_INPUT}"

# Add coding standards if available
if [ -f "${STANDARDS_FILE}" ]; then
    echo "" >> "${COMBINED_INPUT}"
    echo "" >> "${COMBINED_INPUT}"
    echo "## TEAM CODING STANDARDS:" >> "${COMBINED_INPUT}"
    echo "" >> "${COMBINED_INPUT}"
    cat "${STANDARDS_FILE}" >> "${COMBINED_INPUT}"
    echo "  📏 Standards: included"
else
    echo "  📏 Standards: not found (skipping)"
fi

# Add the SonarQube report
echo "" >> "${COMBINED_INPUT}"
echo "" >> "${COMBINED_INPUT}"
echo "## SONARQUBE REPORT (sonar_report.json):" >> "${COMBINED_INPUT}"
echo "" >> "${COMBINED_INPUT}"
cat "${SONAR_FILTERED}" >> "${COMBINED_INPUT}"

# Add final instruction
echo "" >> "${COMBINED_INPUT}"
echo "" >> "${COMBINED_INPUT}"
echo "Analyze ALL issues above. Use the EXACT output format specified earlier with ASSESSMENT_START, ---VALIDATION_START---, and ---FINDING_START--- markers. Do not skip any SonarQube finding." >> "${COMBINED_INPUT}"

# Show stats
COMBINED_SIZE=$(wc -c < "${COMBINED_INPUT}" | tr -d ' ')
ISSUE_COUNT=$(python3 -c "import json; d=json.load(open('${SONAR_FILTERED}')); print(len(d.get('issues',[])))" 2>/dev/null || echo "?")

echo "  📊 Issues being reviewed: ${ISSUE_COUNT}"
echo "  📦 Combined input: ${COMBINED_SIZE} bytes"

# Check if input is too large
if [ "${COMBINED_SIZE}" -gt 500000 ]; then
    echo "  ⚠️  Input is very large. Reducing issues to 30..."
    python3 << REDUCE
import json
with open('${SONAR_FILTERED}') as f:
    d = json.load(f)
d['issues'] = d['issues'][:30]
d['metadata']['filter_note'] = 'Reduced to 30 issues due to size'
with open('${SONAR_FILTERED}', 'w') as f:
    json.dump(d, f, indent=2)
print(f"  Reduced to {len(d['issues'])} issues")
REDUCE
    # Rebuild combined input with reduced report
    cat "${PROMPT_FILE}" > "${COMBINED_INPUT}"
    [ -f "${STANDARDS_FILE}" ] && { echo -e "\n\n## TEAM CODING STANDARDS:\n"; cat "${STANDARDS_FILE}"; } >> "${COMBINED_INPUT}"
    echo -e "\n\n## SONARQUBE REPORT:\n" >> "${COMBINED_INPUT}"
    cat "${SONAR_FILTERED}" >> "${COMBINED_INPUT}"
    echo -e "\n\nAnalyze ALL issues above using the exact output format with ASSESSMENT_START, ---VALIDATION_START---, and ---FINDING_START--- markers." >> "${COMBINED_INPUT}"
    COMBINED_SIZE=$(wc -c < "${COMBINED_INPUT}" | tr -d ' ')
    echo "  📦 Reduced input: ${COMBINED_SIZE} bytes"
fi

echo ""
echo "  ⏳ Calling Gemini CLI (30-120 seconds)..."
echo ""

# ── Call Gemini CLI ──
# Use @file syntax (pass entire input as one file, no -p flag)
set +e

gemini @"${COMBINED_INPUT}" \
    > "${GEMINI_RAW}" 2>"${WORK_DIR}/gemini_stderr.txt"

GEMINI_EXIT=$?

set -e

GEMINI_END=$(date +%s)
GEMINI_DURATION=$((GEMINI_END - GEMINI_START))

echo ""
echo "  ── Result ──"
echo "  Exit code: ${GEMINI_EXIT}"
echo "  Duration: ${GEMINI_DURATION}s"

# ── Handle failure ──
if [ ${GEMINI_EXIT} -ne 0 ]; then
    echo ""
    echo "  ❌ Gemini CLI failed (exit: ${GEMINI_EXIT})"
    
    if [ -s "${WORK_DIR}/gemini_stderr.txt" ]; then
        echo ""
        echo "  ── Error ──"
        cat "${WORK_DIR}/gemini_stderr.txt"
    fi

    # Check if partial output exists
    if [ -s "${GEMINI_RAW}" ]; then
        PARTIAL_SIZE=$(wc -c < "${GEMINI_RAW}" | tr -d ' ')
        echo ""
        echo "  ⚠️  Partial output exists (${PARTIAL_SIZE} bytes). Trying to use it..."
    else
        echo ""
        echo "  ── Retrying with pipe approach ──"
        
        set +e
        cat "${COMBINED_INPUT}" | gemini \
            > "${GEMINI_RAW}" 2>"${WORK_DIR}/gemini_stderr2.txt"
        RETRY_EXIT=$?
        set -e

        if [ ${RETRY_EXIT} -eq 0 ] && [ -s "${GEMINI_RAW}" ]; then
            echo "  ✅ Retry with pipe succeeded!"
            GEMINI_EXIT=0
        else
            echo "  ❌ Pipe retry also failed"
            if [ -s "${WORK_DIR}/gemini_stderr2.txt" ]; then
                cat "${WORK_DIR}/gemini_stderr2.txt"
            fi

            echo ""
            echo "  ── Retrying with -p flag (short prompt) ──"
            
            # Last resort: put report in -p, no @file
            set +e
            gemini -p "$(cat "${COMBINED_INPUT}")" \
                > "${GEMINI_RAW}" 2>"${WORK_DIR}/gemini_stderr3.txt"
            RETRY2_EXIT=$?
            set -e

            if [ ${RETRY2_EXIT} -eq 0 ] && [ -s "${GEMINI_RAW}" ]; then
                echo "  ✅ Retry with -p flag succeeded!"
                GEMINI_EXIT=0
            else
                echo "  ❌ All approaches failed."
                
                if [ -s "${WORK_DIR}/gemini_stderr3.txt" ]; then
                    cat "${WORK_DIR}/gemini_stderr3.txt"
                fi
                
                echo ""
                echo "  Creating fallback review..."
                cat > "${GEMINI_JSON}" << 'FALLBACK'
{
  "sonarValidation": [],
  "logicalFindings": [],
  "assessment": {
    "overallRisk": "UNKNOWN",
    "recommendation": "NEEDS_DISCUSSION",
    "summary": "Gemini review could not be completed. SonarQube data is available. Try reducing MAX_ISSUES_FOR_AI to 20 in config/.env or use the Python API approach.",
    "positives": [],
    "topRisks": ["AI review failed - manual review required"]
  }
}
FALLBACK
            fi
        fi
    fi
fi

# ── Handle success ──
if [ ${GEMINI_EXIT} -eq 0 ] && [ -s "${GEMINI_RAW}" ]; then
    RAW_SIZE=$(wc -c < "${GEMINI_RAW}" | tr -d ' ')
    RAW_LINES=$(wc -l < "${GEMINI_RAW}" | tr -d ' ')
    
    echo ""
    echo "  ✅ Gemini responded successfully!"
    echo "  📄 Output: ${RAW_SIZE} bytes, ${RAW_LINES} lines"
    echo ""
    
    # Show first 400 chars
    echo "  ── Preview ──"
    head -c 400 "${GEMINI_RAW}"
    echo ""
    echo "  ..."
    echo ""
    
    # Check for structured markers
    MARK_A=$(grep -c "ASSESSMENT_START" "${GEMINI_RAW}" 2>/dev/null || echo "0")
    MARK_V=$(grep -c "VALIDATION_START" "${GEMINI_RAW}" 2>/dev/null || echo "0")
    MARK_F=$(grep -c "FINDING_START" "${GEMINI_RAW}" 2>/dev/null || echo "0")
    
    echo "  ── Markers Found ──"
    echo "  ASSESSMENT_START: ${MARK_A}"
    echo "  ---VALIDATION_START---: ${MARK_V}"
    echo "  ---FINDING_START---: ${MARK_F}"
    
    if [ "${MARK_A}" = "0" ] && [ "${MARK_V}" = "0" ] && [ "${MARK_F}" = "0" ]; then
        echo ""
        echo "  ⚠️  No structured markers found."
        echo "     Parser will use freeform markdown extraction."
    fi
fi

echo ""


# ══════════════════════════════════════════════════════════
# STEP 6: PARSE GEMINI OUTPUT TO JSON
# ══════════════════════════════════════════════════════════

echo "═══════════════════════════════════════════════════════"
echo "  🔄 STEP 6: Parsing Gemini Output..."
echo "═══════════════════════════════════════════════════════"
echo ""

if [ -s "${GEMINI_RAW}" ]; then
    python3 "${SCRIPT_DIR}/scripts/parse_gemini_output.py" \
        "${GEMINI_RAW}" \
        "${GEMINI_JSON}"
fi

# Validate JSON
if ! jq empty "${GEMINI_JSON}" 2>/dev/null; then
    echo "  ⚠️  Gemini output could not be parsed as JSON"
    echo "     Raw output saved at: ${GEMINI_RAW}"
    echo "     Using fallback..."
    
    cat > "${GEMINI_JSON}" << FALLBACK2
{
  "sonarValidation": [],
  "logicalFindings": [],
  "assessment": {
    "overallRisk": "UNKNOWN",
    "recommendation": "NEEDS_DISCUSSION",
    "summary": "AI output could not be parsed. Raw output saved for manual inspection.",
    "positives": [],
    "topRisks": ["AI output parsing failed"]
  },
  "parseError": true,
  "rawOutputPath": "${GEMINI_RAW}"
}
FALLBACK2
fi

# Print summary of AI findings
python3 -c "
import json
with open('${GEMINI_JSON}') as f:
    data = json.load(f)

sv = data.get('sonarValidation', [])
lf = data.get('logicalFindings', [])
a = data.get('assessment', {})

confirmed = len([v for v in sv if v.get('verdict') == 'CONFIRMED'])
false_pos = len([v for v in sv if v.get('verdict') == 'FALSE_POSITIVE'])
escalated = len([v for v in sv if v.get('verdict') == 'ESCALATED'])

print(f'  SonarQube Validation:')
print(f'    ✅ Confirmed:      {confirmed}')
print(f'    ❌ False Positives: {false_pos}')
print(f'    ⬆️  Escalated:      {escalated}')
print(f'')
print(f'  AI Logical Findings: {len(lf)}')

for finding in lf:
    sev = finding.get('severity', '?')
    icon = {'CRITICAL':'🚨','HIGH':'🔴','MEDIUM':'🟡','LOW':'🟢'}.get(sev, '📌')
    print(f'    {icon} [{sev}] {finding.get(\"title\", \"Untitled\")}')

print(f'')
print(f'  Overall Risk:      {a.get(\"overallRisk\", \"?\")}')
print(f'  Recommendation:    {a.get(\"recommendation\", \"?\")}')
" 2>/dev/null || echo "  Could not parse AI review summary"

echo ""


# ══════════════════════════════════════════════════════════
# STEP 7: GENERATE HTML REPORT
# ══════════════════════════════════════════════════════════

echo "═══════════════════════════════════════════════════════"
echo "  📊 STEP 7: Generating HTML Report..."
echo "═══════════════════════════════════════════════════════"
echo ""

python3 "${SCRIPT_DIR}/scripts/generate_dashboard.py" \
    "${SONAR_RAW}" \
    "${SONAR_FILTERED}" \
    "${GEMINI_JSON}" \
    "${REPORT_HTML}" \
    "${SONAR_PROJECT_NAME}" \
    "${TIMESTAMP}"

if [ -f "${REPORT_HTML}" ]; then
    REPORT_SIZE=$(du -h "${REPORT_HTML}" | cut -f1)
    echo "  ✅ Report generated: ${REPORT_HTML} (${REPORT_SIZE})"
else
    echo "  ❌ Report generation failed"
fi

echo ""

# ══════════════════════════════════════════════════════════
# STEP 8: CLEANUP & SUMMARY
# ══════════════════════════════════════════════════════════

# Copy key files to reports directory
cp "${SONAR_FILTERED}" "${REPORTS_DIR}/sonar_filtered_${TIMESTAMP}.json" 2>/dev/null || true
cp "${GEMINI_JSON}" "${REPORTS_DIR}/gemini_review_${TIMESTAMP}.json" 2>/dev/null || true
cp "${GEMINI_RAW}" "${REPORTS_DIR}/gemini_raw_${TIMESTAMP}.txt" 2>/dev/null || true

# Cleanup workspace
#rm -rf "${WORK_DIR}"

PIPELINE_END=$(date +%s)
TOTAL_DURATION=$((PIPELINE_END - PIPELINE_START))

echo "═══════════════════════════════════════════════════════"
echo "  ✅ PIPELINE COMPLETE"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "  ⏱️  Total duration: ${TOTAL_DURATION}s"
echo ""
echo "  📄 Files generated:"
echo "     HTML Report:      ${REPORT_HTML}"
echo "     Sonar Results:    ${REPORTS_DIR}/sonar_filtered_${TIMESTAMP}.json"
echo "     AI Review:        ${REPORTS_DIR}/gemini_review_${TIMESTAMP}.json"
echo "     AI Raw Output:    ${REPORTS_DIR}/gemini_raw_${TIMESTAMP}.txt"
echo ""

# Open report in browser (macOS)
if command -v open &> /dev/null && [ -f "${REPORT_HTML}" ]; then
    echo "  🌐 Opening report in browser..."
    open "${REPORT_HTML}"
fi