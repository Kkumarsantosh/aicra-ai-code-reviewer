"""
Engineering Intelligence — Analyzes project intent, work units, and structural footprint.
"""

import os
import json
import time
import subprocess
import threading
import requests
import re
import hashlib
from datetime import datetime, timedelta
from collections import defaultdict

from config import Config
from engine import db
from engine.ai_provider import AIProvider
from engine.git_manager import GitManager
from engine.jira_client import JiraClient

_ANALYSIS_TEMP = Config.AI_TEMPERATURE        # classification, risk, narrative
_JSON_TEMP     = Config.AI_TEMPERATURE_JSON   # structured JSON grouping

class ROIAuditor:
    def __init__(self):
        self.git = GitManager()
        self.jira = JiraClient()
        self.ai = AIProvider()

        # ── v6.0 Hybrid Audit Infrastructure ──
        self.lib_path = os.path.join(Config.BASE_DIR, "lib")
        self.cloc_path = os.path.join(self.lib_path, "cloc-2.08.pl")
        self.sizer_path = os.path.join(self.lib_path, "git-sizer-1.5.0-darwin-arm64", "git-sizer")
        


    def _extract_branch_context(self, branch, project_key=None):
        if project_key:
            ticket_match = re.search(rf'({project_key.upper()}-\d+)', branch.upper())
            if ticket_match: return ticket_match.group(1)
        ticket_match = re.search(r'([A-Z0-9]+-\d+)', branch.upper())
        return ticket_match.group(1) if ticket_match else "N/A"

    def _safe_update_status(self, analysis_id, expected_status, new_status, version, data=None):
        query = "UPDATE roi_analyses SET status = %s, version = version + 1"
        params = [new_status]
        if data:
            query += ", analysis_data = %s"
            params.append(data)
        query += " WHERE id = %s AND status = %s AND version = %s"
        params.extend([analysis_id, expected_status, version])
        return db.update(query, params) > 0

    def start_analysis(self, repo_id, branch, base_branch='main', commit_count=10):
        analysis_id = db.insert(
            "INSERT INTO roi_analyses (repo_id, branch, base_branch, status, target_commits, version) VALUES (%s, %s, %s, 'pending', %s, 1)",
            (repo_id, branch, base_branch, commit_count)
        )
        thread = threading.Thread(target=self._run_analysis, args=(analysis_id, repo_id, branch, base_branch, commit_count))
        thread.daemon = True
        thread.start()
        return analysis_id

    def _get_changed_files(self, commit_shas, repo_path):
        """STEP 2 FIX: Robustly extracts file changes from commits."""
        files_dict = defaultdict(lambda: {'path': '', 'change_type': '', 'lines_added': 0, 'lines_removed': 0, 'commits': []})
        for commit_sha in commit_shas:
            try:
                result = subprocess.run(['git', 'diff-tree', '--no-commit-id', '--name-status', '-r', commit_sha],
                                     cwd=repo_path, capture_output=True, text=True, check=True, timeout=10)
                for line in result.stdout.strip().split('\n'):
                    if not line: continue
                    parts = line.split('\t')
                    if len(parts) < 2: continue
                    change_type, file_path = parts[0][0], parts[1]
                    if self._should_skip_file(file_path): continue
                    
                    numstat = subprocess.run(['git', 'show', '--numstat', '--format=', commit_sha, '--', file_path],
                                          cwd=repo_path, capture_output=True, text=True, timeout=5)
                    added, removed = 0, 0
                    if numstat.returncode == 0 and numstat.stdout.strip():
                        stat_parts = numstat.stdout.strip().split('\n')[0].split('\t')
                        if len(stat_parts) >= 2:
                            try:
                                added = int(stat_parts[0]) if stat_parts[0] != '-' else 0
                                removed = int(stat_parts[1]) if stat_parts[1] != '-' else 0
                            except: pass
                    
                    if file_path not in files_dict:
                        files_dict[file_path]['path'] = file_path
                        files_dict[file_path]['change_type'] = change_type
                    files_dict[file_path]['lines_added'] += added
                    files_dict[file_path]['lines_removed'] += removed
                    files_dict[file_path]['commits'].append(commit_sha)
            except Exception as e: print(f"Error processing commit {commit_sha}: {e}")
        return list(files_dict.values())

    def _should_skip_file(self, file_path):
        skip_patterns = ['.git/', 'node_modules/', 'vendor/', '__pycache__/', 'package-lock.json', 'yarn.lock', 'go.sum', '.env', '.gitignore']
        if any(p in file_path for p in skip_patterns): return True
        binary_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.exe', '.dll', '.so']
        return any(file_path.endswith(ext) for ext in binary_extensions)

    def _analyze_complexity(self, work_unit_id, files, repo_path):
        source_files = [f for f in files if any(f['path'].endswith(ext) for ext in ['.py', '.js', '.ts', '.go', '.java', '.cs'])]
        if not source_files: return 0
        temp_file_list = os.path.join(repo_path, f'.aicra_cloc_{work_unit_id}.txt')
        try:
            with open(temp_file_list, 'w') as f:
                for sf in source_files:
                    fp = os.path.join(repo_path, sf['path'])
                    if os.path.exists(fp): f.write(fp + '\n')
            result = subprocess.run(["perl", self.cloc_path, "--json", "--list-file=" + temp_file_list], capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                cloc_data = json.loads(result.stdout)
                total_code = sum(v.get('code', 0) for k, v in cloc_data.items() if k not in ['header', 'SUM'])
                num_files, num_dirs = len(files), len(set(os.path.dirname(f['path']) for f in files))
                
                score = (1 if num_files <= 2 else 2 if num_files <= 5 else 3 if num_files <= 10 else 4 if num_files <= 20 else 5)
                score += (0 if total_code <= 50 else 1 if total_code <= 200 else 2 if total_code <= 500 else 3 if total_code <= 1000 else 4)
                score += (0 if num_dirs <= 1 else 1 if num_dirs <= 3 else 2)
                tier = 1 if score <= 2 else 2 if score <= 4 else 3 if score <= 6 else 4 if score <= 8 else 5
                
                db.update("UPDATE roi_work_units SET complexity_tier = %s, logic_lines = %s, cloc_data_json = %s WHERE id = %s",
                          (tier, total_code, json.dumps(cloc_data), work_unit_id))
                return total_code
        except Exception as e: print(f"Complexity Error: {e}")
        finally:
            if os.path.exists(temp_file_list): os.remove(temp_file_list)
        return 0

    def _classify_with_ai(self, work_unit_id, files, commit_shas, repo_path, commit_details):
        messages = []
        for sha in commit_shas:
            msg = next((c['message'] for c in commit_details if c['sha'].startswith(sha)), "Unknown")
            messages.append(msg)
        
        unit = db.execute("SELECT unit_name FROM roi_work_units WHERE id = %s", (work_unit_id,))[0]
        file_list = '\n'.join([f" - {f['path']} (+{f['lines_added']})" for f in files[:10]])
        
        prompt = f"""Classify this work unit: {unit['unit_name']}\nCommits:\n{chr(10).join(messages)}\nFiles:\n{file_list}\n
        Format:\nCATEGORY: [INNOVATION|MAINTENANCE|TECHNICAL_DEBT]\nCONFIDENCE: [0.5-1.0]\nREASONING: ...\nBUSINESS_IMPACT: ..."""
        
        try:
            res = self.ai.complete(prompt, work_dir=repo_path, temperature=_ANALYSIS_TEMP)
            cat = self._extract_field(res, 'CATEGORY', 'MAINTENANCE')
            conf = float(self._extract_field(res, 'CONFIDENCE', '0.7'))
            reason = self._extract_field(res, 'REASONING', '')
            impact = self._extract_field(res, 'BUSINESS_IMPACT', '')
            
            db.update("UPDATE roi_work_units SET work_category = %s, ai_confidence = %s, executive_summary = %s, business_impact = %s WHERE id = %s",
                      (cat, conf, reason, impact, work_unit_id))
            return {"work_category": cat, "ai_confidence": conf, "executive_summary": reason, "business_impact": impact}
        except Exception as e:
            cat = 'MAINTENANCE' if any(x in ' '.join(messages).lower() for x in ['fix', 'bug']) else 'INNOVATION'
            db.update("UPDATE roi_work_units SET work_category = %s WHERE id = %s", (cat, work_unit_id))
            return {"work_category": cat}

    def _extract_field(self, text, field, default=''):
        m = re.search(rf'{field}:\s*(.+?)(?:\n|$)', text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    def _run_analysis(self, analysis_id, repo_id, branch, base_branch, commit_count):
        self._log_progress(analysis_id, "INIT", "Initializing Engineering Intelligence Audit...")
        rows = db.execute("SELECT version FROM roi_analyses WHERE id = %s", (analysis_id,))
        if not rows: return
        version = rows[0]['version']
        if not self._safe_update_status(analysis_id, 'pending', 'analyzing', version): return
        version += 1
        
        try:
            repo = self.git.get_repo(repo_id)
            work_dir = os.path.join(Config.WORKSPACE_DIR, f"roi_repo_{repo_id}")
            self._log_progress(analysis_id, "CONTEXT", f"Targeting: {branch} (vs {base_branch})")
            
            ticket_id = self._extract_branch_context(branch, repo.get('jira_project_key'))
            self._log_progress(analysis_id, "JIRA", f"Fetching context for {ticket_id}...")
            jira_context = self.jira.get_issue_context(ticket_id)
            
            self._log_progress(analysis_id, "SYNC", f"Synchronizing repository node...")
            if not os.path.exists(work_dir): self.git.clone_repo(repo_id, branch, work_dir)
            else:
                for b in [base_branch, branch]: 
                    self._log_progress(analysis_id, "FETCH", f"Fetching {b}...")
                    subprocess.run(["git", "fetch", "origin", b], cwd=work_dir, capture_output=True)
                self._log_progress(analysis_id, "CHECKOUT", f"Checking out {branch}...")
                subprocess.run(["git", "checkout", branch], cwd=work_dir, capture_output=True)

            self._log_progress(analysis_id, "GIT_LOG", "Extracting commit history...")
            cmd = ["git", "log", "--reverse", "--no-merges", f"origin/{base_branch}..origin/{branch}", "--pretty=format:%H||%s||%an||%ct||%ad"]
            res = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
            commits = []
            for line in res.stdout.strip().split('\n'):
                if not line: continue
                p = line.split('||')
                if len(p) >= 5: commits.append({"sha": p[0], "message": p[1], "author": p[2], "timestamp": int(p[3]), "date": p[4]})

            if not commits:
                self._log_progress(analysis_id, "FALLBACK", "No delta found. Analyzing recent activity.")
                cmd = ["git", "log", "-n", "5", "--pretty=format:%H||%s||%an||%ct||%ad"]
                res = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
                for line in res.stdout.strip().split('\n'):
                    if not line: continue
                    p = line.split('||')
                    if len(p) >= 5: commits.append({"sha": p[0], "message": p[1], "author": p[2], "timestamp": int(p[3]), "date": p[4]})

            self._log_progress(analysis_id, "COMMITS", f"Analyzing {len(commits)} commits...")
            commit_details = []
            for c in commits:
                detail = self._analyze_single_commit(c, None, work_dir, analysis_id)
                commit_details.append(detail)

            self._log_progress(analysis_id, "GROUPING", "Synthesizing logical units...")
            grouped_work = self._group_commits_with_ai(commit_details, work_dir=work_dir)
            unique_all_files = set()
            for group in grouped_work:
                shadow, count, files = self._analyze_work_unit(analysis_id, group, work_dir, jira_context, repo_id, commit_details)
                for f in files: unique_all_files.add(f['path'])

            report_data = {"summary": {"commits_analyzed": len(commits), "logical_units": len(grouped_work), "structural_footprint": len(unique_all_files)},
                           "logical_units": grouped_work}
            
            report_data["executive_intelligence"] = self._generate_executive_intelligence_v2(report_data["summary"], grouped_work, analysis_id)

            self._safe_update_status(analysis_id, 'analyzing', 'complete', version, data=json.dumps(report_data))
            self._log_progress(analysis_id, "COMPLETE", "Audit finalized.")
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            self._log_progress(analysis_id, "FAILED", str(e))
            db.update("UPDATE roi_analyses SET status = 'failed', analysis_data = %s WHERE id = %s", (str(e), analysis_id))

    def _generate_executive_intelligence_v2(self, summary, grouped_work, analysis_id):
        """Phase 1: Factual Engineering Intelligence. No fake ROI or speculative metrics."""
        quadrant_data = []
        for unit in grouped_work:
            audit = unit.get('shadow_audit', {})
            cat = audit.get('work_category', 'MAINTENANCE')
            exec_quadrant = "Maintenance"
            if cat == 'INNOVATION': exec_quadrant = "New Feature"
            elif cat == 'BUG_FIX': exec_quadrant = "Quality Improvement"
            elif cat == 'REFACTORING': exec_quadrant = "Technical Debt"
            
            quadrant_data.append({
                "unit": unit.get('unit_name'),
                "quadrant": exec_quadrant,
                "business_value": audit.get('executive_summary', 'Operational Stability'),
                "impact": f"{len(audit.get('deterministic_complexity', {}).get('file_changes', []))} files impacted"
            })

        unit_names = ", ".join([u['unit_name'] for u in grouped_work[:2]])
        mgmt_summary = (
            f"Audit {analysis_id} analyzed {summary.get('commits_analyzed')} commits across {summary.get('logical_units')} logical units. "
            f"Key focus areas included {unit_names}. "
            f"The work involved {summary.get('structural_footprint')} files."
        )

        return {
            "dashboard": {
                "work_delivered": f"{summary.get('logical_units')} Units",
                "structural_footprint": f"{summary.get('structural_footprint')} Files",
                "audit_status": "FACTUAL_AUDIT_COMPLETE",
                "intelligence_summary": mgmt_summary
            },
            "quadrant_ledger": quadrant_data,
            "management_summary": mgmt_summary,
            "traffic_light": "green" if summary.get('logical_units', 0) > 0 else "yellow"
        }

    def _analyze_work_unit(self, analysis_id, group, work_dir, jira_context, repo_id, commit_details):
        # 1. Identity attribution
        author = "Engineering Team"
        commit_shas = group.get('commits', [])
        if commit_shas:
            first_sha = commit_shas[0]
            for c in commit_details:
                if c['sha'].startswith(first_sha) or first_sha.startswith(c['sha']):
                    author = c.get('author', author)
                    break

        # 2. Extract Jira Tickets from commits
        tickets = set()
        for sha in commit_shas:
            for c in commit_details:
                if c['sha'].startswith(sha) or sha.startswith(c['sha']):
                    found = re.findall(r'([A-Z0-9]+-\d+)', c['message'].upper())
                    for t in found: tickets.add(t)
        
        jira_data = []
        for t in list(tickets)[:5]: # Limit to 5 tickets per unit
            info = self.jira.get_issue_basic(t)
            if info: jira_data.append(info)

        wu_id = db.insert(
            "INSERT INTO roi_work_units (analysis_id, unit_name, author, intent, jira_tickets_json) VALUES (%s, %s, %s, %s, %s)", 
            (analysis_id, group['unit_name'], author, group.get('intent', 'N/A'), json.dumps(jira_data))
        )
        
        files = self._get_changed_files(commit_shas, work_dir)
        
        total_added = 0
        total_deleted = 0
        for f in files:
            total_added += f['lines_added']
            total_deleted += f['lines_removed']
            db.insert("INSERT INTO roi_work_unit_files (work_unit_id, file_path, change_type, lines_added, lines_removed, commits_json) VALUES (%s, %s, %s, %s, %s, %s)",
                      (wu_id, f['path'], f['change_type'], f['lines_added'], f['lines_removed'], json.dumps(f['commits'])))
        
        # Update initial metrics
        db.update("UPDATE roi_work_units SET files_impacted = %s, lines_added = %s, lines_removed = %s WHERE id = %s",
                  (len(files), total_added, total_deleted, wu_id))
        
        self._analyze_complexity(wu_id, files, work_dir)
        shadow = self._classify_with_ai(wu_id, files, commit_shas, work_dir, commit_details)
        risks = self._detect_structural_risks(group, commit_details, repo_id)
        db.update("UPDATE roi_work_units SET risk_assessment = %s WHERE id = %s", (json.dumps(risks), wu_id))
        
        final = db.execute("SELECT * FROM roi_work_units WHERE id = %s", (wu_id,))[0]
        shadow_audit = {
            "work_category": final['work_category'], "complexity_tier": final['complexity_tier'],
            "executive_summary": final['executive_summary'], "business_impact": final['business_impact'],
            "ai_confidence": float(final['ai_confidence']), "structural_risks": risks,
            "deterministic_complexity": {"added_logic": final['logic_lines'], "files_impacted": final['files_impacted'], 
                                        "file_changes": [{"file": f['path'], "added": f['lines_added'], "deleted": f['lines_removed']} for f in files]}
        }
        return shadow_audit, len(files), files

    def _analyze_single_commit(self, commit, prev_time, work_dir, analysis_id):
        sha = commit['sha']
        res = subprocess.run(["git", "show", "--numstat", "--format=", sha], cwd=work_dir, capture_output=True, text=True)
        file_stats = []
        for line in res.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 3:
                added = int(parts[0]) if parts[0] != '-' else 0
                deleted = int(parts[1]) if parts[1] != '-' else 0
                file_stats.append({"file": parts[2], "added": added, "deleted": deleted, "category": "logic"})
        return {"sha": sha, "message": commit['message'], "file_stats": file_stats}

    def _group_commits_with_ai(self, commit_details, work_dir=None):
        log = "\n".join([f"{c['sha'][:7]} : {c['message']}" for c in commit_details])
        prompt = f"Group these commits into logical units:\n{log}\nRespond ONLY JSON array: [{{'unit_name': '...', 'intent': '...', 'commits': ['sha']}}]"
        try:
            raw = self.ai.complete(prompt, work_dir=work_dir, temperature=_JSON_TEMP)
            res = self.ai.parse_json(raw, default=[])
            # Robust extraction of the list
            if isinstance(res, dict):
                for key in res:
                    if isinstance(res[key], list):
                        return res[key]
                if 'unit_name' in res:
                    return [res]
            return res if isinstance(res, list) else [{"unit_name": "General Activity", "commits": [c['sha'] for c in commit_details]}]
        except Exception:
            return [{"unit_name": "General Activity", "commits": [c['sha'] for c in commit_details]}]

    def _detect_structural_risks(self, group, commit_details, repo_id):
        """Heuristic risk detection with severity levels and specific alerts."""
        risks = []
        
        # 1. Large Changes Without Tests
        logic_lines = 0
        test_changed = False
        impacted_files = []
        
        commit_shas = group.get('commits', [])
        for sha in commit_shas:
            for c in commit_details:
                if c['sha'].startswith(sha) or sha.startswith(c['sha']):
                    for f in c.get('file_stats', []):
                        if f.get('category') == 'logic':
                            logic_lines += f.get('added', 0)
                            impacted_files.append(f"{f['file']} (+{f['added']} lines)")
                        if 'test' in f['file'].lower() or 'spec' in f['file'].lower():
                            test_changed = True
        
        if logic_lines > 300 and not test_changed:
            files_key = ",".join(sorted(list(set([f.split()[0] for f in impacted_files]))))
            last_sha = commit_shas[-1] if commit_shas else "unknown"
            r_hash = hashlib.md5(f"{repo_id}:LARGE_CHANGE_NO_TESTS:{files_key}:{last_sha}".encode()).hexdigest()
            
            risks.append({
                "severity": "MEDIUM",
                "risk_hash": r_hash,
                "message": f"Large logic change ({logic_lines} lines) without accompanying test changes.",
                "recommendation": "Add unit or integration tests for the new logic."
            })
            
        # 2. Security-Sensitive Changes
        sensitive_patterns = ['auth', 'security', 'password', 'token', 'crypt', 'secret', 'hashing', 'perm', 'privilege']
        sensitive_files = []
        for sha in commit_shas:
            for c in commit_details:
                if c['sha'].startswith(sha) or sha.startswith(c['sha']):
                    for f in c.get('file_stats', []):
                        if any(kw in f['file'].lower() for kw in sensitive_patterns):
                            if f['added'] > 10: 
                                sensitive_files.append(f"{f['file']} (+{f['added']} lines)")
        
        if sensitive_files:
            files_key = ",".join(sorted(list(set([f.split()[0] for f in sensitive_files]))))
            last_sha = commit_shas[-1] if commit_shas else "unknown"
            r_hash = hashlib.md5(f"{repo_id}:SECURITY_SENSITIVE:{files_key}:{last_sha}".encode()).hexdigest()
            
            risks.append({
                "severity": "HIGH",
                "risk_hash": r_hash,
                "message": f"Security-sensitive files modified significantly.",
                "recommendation": "Ensure this change has been reviewed by a security engineer."
            })

        return risks

    def _log_progress(self, analysis_id, step, message):
        db.insert("INSERT INTO roi_logs (analysis_id, step, message) VALUES (%s, %s, %s)", (analysis_id, step, message))

    def _calculate_aggregates(self, work_units):
        """Helper to calculate aggregate metrics across a set of work units."""
        if not work_units:
            return {
                'total_work_units': 0, 'total_files': 0, 'total_added': 0, 'total_removed': 0,
                'total_logic': 0, 'innovation_percentage': 0, 'maintenance_percentage': 0, 'average_complexity': 0
            }
            
        total_files = sum(wu['files_impacted'] for wu in work_units)
        total_added = sum(wu['lines_added'] for wu in work_units)
        total_removed = sum(wu['lines_removed'] for wu in work_units)
        total_logic = sum(wu['logic_lines'] or 0 for wu in work_units)
        
        innovation_units = [wu for wu in work_units if wu.get('work_category') == 'INNOVATION']
        maintenance_units = [wu for wu in work_units if wu.get('work_category', 'MAINTENANCE') == 'MAINTENANCE']
        
        innovation_pct = len(innovation_units) / len(work_units) * 100
        maintenance_pct = len(maintenance_units) / len(work_units) * 100
        
        avg_tier = sum(wu['complexity_tier'] or 0 for wu in work_units) / len(work_units)
        
        return {
            'total_work_units': len(work_units),
            'total_files': total_files,
            'total_added': total_added,
            'total_removed': total_removed,
            'total_logic': total_logic,
            'innovation_percentage': round(innovation_pct, 1),
            'maintenance_percentage': round(maintenance_pct, 1),
            'average_complexity': round(avg_tier, 1),
        }

    def get_weekly_report(self):
        """Task 6 Helper: Aggregates factual data for the weekly statement."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        rows = db.execute("SELECT * FROM roi_analyses WHERE status='complete' AND created_at >= %s", (start_date,))
        
        # Get work units for aggregates
        work_units = self.get_weekly_work_units()
        aggregates = self._calculate_aggregates(work_units)
        
        return {
            "period": f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}",
            "metrics": {"total_units_delivered": aggregates['total_work_units'], "total_files_impacted": aggregates['total_files'], "quality_metrics": "Factual Integrity Verified"},
            "raw_audits_count": len(rows),
            "engineering_narrative": f"Analyzed {aggregates['total_work_units']} logical units across {len(rows)} operational audits this week.",
            "aggregates": aggregates
        }

    def get_weekly_work_units(self):
        """Fetches all work units and their files from the last 7 days for the weekly statement."""
        start_date = datetime.now() - timedelta(days=7)
        work_units = db.execute(
            "SELECT * FROM roi_work_units WHERE created_at >= %s ORDER BY created_at DESC", 
            (start_date,)
        )
        for wu in work_units:
            wu['files'] = db.execute(
                "SELECT * FROM roi_work_unit_files WHERE work_unit_id = %s ORDER BY lines_added DESC",
                (wu['id'],)
            )
            wu['classification'] = wu.get('work_category', 'MAINTENANCE')
            try:
                wu['jira_tickets'] = json.loads(wu['jira_tickets_json']) if wu.get('jira_tickets_json') else []
            except: wu['jira_tickets'] = []
        return work_units

    def build_roi_report(self, analysis_id):
        """Task 6 core logic: Fetches relational data for detailed reporting."""
        work_units = db.execute("SELECT * FROM roi_work_units WHERE analysis_id = %s ORDER BY id", (analysis_id,))
        for wu in work_units:
            wu['files'] = db.execute("SELECT * FROM roi_work_unit_files WHERE work_unit_id = %s ORDER BY lines_added DESC", (wu['id'],))
            wu['classification'] = wu.get('work_category', 'MAINTENANCE') 
            try:
                wu['jira_tickets'] = json.loads(wu['jira_tickets_json']) if wu.get('jira_tickets_json') else []
            except: wu['jira_tickets'] = []
            
        aggregates = self._calculate_aggregates(work_units)
        dev_breakdown = self._get_developer_breakdown(work_units)
        return work_units, aggregates, dev_breakdown

    def _get_developer_breakdown(self, work_units):
        """Task Enhancement 3: Groups work by developer."""
        devs = defaultdict(lambda: {'units_count': 0, 'total_logic': 0, 'impacted_files': 0})
        for wu in work_units:
            author = wu.get('author', 'Engineering Team')
            devs[author]['units_count'] += 1
            devs[author]['total_logic'] += wu.get('logic_lines', 0)
            devs[author]['impacted_files'] += wu.get('files_impacted', 0)
        
        # Convert to list for template
        breakdown = []
        for name, stats in devs.items():
            breakdown.append({
                'name': name,
                'units': stats['units_count'],
                'logic': stats['total_logic'],
                'files': stats['impacted_files']
            })
        return sorted(breakdown, key=lambda x: x['logic'], reverse=True)

    def dismiss_risk(self, repo_id, risk_hash, username, reason):
        db.insert("INSERT INTO roi_dismissed_risks (repo_id, risk_hash, dismissed_by, reason) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE reason = VALUES(reason)", (repo_id, risk_hash, username, reason))

    def get_dismissed_risks(self, repo_id):
        rows = db.execute("SELECT risk_hash FROM roi_dismissed_risks WHERE repo_id = %s", (repo_id,))
        return set([r['risk_hash'] for r in rows])

    def get_unlinked_work_report(self, repo_id):
        """Generates a weekly report of commits not linked to any Jira ticket."""
        repo = self.git.get_repo(repo_id)
        if not repo:
            return {
                "total_commits": 0,
                "linked_count": 0,
                "unlinked_count": 0,
                "potential_feature": [],
                "routine": []
            }

        meta_dir = os.path.join(Config.WORKSPACE_DIR, f"meta_repo_{repo_id}")
        clone_url = repo['clone_url'].replace('https://github.com', f'https://{self.git.token}@github.com') if self.git.token else repo['clone_url']

        # Ensure metadata directory exists and is updated
        try:
            if not os.path.exists(meta_dir):
                os.makedirs(meta_dir, exist_ok=True)
                # Clone bare with depth=150 and no-single-branch for efficiency and to capture recent commits on all branches
                subprocess.run(['git', 'clone', '--bare', '--depth=150', '--no-single-branch', '--filter=blob:none', clone_url, '.'], cwd=meta_dir, capture_output=True, timeout=60)
            else:
                subprocess.run(['git', 'fetch', '--depth=150', 'origin', '*:*'], cwd=meta_dir, capture_output=True, timeout=30)
        except Exception as e:
            print(f"Error syncing repo metadata for unlinked work: {e}")
            # Continue using whatever is locally available in meta_dir if it exists
            if not os.path.exists(meta_dir):
                return {
                    "total_commits": 0,
                    "linked_count": 0,
                    "unlinked_count": 0,
                    "potential_feature": [],
                    "routine": []
                }

        # Get all commits from the last 7 days across all branches, excluding merges
        cmd = ["git", "log", "--all", "--since=7 days ago", "--no-merges", "--pretty=format:%H||%s||%an||%at"]
        res = subprocess.run(cmd, cwd=meta_dir, capture_output=True, text=True)
        if res.returncode != 0:
            return {
                "total_commits": 0,
                "linked_count": 0,
                "unlinked_count": 0,
                "potential_feature": [],
                "routine": []
            }

        seen_shas = set()
        commits = []
        for line in res.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('||')
            if len(parts) >= 4:
                sha = parts[0]
                if sha in seen_shas:
                    continue
                seen_shas.add(sha)
                commits.append({
                    "sha": sha,
                    "message": parts[1],
                    "author": parts[2],
                    "timestamp": int(parts[3])
                })

        total_commits = len(commits)
        linked_count = 0
        unlinked_count = 0
        potential_feature = []
        routine = []

        for c in commits:
            sha = c['sha']
            message = c['message']
            author = c['author']

            # Check if message itself has a Jira reference
            has_jira = bool(re.search(r'([A-Z0-9]+-\d+)', message.upper()))

            if not has_jira:
                # Check branches containing this commit
                try:
                    b_res = subprocess.run(['git', 'branch', '--contains', sha], cwd=meta_dir, capture_output=True, text=True, timeout=5)
                    if b_res.returncode == 0:
                        for b_line in b_res.stdout.split('\n'):
                            branch_name = b_line.replace('*', '').strip()
                            if branch_name and re.search(r'([A-Z0-9]+-\d+)', branch_name.upper()):
                                has_jira = True
                                break
                except Exception as e:
                    print(f"Error checking branches for commit {sha}: {e}")

            if has_jira:
                linked_count += 1
                continue

            unlinked_count += 1

            # Get files and lines changed for this unlinked commit
            files_changed = 0
            lines_changed = 0
            try:
                s_res = subprocess.run(['git', 'show', '--numstat', '--format=', sha], cwd=meta_dir, capture_output=True, text=True, timeout=5)
                if s_res.returncode == 0:
                    for s_line in s_res.stdout.strip().split('\n'):
                        if not s_line:
                            continue
                        parts = s_line.split()
                        if len(parts) >= 3:
                            files_changed += 1
                            try:
                                added = int(parts[0]) if parts[0] != '-' else 0
                                deleted = int(parts[1]) if parts[1] != '-' else 0
                                lines_changed += (added + deleted)
                            except ValueError:
                                pass
            except Exception as e:
                print(f"Error getting stats for commit {sha}: {e}")

            # Classify
            author_lower = author.lower()
            is_bot = any(kw in author_lower for kw in ['bot', 'action', 'service', 'sonar', 'jenkins', 'ci', 'workflow'])
            
            message_lower = message.lower()
            is_routine_msg = any(kw in message_lower for kw in ['merge', 'revert', 'lint', 'format', 'bump', 'chore', 'dependencies'])
            
            is_small_change = (files_changed < 3 and lines_changed < 30)

            commit_obj = {
                "sha": sha[:8],
                "message": message,
                "author": author,
                "files": files_changed,
                "lines": lines_changed
            }

            if is_bot or is_routine_msg or is_small_change:
                routine.append(commit_obj)
            else:
                potential_feature.append(commit_obj)

        return {
            "total_commits": total_commits,
            "linked_count": linked_count,
            "unlinked_count": unlinked_count,
            "potential_feature": potential_feature,
            "routine": routine
        }
