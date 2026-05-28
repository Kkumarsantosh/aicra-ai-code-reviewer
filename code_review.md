Bug #1: Prompt Passed as CLI Argument — Will Silently Fail on Large Diffs
This is most likely your primary problem.



# YOUR CODE (line ~285):
def _call_gemini_cli(self, prompt, work_dir):
    cmd = [Config.GEMINI_CLI_BIN, "--prompt", prompt, "--model", model_name, ...]
    process = subprocess.run(cmd, capture_output=True, =True, ...)
    return process.stdout
Your prompt contains the entire git diff + SonarQube findings + project structure + prompt template. That is easily 50,000-200,000 characters. You are passing this as a command-line argument.



Operating System Argument Limits:
  Linux:   ~2MB (but shell expansion can reduce this)
  macOS:   ~256KB
  
Your prompt size:
  Template:         ~4KB
  Git diff:         ~10KB-200KB  
  SonarQube JSON:   ~5KB-50KB
  Project structure: ~2KB-10KB
  Total:            ~20KB-260KB

What happens when it exceeds the limit:
  - subprocess.run silently truncates OR throws OSError
  - The CLI receives a chopped prompt with no closing instructions
  - Gemini gets confused, returns unstructured garbage
  - Parser finds no markers → empty result → blank summary
Fix — Write prompt to a temp file and pass the file path:



import tempfile

def _call_gemini_cli(self, prompt, work_dir):
    """Call Gemini CLI with prompt via temp file to avoid argument length limits."""
    model_name = Config.GEMINI_LARGE_MODEL if len(prompt) > 20000 else Config.GEMINI_DEFAULT_MODEL
    
    env = os.environ.copy()
    env["GOOGLE_CLOUD_PROJECT"] = "elab-code-assist"
    env["GOOGLE_CLOUD_PROJECT_ID"] = "elab-code-assist"
    
    # Write prompt to temp file instead of passing as argument
    prompt_file = os.path.join(work_dir, '.aicra_prompt.txt')
    try:
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        
        # Check if CLI supports file input (common patterns):
        # Option A: --prompt-file flag (if supported)
        cmd = [
            Config.GEMINI_CLI_BIN,
            "--prompt-file", prompt_file,  # or "--input", or pipe stdin
            "--model", model_name,
            "--approval-mode", "plan",
            "--sandbox"
        ]
        
        # Option B: If CLI only supports --prompt, pipe via stdin instead
        # process = subprocess.run(
        #     [Config.GEMINI_CLI_BIN, "--model", model_name, ...],
        #     input=prompt,          # Pass via stdin
        #     capture_output=True, text=True, env=env,
        #     cwd=work_dir, timeout=600
        # )
        
        process = subprocess.run(
            cmd, capture_output=True, text=True, 
            env=env, cwd=work_dir, timeout=600
        )
        
        if process.returncode != 0:
            raise Exception(f"Gemini CLI failed (exit {process.returncode}): {process.stderr[:1000]}")
        
        response = process.stdout
        
        # DIAGNOSTIC: Log response length and first 200 chars
        print(f"      [Gemini] Response length: {len(response)} chars")
        print(f"      [Gemini] Response preview: {response[:200]}")
        
        if not response or len(response.strip()) < 50:
            raise Exception(
                f"Gemini returned empty or very short response ({len(response)} chars). "
                f"Stderr: {process.stderr[:500]}"
            )
        
        return response
        
    finally:
        # Clean up temp file
        if os.path.exists(prompt_file):
            os.remove(prompt_file)
To diagnose RIGHT NOW without code changes, check your gemini_raw_output column:

SQL

-- Run this query to see what Gemini actually returned
SELECT id, 
       LENGTH(gemini_raw_output) as response_length,
       LEFT(gemini_raw_output, 500) as response_preview
FROM reviews 
WHERE status = 'complete' 
ORDER BY id DESC 
LIMIT 5;
If response_length is 0 or very small, or response_preview shows CLI error messages instead of ASSESSMENT_START, the prompt argument is being truncated.

