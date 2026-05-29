"""
GitHub integration: list repos, branches, clone, and developer activity tracking.
"""

import requests
import subprocess
import os
import shutil
import json
import time
import threading
from datetime import datetime, timedelta
from config import Config
from engine import db

_branches_cache: dict = {}   # {repo_id: (branch_list, fetched_at)}
_BRANCHES_TTL = 300          # seconds before re-fetching from GitHub


class GitManager:
    
    def __init__(self):
        self.api_url = Config.GITHUB_API_URL
        self.token = Config.GITHUB_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }

    def sync_repos(self):
        """Sync list of repos from GitHub to local database."""
        repos = []
        page = 1
        while True:
            params = {'per_page': 100, 'page': page, 'sort': 'updated', 'direction': 'desc'}
            url = f"{self.api_url}/orgs/{Config.GITHUB_ORG}/repos" if Config.GITHUB_ORG else f"{self.api_url}/user/repos"
            resp = requests.get(url, headers=self.headers, params=params)
            if resp.status_code != 200: raise Exception(f"GitHub API error: {resp.status_code}")
            batch = resp.json()
            if not batch: break
            repos.extend(batch)
            page += 1
            if len(batch) < 100: break
        
        synced = 0
        for repo in repos:
            existing = db.execute("SELECT id FROM repos WHERE github_id = %s", (repo['id'],))
            if existing:
                db.update("""UPDATE repos SET name = %s, full_name = %s, git_url = %s, clone_url = %s, default_branch = %s, language = %s, description = %s, is_private = %s, last_synced_at = NOW() WHERE github_id = %s""",
                    (repo['name'], repo['full_name'], repo.get('html_url', ''), repo.get('clone_url', ''), repo.get('default_branch', 'main'), repo.get('language', ''), (repo.get('description', '') or '')[:500], repo.get('private', False), repo['id']))
            else:
                db.insert("""INSERT INTO repos (github_id, name, full_name, git_url, clone_url, default_branch, language, description, is_private, last_synced_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
                    (repo['id'], repo['name'], repo['full_name'], repo.get('html_url', ''), repo.get('clone_url', ''), repo.get('default_branch', 'main'), repo.get('language', ''), (repo.get('description', '') or '')[:500], repo.get('private', False)))
            synced += 1
        return {"synced": synced, "total": len(repos)}

    def get_repos(self, active_only=True):
        """Get repos from database with optional active filter."""
        query = "SELECT r.*, sc.sonar_project_key, sc.is_configured as sonar_configured, sc.last_scan_at as sonar_last_scan, sc.quality_gate_status, (SELECT COUNT(*) FROM reviews rv WHERE rv.repo_id = r.id) as review_count, (SELECT ai_risk_level FROM reviews rv WHERE rv.repo_id = r.id ORDER BY rv.created_at DESC LIMIT 1) as last_risk_level FROM repos r LEFT JOIN sonar_configs sc ON sc.repo_id = r.id"
        if active_only: query += " WHERE r.is_active = TRUE"
        query += " ORDER BY r.name"
        return db.execute(query)

    def sync_developer_activity(self, days=90):
        """Optimized scanner: focuses ONLY on active repositories."""
        since_iso = (datetime.now() - timedelta(days=days)).isoformat() + 'Z'
        active_repos = self.get_repos(active_only=True)
        all_activity = {} 
        scanned_shas = set()
        
        for r in active_repos:
            repo_name = r['full_name']
            default_branch = r.get('default_branch') or 'main'
            commits_url = f"{self.api_url}/repos/{repo_name}/commits"
            try:
                c_resp = requests.get(commits_url, headers=self.headers, params={'since': since_iso, 'sha': default_branch, 'per_page': 100}, timeout=20)
                if c_resp.status_code != 200: continue
                batch = c_resp.json()
                if not batch: continue
                
                for c in batch:
                    if c['sha'] in scanned_shas: continue
                    scanned_shas.add(c['sha'])
                    commit_author = c['commit']['author']
                    email = commit_author.get('email')
                    if not email: continue
                    
                    author_data = c.get('author')
                    login = author_data['login'] if author_data else email
                    avatar = author_data['avatar_url'] if author_data else None
                    date_str = commit_author['date'].split('T')[0]
                    
                    if email not in all_activity: all_activity[email] = {}
                    if date_str not in all_activity[email]:
                        all_activity[email][date_str] = {'login': login, 'name': commit_author.get('name'), 'avatar': avatar, 'commits': 0, 'added': 0, 'removed': 0, 'files': set(), 'email': email}
                    
                    day_stats = all_activity[email][date_str]
                    day_stats['commits'] += 1
                    if len(scanned_shas) < 300:
                        try:
                            det = requests.get(c['url'], headers=self.headers, timeout=10).json()
                            stats = det.get('stats', {})
                            day_stats['added'] += stats.get('additions', 0)
                            day_stats['removed'] += stats.get('deletions', 0)
                            for f in det.get('files', []): day_stats['files'].add(f['filename'])
                        except: pass
            except: pass

        for email, dates in all_activity.items():
            dev_rows = db.execute("SELECT id FROM developers WHERE email = %s", (email,))
            if not dev_rows: dev_id = db.insert("INSERT INTO developers (github_username, display_name, avatar_url, email) VALUES (%s,%s,%s,%s)", (list(dates.values())[0]['login'], list(dates.values())[0]['name'], list(dates.values())[0]['avatar'], email))
            else:
                dev_id = dev_rows[0]['id']
                db.update("UPDATE developers SET avatar_url = %s, display_name = %s, github_username = %s WHERE id = %s", (list(dates.values())[0]['avatar'], list(dates.values())[0]['name'], list(dates.values())[0]['login'], dev_id))
            for d_str, s in dates.items():
                db.execute("INSERT INTO developer_daily_stats (developer_id, stats_date, commits_count, lines_added, lines_removed, files_touched_count) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE commits_count=VALUES(commits_count), lines_added=VALUES(lines_added), lines_removed=VALUES(lines_removed), files_touched_count=VALUES(files_touched_count)", (dev_id, d_str, s['commits'], s['added'], s['removed'], len(s['files'])), fetch=False)
        return len(all_activity)

    def get_repo(self, repo_id):
        rows = db.execute("""SELECT r.*, sc.id as sonar_config_id, sc.sonar_project_key, sc.sonar_project_name, 
                             sc.sonar_host, sc.sonar_token, sc.sources_path, sc.exclusions, sc.test_inclusions, 
                             sc.is_configured as sonar_configured, sc.last_scan_at as sonar_last_scan, sc.quality_gate_status
                             FROM repos r LEFT JOIN sonar_configs sc ON sc.repo_id = r.id WHERE r.id = %s""", (repo_id,))
        return rows[0] if rows else None

    def get_branches(self, repo_id):
        now = time.time()
        entry = _branches_cache.get(repo_id)
        if entry and (now - entry[1]) < _BRANCHES_TTL:
            return entry[0]

        result = self._fetch_branches(repo_id)
        if isinstance(result, list):
            _branches_cache[repo_id] = (result, now)
        return result

    def _fetch_branches(self, repo_id):
        repo = self.get_repo(repo_id)
        if not repo:
            return {"error": "Repository not found in local index"}

        default_branch = repo.get('default_branch', 'main')
        meta_dir = os.path.join(Config.WORKSPACE_DIR, f"meta_repo_{repo_id}")
        clone_url = (
            repo['clone_url'].replace('https://github.com', f'https://{self.token}@github.com')
            if self.token else repo['clone_url']
        )

        # Fast path: local bare-clone already exists — sorted by committer date, no network call
        if os.path.exists(meta_dir):
            local = self._read_local_branches(meta_dir, default_branch)
            if local:
                # Refresh in background so the next TTL cycle has up-to-date ordering
                threading.Thread(
                    target=self._background_sync, args=(meta_dir, clone_url), daemon=True
                ).start()
                return self._top20_with_default(local, default_branch)

        # Cold start: no local clone yet — use GitHub API (fast, alphabetical)
        try:
            branches = self._fetch_branches_from_api(repo['full_name'], default_branch)
            if branches:
                # Sync in background so the next page load serves sorted results
                threading.Thread(
                    target=self._background_sync, args=(meta_dir, clone_url), daemon=True
                ).start()
                return self._top20_with_default(branches, default_branch)
        except Exception:
            pass

        # Last resort: blocking sync (network required but local clone absent)
        try:
            self._sync_meta_repo(meta_dir, clone_url)
            branches = self._read_local_branches(meta_dir, default_branch)
            if branches:
                return self._top20_with_default(branches, default_branch)
        except Exception:
            pass

        return {"error": "Could not retrieve branches from GitHub API or local git"}

    def _background_sync(self, meta_dir, clone_url):
        """Refresh the bare clone in a daemon thread — never blocks the request."""
        try:
            self._sync_meta_repo(meta_dir, clone_url)
        except Exception:
            pass

    def _sync_meta_repo(self, meta_dir, clone_url):
        if not os.path.exists(meta_dir):
            os.makedirs(meta_dir, exist_ok=True)
            subprocess.run(
                ['git', 'clone', '--bare', '--depth', '1', '--no-single-branch', '--filter=blob:none', clone_url, '.'],
                cwd=meta_dir, capture_output=True, timeout=60,
            )
        else:
            try:
                subprocess.run(
                    ['git', 'fetch', '--depth', '1', 'origin', '*:*'],
                    cwd=meta_dir, capture_output=True, timeout=30,
                )
            except subprocess.TimeoutExpired:
                pass  # stale cache acceptable; API fallback runs if local refs are empty

    def _read_local_branches(self, meta_dir, default_branch):
        res = subprocess.run(
            ['git', 'for-each-ref', '--sort=-committerdate', 'refs/heads/', '--format=%(refname:short)'],
            cwd=meta_dir, capture_output=True, text=True, timeout=10,
        )
        if res.returncode != 0:
            return []
        return [
            {'name': b, 'is_default': b == default_branch}
            for b in res.stdout.strip().split('\n')
            if b and b != 'HEAD'
        ]

    def _fetch_branches_from_api(self, full_name, default_branch):
        resp = requests.get(
            f"{self.api_url}/repos/{full_name}/branches",
            headers=self.headers, params={'per_page': 30}, timeout=10,
        )
        if resp.status_code != 200:
            return []
        return [{'name': b['name'], 'is_default': b['name'] == default_branch} for b in resp.json()]

    @staticmethod
    def _top20_with_default(branches, default_branch):
        top_20 = branches[:20]
        if not any(b['is_default'] for b in top_20):
            default_ref = next((b for b in branches if b['is_default']), None)
            if default_ref:
                top_20 = [default_ref] + branches[:19]
        return top_20

    def clone_repo(self, repo_id, branch, work_dir, log_callback=None):
        repo = self.get_repo(repo_id)
        clone_url = repo['clone_url'].replace('https://github.com', f'https://{self.token}@github.com') if self.token else repo['clone_url']
        if os.path.exists(work_dir): shutil.rmtree(work_dir)
        os.makedirs(work_dir, exist_ok=True)
        if log_callback:
            p = subprocess.Popen(['git', 'clone', '--depth', '1', '--progress', '--branch', branch, clone_url, work_dir], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout: log_callback(line.strip())
            p.wait()
        else: subprocess.run(['git', 'clone', '--depth', '1', '--branch', branch, clone_url, work_dir], capture_output=True)
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=work_dir).stdout.strip()
        return {'path': work_dir, 'commit_sha': sha, 'repo_name': repo['name']}

    def post_pr_comment(self, repo_id, branch, markdown_body):
        repo = self.get_repo(repo_id)
        if not repo: return
        pr_url = f"{self.api_url}/repos/{repo['full_name']}/pulls"
        try:
            resp = requests.get(pr_url, headers=self.headers, params={'head': f"{repo['full_name'].split('/')[0]}:{branch}", 'state': 'open'})
            if resp.status_code == 200 and resp.json():
                pr_number = resp.json()[0]['number']
                comment_url = f"{self.api_url}/repos/{repo['full_name']}/issues/{pr_number}/comments"
                requests.post(comment_url, headers=self.headers, json={"body": markdown_body})
            else:
                requests.post(f"{self.api_url}/repos/{repo['full_name']}/commits/{branch}/comments", headers=self.headers, json={"body": markdown_body})
        except: pass

    def save_sonar_config(self, repo_id, config):
        # Save Jira keys to repos table
        db.update("UPDATE repos SET jira_project_key = %s, jira_parent_epic = %s WHERE id = %s", 
                  (config.get('jira_project_key'), config.get('jira_parent_epic'), repo_id))
        
        # Save Sonar config
        existing = db.execute("SELECT id FROM sonar_configs WHERE repo_id = %s", (repo_id,))
        if existing:
            db.update("UPDATE sonar_configs SET sonar_project_key = %s, sonar_project_name = %s, sonar_host = %s, sonar_token = %s, sources_path = %s, exclusions = %s, test_inclusions = %s, is_configured = TRUE WHERE repo_id = %s", (config.get('sonar_project_key'), config.get('sonar_project_name'), config.get('sonar_host'), config.get('sonar_token'), config.get('sources_path'), config.get('exclusions'), config.get('test_inclusions'), repo_id))
        else:
            db.insert("INSERT INTO sonar_configs (repo_id, sonar_project_key, sonar_project_name, sonar_host, sonar_token, sources_path, exclusions, test_inclusions, is_configured) VALUES (%s,%s,%s,%s,%s,%s,%s,%s, TRUE)", (repo_id, config.get('sonar_project_key'), config.get('sonar_project_name'), config.get('sonar_host'), config.get('sonar_token'), config.get('sources_path'), config.get('exclusions'), config.get('test_inclusions')))
        return True
