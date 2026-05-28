"""
Review Runner — Orchestrates the complete review pipeline.
Runs in a background thread, updates database as it progresses.
"""

import re
import os
import json
import time
import shutil
import subprocess
import traceback
from datetime import datetime
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

import requests
import google.generativeai as genai

from config import Config
from engine import db
from engine.git_manager import GitManager


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, name, failure_threshold=3, recovery_timeout=60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"

    def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                print(f"      [CircuitBreaker] {self.name} is HALF_OPEN, testing recovery...")
            else:
                raise CircuitOpenError(f"Circuit breaker {self.name} is OPEN")

        try:
            result = func(*args, **kwargs)
            self.failure_count = 0
            self.state = "CLOSED"
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                print(f"      [CircuitBreaker] {self.name} tripped to OPEN state!")
            raise e


class ReviewRunner:
    
    def __init__(self):
        self.git = GitManager()
        self.gemini_breaker = CircuitBreaker("GeminiAPI")
    
    def _safe_update_status(self, review_id, expected_status, new_status, version, message=''):
        """Optimistic locking update for status transitions."""
        affected = db.update(
            "UPDATE reviews SET status = %s, version = version + 1 WHERE id = %s AND status = %s AND version = %s",
            (new_status, review_id, expected_status, version)
        )
        if affected > 0:
            if message:
                self._log(review_id, new_status.upper(), 'started', message, 0)
            return True
        return False

    def run_review(self, review_id):
        """Run the complete review pipeline with parallelism and safety."""
        
        start_time = time.time()
        work_dir = os.path.join(Config.WORKSPACE_DIR, f"review_{review_id}")
        
        try:
            # ── Initial State Check ──
            review_rows = db.execute("SELECT * FROM reviews WHERE id = %s", (review_id,))
            if not review_rows:
                return
            review = review_rows[0]
            version = review['version']
            
            repo = self.git.get_repo(review['repo_id'])
            if not repo:
                raise Exception("Repo not found")
            
            # ── STEP 1: Clone (Optimistic Lock) ──
            if not self._safe_update_status(review_id, 'pending', 'cloning', version, 'Cloning repository...'):
                print(f"      [ReviewRunner] Review {review_id} already being processed or state changed.")
                return
            
            version += 1 # We successfully updated, increment local version tracker
            
            clone_start = time.time()
            def clone_log(msg):
                self._log(review_id, 'clone_stream', 'started', msg, 0)
                
            clone_result = self.git.clone_repo(review['repo_id'], review['branch'], work_dir, log_callback=clone_log)
            self._log(review_id, 'clone', 'completed',
                     f"Cloned {repo['name']}@{review['branch']} ({clone_result['commit_sha'][:7]})",
                     int((time.time() - clone_start) * 1000))
            
            commit_sha = clone_result['commit_sha']
            db.update("UPDATE reviews SET commit_sha = %s WHERE id = %s", (commit_sha, review_id))
            
            # Phase 1: Duplicate Detection (Check for existing completed review)
            existing_review = db.execute(
                "SELECT * FROM reviews WHERE repo_id = %s AND commit_sha = %s AND status = 'complete' AND id != %s ORDER BY completed_at DESC LIMIT 1",
                (review['repo_id'], commit_sha, review_id)
            )
            
            if existing_review:
                ex = existing_review[0]
                self._log(review_id, 'duplicate_check', 'completed', 
                         f"Existing intelligence found for commit {commit_sha[:7]}. Fast-tracking results.", 0)
                
                # Carry forward results to the current record
                db.update(
                    """UPDATE reviews SET 
                        status = 'complete', ai_summary = %s, ai_risk_level = %s, 
                        quality_score = %s, total_real_issues = %s, report_html_path = %s,
                        completed_at = NOW() 
                       WHERE id = %s""",
                    (ex['ai_summary'], ex['ai_risk_level'], ex['quality_score'], ex['total_real_issues'], ex['report_html_path'], review_id)
                )
                
                # Also link findings (optional but recommended for drill-down)
                db.execute(
                    "INSERT INTO findings (review_id, source, ai_verdict, title, category, severity, file_path, line_start, explanation) "
                    "SELECT %s, source, ai_verdict, title, category, severity, file_path, line_start, explanation "
                    "FROM findings WHERE review_id = %s", (review_id, ex['id']), fetch=False
                )
                return

            # ── Phase 2: Execution Pipeline (Sequential & Resilient) ──
            self._update_status(review_id, 'analyzing', 'Neural Audit Pipeline Active...')
            
            # 2.1 Project Structure Mapping (Mandatory for AI context)
            project_structure = self._get_project_structure(work_dir)
            self._log(review_id, 'structure_mapping', 'completed', "Directory tree mapped for AI navigation.", 0)

            # 2.2 SonarQube Lifecycle (Scan -> Wait -> Fetch)
            sonar_results, filtered = {}, {'issues': []}
            try:
                self._log(review_id, 'sonar_scan', 'started', "Triggering SonarQube static scan...", 0)
                self._run_sonar_scan(review_id, repo, work_dir)
                
                self._log(review_id, 'sonar_wait', 'started', "Waiting for SonarQube background processing...", 0)
                self._wait_for_sonar_analysis(review_id, repo, work_dir)
                
                self._log(review_id, 'sonar_fetch', 'started', "Fetching final issue report...", 0)
                sonar_results = self._fetch_sonar_results(review_id, repo)
                filtered = self._filter_issues(review_id, sonar_results)
            except Exception as e:
                print(f"      [ReviewRunner] SonarQube Lifecycle Failed: {e}")
                self._log(review_id, 'sonar_warning', 'started', 
                         "SonarQube failed, proceeding with AI-only logic review.", 0)
            
            # 2.3 Gemini Neural Audit
            ai_result = self._run_gemini_pipeline(review_id, repo, work_dir, 
                                                 sonar_findings=filtered.get('issues', []),
                                                 structure=project_structure)

            # ── STEP 3: Final Aggregation ──
            self._update_status(review_id, 'generating_report', 'Merging findings and generating report...')
            
            # Store Findings
            self._store_findings(review_id, ai_result)
            
            # Generate Report
            report_path = self._generate_report(review_id, repo, sonar_results, filtered, ai_result)
            
            # ── Complete ──
            total_duration = int(time.time() - start_time)
            
            assessment = ai_result.get('assessment', {})
            sonar_val = ai_result.get('sonarValidation', [])
            findings = ai_result.get('logicalFindings', [])
            
            confirmed = len([v for v in sonar_val if v.get('verdict') == 'CONFIRMED'])
            false_pos = len([v for v in sonar_val if v.get('verdict') == 'FALSE_POSITIVE'])
            escalated = len([v for v in sonar_val if v.get('verdict') == 'ESCALATED'])
            total_real = confirmed + escalated + len(findings)
            
            summary_text = assessment.get('summary', '')
            if isinstance(summary_text, (dict, list)):
                summary_text = json.dumps(summary_text)
            
            # Robust mapping for assessment fields
            risk_level = (assessment.get('overallRisk') or 
                          assessment.get('riskLevel') or 
                          assessment.get('risk_level') or 'UNKNOWN').upper()
            
            recommendation = (assessment.get('recommendation') or '')
            
            # Append suggestions to summary for visibility
            suggestions = ai_result.get('suggestions', [])
            if suggestions:
                summary_text += "\n\n### Suggestions:\n- " + "\n- ".join([str(s) for s in suggestions])
            
            risk_predictions_json = json.dumps(ai_result.get('riskPredictions', {}))
            parsed_json_str = json.dumps(ai_result)
            
            # Quality Score Calculation (Deterministic + Semantic)
            final_score, score_details = self._calculate_quality_score(review, ai_result, total_real)

            db.update(
                """UPDATE reviews SET
                    status = 'complete',
                    ai_confirmed = %s, ai_false_positives = %s, ai_escalated = %s,
                    ai_logical_findings = %s,
                    ai_risk_level = %s, ai_recommendation = %s, ai_summary = %s,
                    total_real_issues = %s,
                    duration_seconds = %s, 
                    report_html_path = %s,
                    ai_risk_predictions = %s,
                    gemini_parsed_json = %s,
                    quality_score = %s,
                    score_sonar_issues = %s, score_ai_severity = %s, score_test_coverage = %s,
                    score_commit_msg = %s, score_complexity = %s, score_standards = %s,
                    score_documentation = %s, score_details_json = %s,
                    completed_at = NOW(),
                    version = version + 1
                WHERE id = %s""",
                (
                    confirmed, false_pos, escalated, len(findings),
                    risk_level, recommendation, summary_text,
                    total_real,
                    total_duration,
                    report_path,
                    risk_predictions_json,
                    parsed_json_str,
                    final_score,
                    score_details['sonar_issues'], score_details['ai_severity'], score_details['test_coverage'],
                    score_details['commit_msg'], score_details['complexity'], score_details['standards'],
                    score_details['documentation'], json.dumps(score_details),
                    review_id
                )
            )
            
            self._log(review_id, 'complete', 'completed',
                     f"Review complete: {total_real} issues, {assessment.get('overallRisk','?')} risk, {total_duration}s total",
                     total_duration * 1000)
            
        except Exception as e:
            error_msg = str(e)
            tb = traceback.format_exc()
            print(f"      [ReviewRunner] CRITICAL ERROR: {error_msg}\n{tb}")
            
            db.update(
                "UPDATE reviews SET status = 'failed', error_message = %s, completed_at = NOW(), version = version + 1 WHERE id = %s",
                (f"{error_msg}\n\n{tb}"[:5000], review_id)
            )
            self._log(review_id, 'error', 'failed', error_msg[:1000], 0)
            
        finally:
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)

    def _run_sonar_pipeline(self, review_id, repo, work_dir):
        """Sequential SonarQube steps run in a thread."""
        self._log(review_id, 'sonar_scan', 'started', "Starting SonarQube static analysis...", 0)
        self._run_sonar_scan(review_id, repo, work_dir)
        
        self._log(review_id, 'sonar_wait', 'started', "Waiting for SonarQube server to finalize background tasks...", 0)
        self._wait_for_sonar_analysis(review_id, repo, work_dir)
        
        self._log(review_id, 'sonar_fetch', 'started', "Fetching SonarQube issue report...", 0)
        sonar_results = self._fetch_sonar_results(review_id, repo)
        
        self._log(review_id, 'sonar_filter', 'started', "Prioritizing SonarQube findings for AI validation...", 0)
        filtered = self._filter_issues(review_id, sonar_results)
        return sonar_results, filtered

    def _run_gemini_pipeline(self, review_id, repo, work_dir, sonar_findings=None, structure=None):
        """Gemini analysis run in a thread."""
        self._log(review_id, 'gemini_init', 'started', "Initializing Neural Audit Engine...", 0)

        # 1. Identify changed files via git with optimized fallback
        try:
            res_check = subprocess.run(['git', 'rev-parse', 'HEAD^'], cwd=work_dir, capture_output=True)
            if res_check.returncode == 0:
                res = subprocess.run(['git', 'diff', '--name-only', 'HEAD^', 'HEAD'],
                                     cwd=work_dir, capture_output=True, text=True)
            else:
                # Optimized: ls-tree can be massive, so we'll process it carefully
                res = subprocess.run(['git', 'ls-tree', '-r', 'HEAD', '--name-only'],
                                     cwd=work_dir, capture_output=True, text=True)
            
            all_files = res.stdout.strip().split('\n')
        except Exception as e:
            print(f"      [ReviewRunner] Git identification failed: {e}")
            all_files = []

        # 2. Filter for relevant source files FIRST (Massive performance gain for large repos)
        source_exts = ('.py', '.js', '.ts', '.go', '.java', '.c', '.cpp', '.h', '.cs', '.php', '.rb')
        relevant_files = [f.strip() for f in all_files if f.strip() and f.lower().endswith(source_exts)]
        
        # 3. Only check existence for the filtered subset
        relevant_files = [f for f in relevant_files if os.path.exists(os.path.join(work_dir, f))]

        # 4. Optimized Directory Scanning Fallback
        if not relevant_files:
            self._log(review_id, 'gemini_info', 'started', "No relevant source files found in diff. Scanning directory structure...", 0)
            
            # Use a more efficient walk that prunes common large directories
            skip_dirs = {'.git', 'node_modules', 'vendor', '__pycache__', 'dist', 'build', 'target', '.venv', 'venv'}
            
            for root, dirs, files in os.walk(work_dir):
                # Prune directories in-place to prevent os.walk from entering them
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                
                for f in files:
                    if f.lower().endswith(source_exts):
                        relevant_files.append(os.path.relpath(os.path.join(root, f), work_dir))
                        if len(relevant_files) >= 10: break # Increased slightly for better context
                if len(relevant_files) >= 10: break

        self._log(review_id, 'gemini_plan', 'started', f"Neural audit planned for {len(relevant_files[:20])} files.", 0)
        return self._run_gemini_review_v2(review_id, relevant_files, work_dir, repo=repo, sonar_findings=sonar_findings, project_structure=structure)

    def _detect_languages(self, files_affected: List[str]) -> List[str]:

        """Maps file extensions to supported standard languages."""
        ext_map = {
            '.go': 'go',
            '.java': 'java',
            '.js': 'javascript', '.ts': 'typescript', '.jsx': 'javascript', '.tsx': 'typescript',
            '.php': 'php',
            '.sql': 'sql'
        }
        detected = set()
        for f in files_affected:
            ext = os.path.splitext(f)[1].lower()
            if ext in ext_map:
                detected.add(ext_map[ext])
        return list(detected)

    def _get_dynamic_standards(self, detected_langs: List[str], files_affected: List[str]) -> str:
        """Assembles a hierarchical standards document with explicit precedence."""
        standards_parts = [
            "### STANDARDS PRECEDENCE RULES ###",
            "1. UNIVERSAL STANDARDS: Absolute authority on Security and Logging.",
            "2. PROJECT OVERRIDES: Specific rules for this repository (Wins over Language).",
            "3. LANGUAGE STANDARDS: Framework-specific best practices.",
            "If rules conflict, higher priority (lower number) ALWAYS wins."
        ]
        
        # 1. Layer 1: Universal Base
        universal_path = os.path.join(Config.STANDARDS_DIR, "universal_standards.md")
        if os.path.exists(universal_path):
            with open(universal_path, 'r') as f:
                standards_parts.append(f"### [PRIORITY 1] UNIVERSAL STANDARDS ###\n{f.read()}")
        
        # 2. Layer 2: Project Master Override
        if os.path.exists(Config.STANDARDS_FILE):
            with open(Config.STANDARDS_FILE, 'r') as f:
                standards_parts.append(f"### [PRIORITY 2] PROJECT-SPECIFIC OVERRIDES ###\n{f.read()}")

        # 3. Layer 3: Language Standards
        lang_map = {
            'go': 'go_standards.md',
            'java': 'java_standards.md',
            'javascript': 'node_standards.md',
            'typescript': 'node_standards.md',
            'php': 'php_standards.md',
            'sql': 'sql_standards.md'
        }
        
        for lang in detected_langs:
            lang_file = lang_map.get(lang)
            if lang_file:
                lang_path = os.path.join(Config.STANDARDS_DIR, lang_file)
                if os.path.exists(lang_path):
                    with open(lang_path, 'r') as f:
                        standards_parts.append(f"### [PRIORITY 3] {lang.upper()} STANDARDS ###\n{f.read()}")

        return "\n\n" + "\n\n".join(standards_parts)

    def _run_gemini_review_v2(self, review_id, files_affected, work_dir, repo=None, sonar_findings=None, project_structure=None):
        """Single-call Gemini review with enhanced context and Phase 1-3 validation."""
        # Phase 1: Active Language Detection
        detected_langs = self._detect_languages(files_affected)
        repo_lang = (repo.get('language') or 'Unknown').lower()
        if repo_lang not in detected_langs and repo_lang != 'unknown':
            detected_langs.append(repo_lang)

        # Phase 1: Dynamic Standards Assembly
        standards_text = self._get_dynamic_standards(detected_langs, files_affected)
        
        if not standards_text or "UNIVERSAL STANDARDS" not in standards_text:
            msg = f"Critical Failure: Mandatory Universal Standards missing. Aborting."
            self._log(review_id, 'gemini_abort', 'failed', msg, 0)
            raise Exception(msg)

        self._log(review_id, 'gemini_context', 'started', 
                 f"Context: {len(files_affected)} files, {detected_langs} languages detected.", 0)

        if not project_structure:
            project_structure = self._get_project_structure(work_dir)
            
        full_diff = self._get_unified_diff(work_dir, sonar_findings)
        critical_source = self._get_critical_file_sources(work_dir, sonar_findings, files_affected)

        # Phase 2: Validated Prompt Build with Auto-Truncation
        try:
            prompt = self._build_prompt(
                git_diff=f"{critical_source}\n\n--- UNIFIED DIFF OF CHANGES ---\n{full_diff}",
                sonar_findings=sonar_findings or [],
                project_structure=project_structure,
                language=", ".join(detected_langs),
                coding_standards=standards_text
            )
        except ValueError as e:
            if "Token count" in str(e):
                self._log(review_id, 'prompt_truncation', 'started', "Prompt too large, retrying with minimal diff context...", 0)
                # Retry with NO critical source and 50% truncated diff
                truncated_diff = full_diff[:len(full_diff)//2] + "\n... [EMERGENCY TRUNCATION]"
                prompt = self._build_prompt(
                    git_diff=f"--- TRUNCATED DIFF ---\n{truncated_diff}",
                    sonar_findings=sonar_findings or [],
                    project_structure=project_structure,
                    language=", ".join(detected_langs),
                    coding_standards=standards_text
                )
            else: raise e
        
        self._log(review_id, 'gemini_audit', 'started', "Executing comprehensive neural audit with enhanced context...", 0)

        try:
            # Phase 3: AI Execution with Retry Loop (Internal to _call_gemini_cli)
            raw_response = self._call_gemini_cli(prompt, work_dir)
            
            cleaned_response = self._clean_cli_output(raw_response)
            db.update("UPDATE reviews SET gemini_raw_output = %s WHERE id = %s", (raw_response, review_id))
            
            from engine.parse_output import parse_gemini_output
            parsed_result = parse_gemini_output(cleaned_response)
            
            # Phase 4: Parse Validation & Resilience
            assessment = parsed_result.get('assessment', {})
            findings = parsed_result.get('logicalFindings', [])
            validations = parsed_result.get('sonarValidation', [])

            # Check for empty/malformed response
            if not assessment.get('summary') and not findings and not validations:
                self._log(review_id, 'parse_failure', 'failed', "AI response contains no structured findings or assessment.", 0)
                # Fallback to snippet for summary if everything else failed
                snippet = cleaned_response.strip()[:1000]
                if not snippet: snippet = "[Empty Response from AI]"
                assessment['summary'] = f"[PARSING FAILED - RAW OUTPUT SNIPPET]\n\n{snippet}"
                parsed_result['assessment'] = assessment

            return {
                "sonarValidation": validations, 
                "logicalFindings": findings,
                "suggestions": parsed_result.get('suggestions', []),
                "assessment": assessment,
                "riskPredictions": parsed_result.get('riskPredictions', {}),
                "commitQuality": parsed_result.get('commitQuality', {"messageScore": 5, "standardsScore": 5, "documentationScore": 5})
            }
            
        except Exception as e:
            self._log(review_id, 'gemini_error', 'failed', f"Neural audit failed after retries: {str(e)[:500]}", 0)
            raise e

    def _empty_ai_result(self):
        return {
            "sonarValidation": [], "logicalFindings": [], "suggestions": [],
            "assessment": {"overallRisk": "UNKNOWN", "recommendation": "ERROR"},
            "riskPredictions": {"predictions": []},
            "commitQuality": {"messageScore": 5, "standardsScore": 5, "documentationScore": 5}
        }

    def _get_unified_diff(self, work_dir, sonar_findings):
        """Fetch unified diff with fallback and increased context lines."""
        try:
            # Increase context lines (-U10) to give Gemini more surrounding logic
            res = subprocess.run(['git', 'diff', '-U10', 'HEAD^', 'HEAD'], cwd=work_dir, capture_output=True, text=True)
            diff = res.stdout
            
            # Fallback: if HEAD^ doesn't exist (first commit), diff against empty tree
            if not diff or not diff.strip():
                check = subprocess.run(['git', 'rev-parse', 'HEAD^'], cwd=work_dir, capture_output=True)
                if check.returncode != 0:
                    # Use git hash-object to get the universal empty tree hash
                    empty_tree = '4b825dc642cb6eb9a060e54bf899d153631bdd52'
                    res = subprocess.run(['git', 'diff', '-U10', empty_tree, 'HEAD'], cwd=work_dir, capture_output=True, text=True)
                    diff = res.stdout
                    if diff and diff.strip():
                        print(f"      [ReviewRunner] Used empty-tree diff (first commit)")
            
            # Final Fallback: If still empty, it might be a shallow clone or single commit repo
            # Show all files at HEAD as "added"
            if not diff or not diff.strip():
                print(f"      [ReviewRunner] WARNING: Standard git diff is empty. Falling back to full file listing.")
                res = subprocess.run(['git', 'ls-files'], cwd=work_dir, capture_output=True, text=True)
                files = res.stdout.strip().split('\n')
                full_content = []
                for f in files[:10]: # Limit to first 10 files to avoid token blowout
                    if os.path.exists(os.path.join(work_dir, f)):
                        try:
                            with open(os.path.join(work_dir, f), 'r', errors='ignore') as fcontent:
                                full_content.append(f"--- /dev/null\n+++ b/{f}\n@@ -0,0 +1,1 @@\n" + fcontent.read())
                        except: pass
                diff = "\n".join(full_content)

            if not diff or not diff.strip():
                return "No diff available — repository might be empty or in an unusual state."

            # Simple token estimation: 4 characters per token
            estimated_tokens = len(diff) // 4
            MAX_DIFF_TOKENS = 60000 # Increased budget for Gemini 1.5 Pro
            
            if estimated_tokens > MAX_DIFF_TOKENS:
                print(f"      [ReviewRunner] Diff exceeds budget ({estimated_tokens} tokens). Truncating...")
                diff = self._truncate_diff_by_priority(diff, MAX_DIFF_TOKENS, sonar_findings)
            
            return diff
        except Exception as e:
            print(f"      [ReviewRunner] Error fetching diff: {e}")
            return f"Error fetching git diff: {str(e)}"

    def _get_critical_file_sources(self, work_dir, sonar_findings, files_affected):
        """Retrieve full source code for the top 5 most important files."""
        # Prioritize files with Sonar findings
        sonar_files = []
        if sonar_findings:
            # Count findings per file
            counts = {}
            for f in sonar_findings:
                p = f.get('file', '')
                counts[p] = counts.get(p, 0) + 1
            sorted_sonar = sorted(counts.items(), key=lambda x: x[1], reverse=True)
            sonar_files = [x[0] for x in sorted_sonar]

        # Top candidates
        top_files = (sonar_files + [f for f in files_affected if f not in sonar_files])[:5]
        
        sources = ["### FULL SOURCE FOR CRITICAL FILES (CONTEXT ONLY) ###"]
        for file_path in top_files:
            full_path = os.path.join(work_dir, file_path)
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        # Cap large files at 10k chars to avoid token blowout
                        if len(content) > 15000:
                            content = content[:15000] + "\n... [TRUNCATED]"
                        sources.append(f"FILE: {file_path}\n<SOURCE_CODE_START>\n{content}\n<SOURCE_CODE_END>")
                except: pass
        
        return "\n\n".join(sources) if len(sources) > 1 else ""

    def _truncate_diff_by_priority(self, full_diff, max_tokens, sonar_findings):
        """Prioritize files with SonarQube findings, then by lines changed."""
        if not full_diff:
            return ""

        # Split diff into per-file chunks efficiently
        file_diffs = []
        current_file = None
        current_content = []
        
        # Use splitlines(keepends=True) to avoid re-joining with \n later for each chunk
        for line in full_diff.splitlines(keepends=True):
            if line.startswith('diff --git'):
                if current_file:
                    content_str = "".join(current_content)
                    file_diffs.append({
                        'filename': current_file, 
                        'content': content_str, 
                        'size': len(content_str)
                    })
                # Extract filename
                match = re.search(r'b/(.+)$', line)
                current_file = match.group(1) if match else "unknown"
                current_content = [line]
            else:
                current_content.append(line)
        
        if current_file:
            content_str = "".join(current_content)
            file_diffs.append({
                'filename': current_file, 
                'content': content_str, 
                'size': len(content_str)
            })

        if not file_diffs:
            return full_diff[:max_tokens * 4]

        # Build a robust set of sonar files (full path and just filename)
        sonar_files = set()
        for f in (sonar_findings or []):
            path = f.get('file', '')
            sonar_files.add(path)
            sonar_files.add(os.path.basename(path))
        
        def has_sonar_finding(diff_filename):
            if diff_filename in sonar_files: return True
            if os.path.basename(diff_filename) in sonar_files: return True
            return False

        # Sort: Sonar files first, then by size descending
        prioritized = sorted(file_diffs, key=lambda d: (
            0 if has_sonar_finding(d['filename']) else 1,
            -d['size']
        ))
        
        result = []
        token_count = 0
        for fd in prioritized:
            file_tokens = fd['size'] // 4
            if token_count + file_tokens > max_tokens:
                result.append(f"\n[TRUNCATED: {len(prioritized) - len(result)} files omitted due to size limits]\n")
                break
            result.append(fd['content'])
            token_count += file_tokens
            
        return "".join(result)

    def _calculate_quality_score(self, review, ai_result, total_real):
        cq = ai_result.get('commitQuality', {})
        assessment = ai_result.get('assessment', {})
        
        # 1. Sonar Issues (25%)
        sonar_score_val = max(0, 10 - (review.get('sonar_criticals', 0) + review.get('sonar_majors', 0)))
        
        # 2. AI Severity (25%)
        ai_risk_map = {'CRITICAL': 2, 'HIGH': 5, 'MEDIUM': 8, 'LOW': 10, 'UNKNOWN': 7}
        ai_sev_score = ai_risk_map.get(assessment.get('overallRisk', 'UNKNOWN'), 7)
        
        # 3. Test Coverage (15%)
        cov = float(review.get('sonar_coverage') or 0)
        cov_score = min(10, (cov / 80.0) * 10)
        
        # 4. Commit Message (10%)
        msg_score = cq.get('messageScore', 5)
        
        # 5. Complexity (10%) - Deterministic Improvement (Issue #7)
        # Calculate based on files changed and logic lines if available
        complexity_score = max(0, 10 - (review.get('files_affected', 0) // 2))
        
        # 6. Standards (10%)
        std_score = cq.get('standardsScore', 5)
        
        # 7. Documentation (5%)
        doc_score = cq.get('documentationScore', 5)
        
        final_score = (
            (sonar_score_val * 0.25) +
            (ai_sev_score * 0.25) +
            (cov_score * 0.15) +
            (msg_score * 0.10) +
            (complexity_score * 0.10) +
            (std_score * 0.10) +
            (doc_score * 0.05)
        )
        
        score_details = {
            "sonar_issues": sonar_score_val,
            "ai_severity": ai_sev_score,
            "test_coverage": int(cov_score),
            "commit_msg": msg_score,
            "complexity": complexity_score,
            "standards": std_score,
            "documentation": doc_score
        }
        return final_score, score_details

    def _update_status(self, review_id, status, message=''):
        """Update review status with version increment for consistency."""
        db.update("UPDATE reviews SET status = %s, version = version + 1 WHERE id = %s", (status, review_id))
        if message:
            self._log(review_id, status.upper(), 'started', message, 0)

    def _build_prompt(self, **kwargs) -> str:
        """Load, inject, and validate prompt template."""
        
        prompt_path = Config.PROMPT_FILE
        if not os.path.exists(prompt_path):
            raise FileNotFoundError(f"Prompt template missing at {prompt_path}")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        mapping = {
            'git_diff': '{{GIT_DIFF}}',
            'sonar_findings': '{{SONARQUBE_FINDINGS}}',
            'project_structure': '{{PROJECT_STRUCTURE}}',
            'language': '{{LANGUAGE}}',
            'coding_standards': '{{CODING_STANDARDS}}'
        }

        for key, value in kwargs.items():
            placeholder = mapping.get(key, '{{' + key.upper() + '}}')
            if isinstance(value, (list, dict)):
                value = json.dumps(value, indent=2)
            
            # Validation: Ensure critical context isn't empty (except Sonar which is optional)
            if key != 'sonar_findings' and not str(value or '').strip():
                print(f"      [ReviewRunner] Warning: Critical context '{key}' is empty during prompt build.")
            
            # CRITICAL FIX: Avoid infinite loop by using a single replace call
            # This handles cases where the replacement value itself contains the placeholder
            val_str = str(value or '')
            template = template.replace(placeholder, val_str)
        
        # Phase 2 Validation: Check for unresolved placeholders
        remaining = re.findall(r'\{\{[A-Z_]+\}\}', template)
        critical_remaining = [r for r in remaining if r not in ['{{VARIABLE}}', '{{SONARQUBE_FINDINGS}}']]
        
        if critical_remaining:
            # Check if any of these were actually replaced but reappeared (unlikely with single replace)
            # or if they were missing from kwargs.
            raise ValueError(f"Prompt validation failed: Unresolved placeholders {critical_remaining}")

        # Phase 2 Validation: Token Budget Guard
        estimated_tokens = len(template) // 4
        MAX_ALLOWED_TOKENS = 150000 
        
        if estimated_tokens > MAX_ALLOWED_TOKENS:
            raise ValueError(f"Prompt validation failed: Token count {estimated_tokens} exceeds limit {MAX_ALLOWED_TOKENS}")

        return template

    def _get_project_structure(self, work_dir):
        """Generates a text representation of the project structure."""
        try:
            res = subprocess.run(['find', '.', '-maxdepth', '2', '-not', '-path', '*/.*'], 
                                 cwd=work_dir, capture_output=True, text=True)
            return res.stdout
        except:
            return "Unable to determine project structure."
    
    def _log(self, review_id, step, status, message, duration_ms):
        """Log a review step."""
        db.insert(
            "INSERT INTO review_logs (review_id, step, status, message, duration_ms, created_at) VALUES (%s,%s,%s,%s,%s, %s)",
            (review_id, step, status, message, duration_ms, datetime.now())
        )

    def _run_command_stream(self, review_id, step, cmd, env=None, cwd=None):
        """Execute command and stream output line-by-line to database logs."""
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                cwd=cwd,
                bufsize=1 # Line buffered
            )
            
            for line in process.stdout:
                clean_line = line.strip()
                if clean_line:
                    self._log(review_id, step.lower(), 'started', clean_line, 0)
            
            process.wait()
            return process.returncode
        except Exception as e:
            self._log(review_id, step.lower(), 'failed', f"Execution Error: {str(e)}", 0)
            return -1

    def _run_sonar_scan(self, review_id, repo, work_dir):
        """Run sonar-scanner on the cloned code."""
        
        sonar_config = db.execute(
            "SELECT * FROM sonar_configs WHERE repo_id = %s", (repo['id'],)
        )
        if not sonar_config:
            raise Exception("SonarQube not configured for this repo")
        
        sc = sonar_config[0]
        sonar_host = sc.get('sonar_host') or Config.SONAR_HOST
        sonar_token = sc.get('sonar_token') or Config.SONAR_TOKEN
        
        sources = os.path.join(work_dir, sc.get('sources_path', '.'))
        if not os.path.exists(sources):
            sources = work_dir
        
        env = os.environ.copy()
        env['JAVA_HOME'] = Config.SONAR_JAVA_HOME
        
        cmd = [
            Config.SONAR_SCANNER_PATH,
            f"-Dsonar.projectKey={sc['sonar_project_key']}",
            f"-Dsonar.projectName={sc.get('sonar_project_name', repo['name'])}",
            f"-Dsonar.host.url={sonar_host}",
            f"-Dsonar.token={sonar_token}",
            f"-Dsonar.projectBaseDir={work_dir}",
            f"-Dsonar.sources={sources}",
            "-Dsonar.sourceEncoding=UTF-8",
        ]
        
        if sc.get('exclusions'):
            cmd.append(f"-Dsonar.exclusions={sc['exclusions']}")
        if sc.get('test_inclusions'):
            cmd.append(f"-Dsonar.test.inclusions={sc['test_inclusions']}")
        
        return_code = self._run_command_stream(review_id, 'sonar_log', cmd, env=env)
        if return_code != 0:
            raise Exception(f"SonarScanner failed with exit code {return_code}")
    
    def _wait_for_sonar_analysis(self, review_id, repo, work_dir):
        """Wait for SonarQube server to complete analysis by tracking the specific Task ID."""
        sc_rows = db.execute("SELECT sonar_project_key, sonar_host, sonar_token FROM sonar_configs WHERE repo_id = %s", (repo['id'],))
        if not sc_rows: return
        sc = sc_rows[0]
        
        project_key = sc['sonar_project_key']
        sonar_host = sc.get('sonar_host') or Config.SONAR_HOST
        sonar_token = sc.get('sonar_token') or Config.SONAR_TOKEN
        headers = {'Authorization': f"Bearer {sonar_token}"}
        
        # ── Step 1: Extract Task ID from scanner report ──
        task_id = None
        report_path = os.path.join(work_dir, '.scannerwork', 'report-task.txt')
        if os.path.exists(report_path):
            try:
                with open(report_path, 'r') as f:
                    content = f.read()
                    match = re.search(r'ceTaskId=(.*)', content)
                    if match:
                        task_id = match.group(1).strip()
                        self._log(review_id, 'sonar_wait', 'started', f"Tracking specific SonarQube task: {task_id}", 0)
            except: pass

        # ── Step 2: Poll for completion ──
        self._log(review_id, 'sonar_wait', 'started', f"Awaiting server finalization for {project_key}...", 0)
        
        for attempt in range(30): # 2.5 mins
            try:
                if task_id:
                    # Poll specific task
                    resp = requests.get(f"{sonar_host}/api/ce/task", params={"id": task_id}, headers=headers, timeout=10)
                    task = resp.json().get('task', {})
                    status = task.get('status', '')
                else:
                    # Fallback to component-level polling
                    resp = requests.get(f"{sonar_host}/api/ce/component", params={"component": project_key}, headers=headers, timeout=10)
                    data = resp.json()
                    task = data.get('current', {})
                    status = task.get('status', '')
                    
                    if not status and not data.get('queue'):
                        self._log(review_id, 'sonar_wait', 'started', f"Waiting for task entry to appear (Attempt {attempt+1}/30)...", 0)
                        time.sleep(5)
                        continue

                if status == 'SUCCESS': 
                    self._log(review_id, 'sonar_wait', 'completed', "SonarQube analysis finalized successfully.", 0)
                    return
                elif status in ('FAILED', 'CANCELED'):
                    raise Exception(f"SonarQube analysis {status}")
                
                self._log(review_id, 'sonar_wait', 'started', f"Analysis status: {status or 'PENDING'} (Attempt {attempt+1}/30)...", 0)
            
            except Exception as e:
                if "analysis FAILED" in str(e): raise e
                self._log(review_id, 'sonar_wait_err', 'started', f"Polling error: {str(e)}", 0)
            
            time.sleep(5)
        
        self._log(review_id, 'sonar_wait', 'completed', "Wait timeout reached. Proceeding with best-effort fetch.", 0)
    
    def _fetch_sonar_results(self, review_id, repo):
        """Fetch issues from SonarQube API."""
        sc_rows = db.execute("SELECT sonar_project_key, sonar_host, sonar_token FROM sonar_configs WHERE repo_id = %s", (repo['id'],))
        if not sc_rows: return []
        sc = sc_rows[0]
        
        project_key = sc['sonar_project_key']
        sonar_host = sc.get('sonar_host') or Config.SONAR_HOST
        sonar_token = sc.get('sonar_token') or Config.SONAR_TOKEN
        headers = {'Authorization': f"Bearer {sonar_token}"}
        
        resp = requests.get(f"{sonar_host}/api/issues/search", params={"componentKeys": project_key, "ps": 500, "statuses": "OPEN,CONFIRMED,REOPENED"}, headers=headers, timeout=30)
        sonar_data = resp.json()
        
        db.update("UPDATE reviews SET sonar_raw_json = %s, sonar_total_issues = %s WHERE id = %s", (json.dumps(sonar_data), sonar_data.get('total', 0), review_id))
        return sonar_data
    
    def _filter_issues(self, review_id, sonar_data):
        """Filter and prioritize issues."""
        issues = [i for i in sonar_data.get('issues', []) if i.get('status') in ('OPEN', 'CONFIRMED', 'REOPENED') and i.get('severity') != 'INFO']
        sev_order = {'BLOCKER': 0, 'CRITICAL': 1, 'MAJOR': 2, 'MINOR': 3}
        issues.sort(key=lambda x: sev_order.get(x.get('severity', ''), 99))
        
        seen, unique = set(), []
        for i in issues:
            key = f"{i.get('rule')}:{i.get('component')}:{i.get('line',0)}"
            if key not in seen:
                seen.add(key); unique.append(i)
        
        slim = []
        for i in unique[:Config.MAX_ISSUES_FOR_AI]:
            file_path = i.get('component', '').split(':')[-1] if ':' in i.get('component', '') else i.get('component', '')
            slim.append({'rule': i.get('rule', ''), 'severity': i.get('severity', ''), 'type': i.get('type', ''), 'message': i.get('message', ''), 'file': file_path, 'line': i.get('line', 0)})
        
        summary = {
            'blockers': len([i for i in slim if i['severity'] == 'BLOCKER']),
            'criticals': len([i for i in slim if i['severity'] == 'CRITICAL']),
            'majors': len([i for i in slim if i['severity'] == 'MAJOR']),
            'minors': len([i for i in slim if i['severity'] == 'MINOR']),
            'bugs': len([i for i in slim if i['type'] == 'BUG']),
            'vulnerabilities': len([i for i in slim if i['type'] == 'VULNERABILITY']),
            'code_smells': len([i for i in slim if i['type'] == 'CODE_SMELL']),
        }
        
        db.update("""UPDATE reviews SET sonar_filtered_json = %s, sonar_filtered_issues = %s, sonar_bugs = %s, sonar_vulnerabilities = %s, sonar_code_smells = %s, sonar_blockers = %s, sonar_criticals = %s, sonar_majors = %s, files_affected = %s WHERE id = %s""", (json.dumps({'issues': slim}), len(slim), summary['bugs'], summary['vulnerabilities'], summary['code_smells'], summary['blockers'], summary['criticals'], summary['majors'], len(set(i['file'] for i in slim)), review_id))
        return {'issues': slim}

    def _call_gemini_cli(self, prompt, work_dir):
        """Call Gemini CLI with retry logic and exponential backoff."""
        model_name = Config.GEMINI_LARGE_MODEL if len(prompt) > 20000 else Config.GEMINI_DEFAULT_MODEL
        
        env = os.environ.copy()
        env["GOOGLE_CLOUD_PROJECT"] = "elab-code-assist"
        env["GOOGLE_CLOUD_PROJECT_ID"] = "elab-code-assist"
        
        cmd = [
            Config.GEMINI_CLI_BIN,
            "--prompt", "Please execute the request above.",
            "--model", model_name,
            "--approval-mode", "plan",
            "--sandbox"
        ]
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                process = subprocess.run(
                    cmd, 
                    input=prompt,
                    capture_output=True, 
                    text=True, 
                    env=env, 
                    cwd=work_dir, 
                    timeout=600
                )
                
                if process.returncode != 0:
                    raise Exception(f"Gemini CLI failed (exit {process.returncode}): {process.stderr[:1000]}")
                
                response = process.stdout
                if not response or len(response.strip()) < 50:
                    raise Exception(f"Gemini returned empty response. Stderr: {process.stderr[:500]}")
                    
                return response
                
            except Exception as e:
                wait_time = (2 ** attempt) * 5 # 5s, 10s, 20s
                print(f"      [Gemini Retry] Attempt {attempt+1}/{max_retries} failed: {e}. Retrying in {wait_time}s...")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(wait_time)
        
        return ""

    def _store_findings(self, review_id, ai_result):
        """Store findings and suggestions in database with robust field mapping."""
        
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
            
            # Robust extraction handles multiple parser naming conventions
            explanation = (v.get('explanation') or v.get('whatBreaks') or 
                          v.get('theLogicFailure') or '')
            fix_code = (v.get('fix') or v.get('fixedCode') or 
                       v.get('thePrincipalFix') or '')
            mermaid = (v.get('mermaidDiagram') or v.get('mermaid') or '')
            
            db.insert(
                """INSERT INTO findings 
                   (review_id, source, ai_verdict, title, category, severity, confidence, file_path, line_start, 
                    sonar_rule, explanation, production_impact, current_code, fix_code, mermaid_diagram, standard_violated, strategic_approach, remediation_plan) 
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (review_id, source, verdict, v.get('sonarRule', 'Sonar Issue'), 'SONAR_VALIDATION', sev, 
                 float(v.get('confidence', 0.8)), v.get('file', ''), int(v.get('line', 0) or 0), 
                 v.get('sonarRule', ''), explanation, v.get('productionImpact', ''), 
                 v.get('currentCode', ''), fix_code, 
                 mermaid, v.get('standard', ''), v.get('strategicApproach', ''), v.get('remediationPlan', ''))
            )

        # 2. Store Logical Findings
        findings = ai_result.get('logicalFindings', [])
        for f in findings:
            sev = self._normalize_severity(f.get('severity', 'MEDIUM'))
            
            # Robust extraction
            explanation = (f.get('theLogicFailure') or f.get('whatBreaks') or 
                          f.get('logicFailure') or f.get('explanation') or '')
            fix_code = (f.get('thePrincipalFix') or f.get('fixedCode') or 
                       f.get('fixCode') or f.get('fix') or '')
            current_code = (f.get('currentCode') or f.get('current_code') or '')
            mermaid = (f.get('mermaidDiagram') or f.get('mermaid') or '')
            
            db.insert(
                """INSERT INTO findings 
                   (review_id, source, ai_verdict, title, category, severity, confidence, file_path, line_start, 
                    line_end, explanation, production_impact, current_code, fix_code, test_code, 
                    remediation_plan, mermaid_diagram, strategic_approach, standard_violated) 
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (review_id, 'ai_finding', 'CONFIRMED', f.get('title', ''), f.get('category', 'LOGIC'), sev, 
                 float(f.get('confidence', 0.7)), f.get('file', ''), int(f.get('lineStart', 0) or 0), 
                 int(f.get('lineEnd', 0) or 0), explanation, f.get('productionImpact', ''), 
                 current_code, fix_code, f.get('proofTest', ''), 
                 f.get('remediationPlan', ''), mermaid, f.get('strategicApproach', ''), 
                 f.get('standard', ''))
            )

        # 3. Store Suggestions
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

    def _clean_cli_output(self, raw_output: str) -> str:
        """Extract the actual Gemini response from CLI wrapper output."""
        if not raw_output: return ""
        
        # Step 1: Remove ANSI color/escape codes
        ansi_pattern = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
        cleaned = ansi_pattern.sub('', raw_output)
        
        # Step 2: Try to extract content between markers
        first_marker = 'ASSESSMENT_START'
        last_markers = ['---SUGGESTIONS_END---', '---RISK_PREDICTION_END---', 
                        '---FINDING_END---', '---VALIDATION_END---', 'ASSESSMENT_END']
        
        start_idx = cleaned.find(first_marker)
        if start_idx == -1:
            return cleaned
        
        end_idx = -1
        for marker in last_markers:
            idx = cleaned.rfind(marker)
            if idx > end_idx:
                end_idx = idx + len(marker)
        
        if end_idx > start_idx:
            return cleaned[start_idx:end_idx]
        
        return cleaned[start_idx:]

    def _generate_report(self, review_id, repo, sonar_raw, filtered, ai_result):
        """Generate HTML report."""
        from engine.report_builder import build_html_report
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"review_{repo['name']}_{review_id}_{timestamp}.html"
        filepath = os.path.join(Config.REPORTS_DIR, filename)
        
        html = build_html_report(sonar_raw=sonar_raw, sonar_filtered=filtered, gemini_review=ai_result, project_name=repo['name'], timestamp=timestamp, review_id=review_id)
        with open(filepath, 'w', encoding='utf-8') as f: f.write(html)
        return filename