Bug #2: CLI Output Contains Non-Response Text
Even if the prompt gets through, the CLI tool likely wraps Gemini's response with its own output — banners, status messages, thinking indicators.


What process.stdout probably looks like:
──────────────────────────────────────────
🤖 Gemini CLI v1.2.3
Using model: gemini-2.5-pro
Thinking...

ASSESSMENT_START
RISK_LEVEL: HIGH
...actual response...
---SUGGESTIONS_END---

✅ Done! (took 45.2s)
──────────────────────────────────────────

What your parser expects:
──────────────────────────────────────────
ASSESSMENT_START
RISK_LEVEL: HIGH
...
---SUGGESTIONS_END---
──────────────────────────────────────────
Your parser searches for markers like ASSESSMENT_START — if the CLI adds noise before/after, the markers might still be found. But if the CLI adds ANSI color codes, special characters, or interleaves its own status updates with the response, the regex breaks.

Fix — Strip CLI noise before parsing:



def _run_gemini_review_v2(self, review_id, files_affected, work_dir, repo=None, sonar_findings=None):
    # ... existing code ...
    
    try:
        raw_response = self.gemini_breaker.call(self._call_gemini_cli, prompt, work_dir)
        
        # ── CRITICAL: Clean CLI wrapper noise before parsing ──
        cleaned_response = self._clean_cli_output(raw_response)
        
        # Store BOTH raw and cleaned for debugging
        db.update(
            "UPDATE reviews SET gemini_raw_output = %s WHERE id = %s", 
            (raw_response, review_id)
        )
        
        from engine.parse_output import parse_gemini_output
        parsed_result = parse_gemini_output(cleaned_response)
        
        # ── DIAGNOSTIC: Check if parsing produced anything ──
        if not parsed_result.get('assessment') and not parsed_result.get('logicalFindings'):
            print(f"      [ReviewRunner] WARNING: Parser returned empty results!")
            print(f"      [ReviewRunner] Raw response length: {len(raw_response)}")
            print(f"      [ReviewRunner] Cleaned response length: {len(cleaned_response)}")
            print(f"      [ReviewRunner] Contains ASSESSMENT_START: {'ASSESSMENT_START' in cleaned_response}")
            print(f"      [ReviewRunner] Contains FINDING_START: {'---FINDING_START---' in cleaned_response}")
            self._log(review_id, 'parse_warning', 'started', 
                     f"Parser returned empty. Raw={len(raw_response)} chars, "
                     f"Has markers: ASSESSMENT={'ASSESSMENT_START' in cleaned_response}, "
                     f"FINDING={'---FINDING_START---' in cleaned_response}", 0)
        
        # ... rest of method ...


def _clean_cli_output(self, raw_output: str) -> str:
    """Extract the actual Gemini response from CLI wrapper output."""
    
    # Step 1: Remove ANSI color/escape codes
    ansi_pattern = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
    cleaned = ansi_pattern.sub('', raw_output)
    
    # Step 2: Try to extract just the content between our known markers
    # Find the first marker we expect
    first_marker = 'ASSESSMENT_START'
    last_markers = ['---SUGGESTIONS_END---', '---RISK_PREDICTION_END---', 
                    '---FINDING_END---', '---VALIDATION_END---', 'ASSESSMENT_END']
    
    start_idx = cleaned.find(first_marker)
    if start_idx == -1:
        # Markers not found at all — return cleaned and let parser handle it
        print(f"      [ReviewRunner] WARNING: No '{first_marker}' marker found in Gemini response")
        print(f"      [ReviewRunner] Response starts with: {cleaned[:300]}")
        return cleaned
    
    # Find the last marker
    end_idx = -1
    for marker in last_markers:
        idx = cleaned.rfind(marker)
        if idx > end_idx:
            end_idx = idx + len(marker)
    
    if end_idx > start_idx:
        extracted = cleaned[start_idx:end_idx]
        print(f"      [ReviewRunner] Extracted response: {len(extracted)} chars "
              f"(trimmed {len(cleaned) - len(extracted)} chars of CLI noise)")
        return extracted
    
    # Fallback: return everything from first marker onward
    return cleaned[start_idx:]
