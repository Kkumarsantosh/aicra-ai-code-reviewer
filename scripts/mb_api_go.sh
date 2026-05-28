#!/bin/bash

export PATH="$HOME/npm-global/bin:$PATH"
export GOOGLE_CLOUD_PROJECT="elab-code-assist"
export GOOGLE_CLOUD_PROJECT_ID="elab-code-assist"
source ~/.zshrc

# 1. Run Scan
echo "🔍 Step 1: Running SonarQube Analysis..."
JAVA_HOME=/opt/homebrew/opt/openjdk@17 /Users/santosh.kumar/Work/ai-code-review/lib/sonar-scanner-8.0.1.6346-macosx-aarch64/bin/sonar-scanner \
  -Dsonar.projectName='Moneyback-Api-4.0' \
  -Dsonar.projectKey='moneyback-api-4.0-UAT' \
  -Dsonar.host.url='http://10.32.83.180:9002/' \
  -Dsonar.token='sqp_12e314eb2d8f05a053af81dd8f137fc841e5ed1f' \
  -Dsonar.projectBaseDir=/Users/santosh.kumar/Work/Development/MoneyBack/elabasia-mobileapp-moneyback-app-api \
  -Dsonar.sources=/Users/santosh.kumar/Work/Development/MoneyBack/elabasia-mobileapp-moneyback-app-api/internal \
  -Dsonar.go.exclusions="**/vendor/**,**/testdata/**,**/Dockerfile,**/*.pb.go,**/*.pb.gw.go" \
  -Dsonar.exclusions="**/Dockerfile,**/*.exe,**/tools/**" \
  -Dsonar.tests=. \
  -Dsonar.test.inclusions="**/*_test.go"

# 2. Extract Data
echo "📥 Step 2: Fetching SonarQube Issues..."
curl -s -u "sqp_12e314eb2d8f05a053af81dd8f137fc841e5ed1f:" \
     "http://10.32.83.180:9002/api/issues/search?componentKeys=moneyback-api-4.0-UAT&ps=500" \
     -o sonar_report.json

# 3. Gemini AI Logical & Architectural Audit
echo "🤖 Step 3: Performing Gemini AI Logical Audit..."
# We pipe the context files into the gemini command and use a single -p for the instructions
(cat sonar_report.json; cat scripts/my_coding_standards.md) | gemini -p "Act as a Principal Go Architect. 

I have provided 'sonar_report.json' (first part of input) and 'scripts/my_coding_standards.md' (second part).
DO NOT just repeat the SonarQube rule. Instead, perform a **Logical Deep Dive** on the code at those locations.

Your Goal: Find bugs in the LOGIC, not the syntax.
Analyze for:
1. **Race Conditions:** Look for 'Check-then-Act' patterns (e.g., checking balance then deducting).
2. **Distributed Transaction Failures:** Identify paths where a failure after a 'Point of No Return' (like payment capture) leaves the system inconsistent.
3. **Idempotency Gaps:** Ensure API callbacks handle 'Already Processed' or 'Expired' states safely.
4. **Standard Alignment:** Match against 'scripts/my_coding_standards.md'.

Format each finding:
### 🚨 [Logical Flaw Title] (Severity: [Critical/Major])
- **Standard:** [Relevant Standard]
- **Location:** [File Path]:[Line]
- **The Logic Failure:** [Explain why the math works but the business logic fails]
- **The Principal Fix:** 
\`\`\`go
[Provide a robust, transactional implementation]
\`\`\`
" > GEMINI_REVIEW.md

# 4. Generate Dashboard
echo "📊 Step 4: Generating Modern HTML Dashboard..."
python3 scripts/generate_dashboard.py sonar_report.json GEMINI_REVIEW.md

echo "✅ Workflow Complete!"
echo "📄 Sonar Report: sonar_report.json"
echo "🤖 AI Review: GEMINI_REVIEW.md"
echo "🌐 Dashboard: Look in the reports/ directory for the latest HTML file."