Bug #3: Field Name Mismatch Between Parser and Storage Code
Your _store_findings method uses field names that don't match the v2 prompt output. This means even if parsing works, the data gets stored as empty strings.



# YOUR STORAGE CODE expects these keys:
f.get('theLogicFailure', '')    # ← old v1 field name
f.get('thePrincipalFix', '')    # ← old v1 field name  
f.get('proofTest', '')          # ← old v1 field name (tests removed in v2)

# YOUR v2 PROMPT outputs:
# WHAT_BREAKS: ...     → parser should produce 'whatBreaks' or 'what_breaks'
# FIXED_CODE: ...      → parser should produce 'fixedCode' or 'fixed_code'
# (no test field in v2)
Similarly for the assessment:



# YOUR CODE expects:
assessment.get('overallRisk', 'UNKNOWN')    # ← expects 'overallRisk'

# YOUR v2 PROMPT outputs:
# RISK_LEVEL: HIGH    → parser likely produces 'riskLevel' not 'overallRisk'
Fix — Align the field names. Choose one mapping and use it consistently:



def _store_findings(self, review_id, ai_result):
    """Store findings and suggestions in database."""
    
    # 1. Store Sonar Validations
    validations = ai_result.get('sonarValidation', [])
    for v in validations:
        verdict = str(v.get('verdict', 'CONFIRMED')).upper()
        if verdict not in ['CONFIRMED', 'FALSE_POSITIVE', 'ESCALATED']:
            verdict = 'CONFIRMED'
        
        source = 'sonar_confirmed'
        if verdict == 'FALSE_POSITIVE': source = 'sonar_false_positive'
        elif verdict == 'ESCALATED': source = 'sonar_escalated'
        
        sev = self._normalize_severity(v.get('severity', 'MEDIUM'))
        
        # FIX: Try multiple possible field names from parser
        explanation = (v.get('explanation') or v.get('whatBreaks') or 
                      v.get('theLogicFailure') or '')                    # FIXED
        fix_code = (v.get('fix') or v.get('fixedCode') or 
                   v.get('thePrincipalFix') or '')                      # FIXED
        mermaid = (v.get('mermaid') or v.get('mermaidDiagram') or '')    # FIXED
        
        db.insert(
            """INSERT INTO findings 
               (review_id, source, ai_verdict, title, category, severity, confidence, 
                file_path, line_start, sonar_rule, explanation, fix_code, 
                mermaid_diagram, standard_violated) 
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (review_id, source, verdict, 
             v.get('sonarRule', v.get('sonar_rule', 'Sonar Issue')),     # FIXED
             'SONAR_VALIDATION', sev,
             float(v.get('confidence', 0.8)), 
             v.get('file', ''), 
             int(v.get('line', 0) or 0),
             v.get('sonarRule', v.get('sonar_rule', '')),                # FIXED
             explanation, fix_code, mermaid,
             v.get('standard', v.get('standardViolated', '')))          # FIXED
        )

    # 2. Store Logical Findings
    findings = ai_result.get('logicalFindings', [])
    for f in findings:
        sev = self._normalize_severity(f.get('severity', 'MEDIUM'))
        
        # FIX: Try multiple possible field names
        explanation = (f.get('whatBreaks') or f.get('theLogicFailure') or 
                      f.get('explanation') or f.get('what_breaks') or '')     # FIXED
        fix_code = (f.get('fixedCode') or f.get('thePrincipalFix') or 
                   f.get('fix') or f.get('fixed_code') or '')                # FIXED
        current_code = (f.get('currentCode') or f.get('current_code') or '') # FIXED
        mermaid = (f.get('mermaid') or f.get('mermaidDiagram') or '')         # FIXED
        
        db.insert(
            """INSERT INTO findings 
               (review_id, source, title, category, severity, confidence, file_path, 
                line_start, line_end, explanation, current_code, fix_code, 
                mermaid_diagram, standard_violated) 
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (review_id, 'ai_finding', 
             f.get('title', ''), 
             f.get('category', 'LOGIC'), 
             sev,
             float(f.get('confidence', 0.7)), 
             f.get('file', ''),
             int(f.get('lineStart', f.get('line_start', 0)) or 0),     # FIXED
             int(f.get('lineEnd', f.get('line_end', 0)) or 0),         # FIXED
             explanation, current_code, fix_code, mermaid,
             f.get('standard', f.get('standardViolated', '')))         # FIXED
        )

    # 3. Store Suggestions (this part looks fine)
    suggestions = ai_result.get('suggestions', [])
    for s in suggestions:
        if s and str(s).strip():
            db.insert(
                "INSERT INTO review_suggestions (review_id, suggestion_text) VALUES (%s, %s)",
                (review_id, str(s).strip())
            )


def _normalize_severity(self, raw_severity):
    """Normalize severity from various sources to our standard values."""
    sev = str(raw_severity).upper().strip()
    mapping = {
        'BLOCKER': 'CRITICAL',
        'MAJOR': 'HIGH', 
        'MINOR': 'LOW',
        'INFO': 'LOW',
    }
    if sev in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        return sev
    return mapping.get(sev, 'MEDIUM')
And fix the assessment field mapping where you build the final update:



# In run_review(), where you read assessment data:

assessment = ai_result.get('assessment', {})

# FIX: Handle both possible field names from parser
risk_level = (assessment.get('overallRisk') or 
              assessment.get('riskLevel') or 
              assessment.get('risk_level') or 'UNKNOWN')              # FIXED

recommendation = (assessment.get('recommendation') or '')

summary_text = (assessment.get('summary') or '')
if isinstance(summary_text, (dict, list)):
    summary_text = json.dumps(summary_text)

# Then use these variables in the UPDATE:
db.update(
    """UPDATE reviews SET
        ...
        ai_risk_level = %s, ai_recommendation = %s, ai_summary = %s,
        ...""",
    (
        ...
        risk_level,          # FIXED: was assessment.get('overallRisk', 'UNKNOWN')
        recommendation,      # FIXED
        summary_text,         # FIXED
        ...
    )
)
Diagnostic Query — Run This First
Before making any code changes, run this to understand what is actually happening:

SQL

-- 1. What did Gemini actually return?
SELECT id, 
       LENGTH(gemini_raw_output) as raw_length,
       CASE WHEN gemini_raw_output LIKE '%ASSESSMENT_START%' THEN 'YES' ELSE 'NO' END as has_assessment,
       CASE WHEN gemini_raw_output LIKE '%FINDING_START%' THEN 'YES' ELSE 'NO' END as has_findings,
       CASE WHEN gemini_raw_output LIKE '%VALIDATION_START%' THEN 'YES' ELSE 'NO' END as has_validations,
       CASE WHEN gemini_raw_output LIKE '%SUGGESTIONS_START%' THEN 'YES' ELSE 'NO' END as has_suggestions,
       LEFT(gemini_raw_output, 300) as response_start,
       ai_summary,
       ai_risk_level
FROM reviews 
WHERE status = 'complete' 
ORDER BY id DESC LIMIT 5;

-- 2. Were findings stored?
SELECT r.id as review_id, 
       COUNT(f.id) as finding_count,
       GROUP_CONCAT(DISTINCT f.source) as sources
FROM reviews r 
LEFT JOIN findings f ON f.review_id = r.id
WHERE r.status = 'complete'
GROUP BY r.id
ORDER BY r.id DESC LIMIT 5;

-- 3. What does the parsed JSON look like?
SELECT id,
       JSON_LENGTH(gemini_parsed_json, '$.assessment') as assessment_keys,
       JSON_LENGTH(gemini_parsed_json, '$.sonarValidation') as validation_count,
       JSON_LENGTH(gemini_parsed_json, '$.logicalFindings') as finding_count,
       JSON_LENGTH(gemini_parsed_json, '$.suggestions') as suggestion_count
FROM reviews 
WHERE status = 'complete' AND gemini_parsed_json IS NOT NULL
ORDER BY id DESC LIMIT 5;
This will tell you exactly where the pipeline breaks:


SCENARIO A: raw_length is 0 or very small
  → Bug #1: Prompt never reached Gemini (CLI argument too long)
  → Fix: Write prompt to file

SCENARIO B: raw_length is large BUT has_assessment = NO
  → Bug #2: CLI output has noise, markers not found
  → Fix: Clean CLI output before parsing

SCENARIO C: has_assessment = YES but ai_summary is blank
  → Bug #3: Parser found markers but field mapping is wrong
  → Fix: Align field names between parser and storage

SCENARIO D: has_assessment = YES, ai_summary has content, 
            but finding_count = 0
  → Parser is extracting assessment but not findings
  → Check parse_gemini_output() for FINDING/VALIDATION extraction
Additional Issues Found in Code Review
These are not causing the blank output but are real bugs or risks:

Issue 4: _update_status Bypasses Optimistic Locking
You implemented _safe_update_status with version checking but then bypass it for most status changes:



# SAFE (used once for pending → cloning):
self._safe_update_status(review_id, 'pending', 'cloning', version, 'Cloning...')

# UNSAFE (used for everything else):
self._update_status(review_id, 'analyzing', 'Neural Audit Pipeline Active...')
# ↑ This does NOT check version or expected status


def _update_status(self, review_id, status, message=''):
    # This just overwrites — no safety
    db.update("UPDATE reviews SET status = %s WHERE id = %s", (status, review_id))
Fix — use safe updates consistently:



def _update_status(self, review_id, status, message=''):
    """Update review status with version increment for consistency."""
    db.update(
        "UPDATE reviews SET status = %s, version = version + 1 WHERE id = %s", 
        (status, review_id)
    )
    if message:
        self._log(review_id, status.upper(), 'started', message, 0)
Issue 5: _get_unified_diff Fails Silently on First Commit


def _get_unified_diff(self, work_dir, sonar_findings):
    res = subprocess.run(
        ['git', 'diff', 'HEAD^', 'HEAD'],   # ← HEAD^ fails if there is only one commit
        cwd=work_dir, capture_output=True, text=True
    )
    diff = res.stdout    # ← Empty string on failure, not checked
If the branch has only one commit (initial commit), HEAD^ does not exist. The command fails silently, res.stdout is empty, and Gemini gets no code to review.



def _get_unified_diff(self, work_dir, sonar_findings):
    """Fetch unified diff with fallback for single-commit branches."""
    try:
        # Try normal diff first
        res = subprocess.run(
            ['git', 'diff', 'HEAD^', 'HEAD'], 
            cwd=work_dir, capture_output=True, text=True
        )
        diff = res.stdout
        
        # Fallback: if HEAD^ doesn't exist (first commit), diff against empty tree
        if not diff.strip():
            # Check if HEAD^ exists
            check = subprocess.run(
                ['git', 'rev-parse', 'HEAD^'], 
                cwd=work_dir, capture_output=True, text=True
            )
            if check.returncode != 0:
                # First commit — diff against empty tree
                empty_tree = '4b825dc642cb6eb9a060e54bf899d15363' \
                             '1bdd52'  # Git's empty tree hash
                res = subprocess.run(
                    ['git', 'diff', empty_tree, 'HEAD'],
                    cwd=work_dir, capture_output=True, text=True
                )
                diff = res.stdout
                print(f"      [ReviewRunner] Used empty-tree diff (first commit)")
        
        if not diff.strip():                                                 # FIXED
            print(f"      [ReviewRunner] WARNING: Git diff is empty")
            return "No diff available — this may be a merge commit or empty change."
        
        # Token budget check
        estimated_tokens = len(diff) // 4
        MAX_DIFF_TOKENS = 40000
        
        if estimated_tokens > MAX_DIFF_TOKENS:
            print(f"      [ReviewRunner] Diff exceeds budget ({estimated_tokens} tokens). Truncating...")
            diff = self._truncate_diff_by_priority(diff, MAX_DIFF_TOKENS, sonar_findings)
        
        return diff
        
    except Exception as e:
        print(f"      [ReviewRunner] Error fetching diff: {e}")
        return f"Error fetching git diff: {str(e)}"
Issue 6: Missing except Body in Standards Loading


# YOUR CODE:
if os.path.exists(Config.STANDARDS_FILE):
    try:
        with open(Config.STANDARDS_FILE, 'r') as f:
            standards_text = f.read()
    except: pass    # ← Bare except with pass — you'll never know if this fails


# FIXED:
if os.path.exists(Config.STANDARDS_FILE):
    try:
        with open(Config.STANDARDS_FILE, 'r', encoding='utf-8') as f:
            standards_text = f.read()
    except Exception as e:
        print(f"      [ReviewRunner] Warning: Could not read standards file: {e}")
        standards_text = ""
Issue 7: SonarQube File Path Mismatch in Truncation
Your truncation compares SonarQube file paths against diff file paths, but they use different formats:



# SonarQube path (from _filter_issues):
file_path = i.get('component', '').split(':')[-1]
# Result: "src/main/java/com/example/App.java"

# Diff path (from _truncate_diff_by_priority):
match = re.search(r'b/(.+)$', line)
# Result: "src/main/java/com/example/App.java"  ← Usually matches

# BUT SonarQube sometimes returns:
# "my-project:src/main/java/com/example/App.java"
# After split(':'): "src/main/java/com/example/App.java" ← OK

# Or with module keys:
# "my-project:my-module:src/main/java/com/example/App.java"  
# After split(':')[-1]: "src/main/java/com/example/App.java" ← OK

# EDGE CASE: SonarQube returns just the filename without path
# "App.java"
# This will NEVER match "src/main/java/com/example/App.java" in the diff


def _truncate_diff_by_priority(self, full_diff, max_tokens, sonar_findings):
    # ... existing file splitting code ...
    
    # FIXED: Build a set that matches on both full path and filename
    sonar_files = set()
    for f in (sonar_findings or []):
        file_path = f.get('file', '')
        sonar_files.add(file_path)                    # Full path
        sonar_files.add(os.path.basename(file_path))  # Just filename  # FIXED
    
    # FIXED: Check if diff filename matches ANY sonar file pattern
    def has_sonar_finding(diff_filename):
        if diff_filename in sonar_files:
            return True
        if os.path.basename(diff_filename) in sonar_files:
            return True
        return False
    
    prioritized = sorted(file_diffs, key=lambda d: (
        0 if has_sonar_finding(d['filename']) else 1,   # FIXED
        -d['size']
    ))
    
    # ... rest unchanged ...
Summary — Fix Order


STEP 1: Run the diagnostic SQL query
        → Tells you exactly which bug is causing blank output

STEP 2: Fix Bug #1 (prompt via file, not CLI argument)
        → This is most likely the primary cause

STEP 3: Fix Bug #2 (clean CLI output before parsing)
        → Handles noise around the actual response

STEP 4: Fix Bug #3 (field name alignment)
        → Ensures parsed data reaches the database correctly

STEP 5: Add the diagnostic logging in _run_gemini_review_v2
        → So you can see exactly what is happening on every run

STEP 6: Fix Issues 4-7 (secondary bugs)
        → Prevents future problems
Run the diagnostic query first — it will tell you immediately where the break is and which fix to prioritize.