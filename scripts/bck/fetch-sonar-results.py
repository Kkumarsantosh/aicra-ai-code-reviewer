#!/usr/bin/env python3
# scripts/fetch-sonar-results.py
# Piece 2: Takes SonarQube results and builds a smart context package for AI.

import os
import json
import requests
import subprocess
import sys
import argparse
from datetime import datetime

def log(msg):
    print(f"DEBUG: {msg}", file=sys.stderr)

def load_env():
    script_dir = os.path.dirname(os.path.realpath(__file__))
    project_root = os.path.dirname(script_dir)
    env_path = os.path.join(project_root, '.env')
    
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    try:
                        key, value = line.strip().split('=', 1)
                        os.environ[key] = value.strip().strip("'").strip('"')
                    except ValueError:
                        continue

def fetch_sonar_results(project_key, pr_number=None):
    sonar_host = os.environ.get('SONAR_HOST_URL', 'http://localhost:9000').rstrip('/')
    sonar_token = os.environ.get('SONAR_TOKEN')
    sonar_edition = os.environ.get('SONAR_EDITION', 'community').lower()
    
    headers = {"Authorization": f"Bearer {sonar_token}"}
    base_params = {"componentKeys": project_key}
    
    # Only use pullRequest parameter if NOT on Community Edition
    is_community = sonar_edition == "community"
    
    if pr_number and pr_number != "0" and not is_community:
        base_params["pullRequest"] = str(pr_number)
    
    results = {
        "issues": [],
        "metrics": {},
        "quality_gate": {"status": "NONE"},
        "issue_map": {},
        "summary": {}
    }
    
    try:
        # Fetch Issues
        issues_url = f"{sonar_host}/api/issues/search"
        issues_params = {**base_params, "resolved": "false", "ps": 500}
        resp = requests.get(issues_url, params=issues_params, headers=headers, timeout=30)
        
        if resp.status_code == 200:
            raw_issues = resp.json().get('issues', [])
            for issue in raw_issues:
                # Component is often "project_key:file_path"
                file_path = issue.get('component', '').split(':')[-1]
                parsed_issue = {
                    "rule": issue.get('rule'),
                    "severity": issue.get('severity'),
                    "type": issue.get('type'),
                    "message": issue.get('message'),
                    "file": file_path,
                    "line": issue.get('line', issue.get('textRange', {}).get('startLine', 0))
                }
                results["issues"].append(parsed_issue)
                if file_path not in results["issue_map"]:
                    results["issue_map"][file_path] = {"filename": file_path, "issues": []}
                results["issue_map"][file_path]["issues"].append(parsed_issue)
            
        # Fetch Metrics
        measures_url = f"{sonar_host}/api/measures/component"
        measures_params = {
            "component": project_key,
            "metricKeys": "coverage,duplicated_lines_density,bugs,vulnerabilities,code_smells,ncloc"
        }
        if pr_number and pr_number != "0" and not is_community:
            measures_params["pullRequest"] = pr_number
            
        resp = requests.get(measures_url, params=measures_params, headers=headers, timeout=10)
        if resp.status_code == 200:
            for m in resp.json().get('component', {}).get('measures', []):
                results["metrics"][m['metric']] = m['value']
        
        # Quality Gate
        qg_url = f"{sonar_host}/api/qualitygates/project_status"
        qg_params = {"projectKey": project_key}
        if pr_number and pr_number != "0" and not is_community:
            qg_params["pullRequest"] = pr_number
        resp = requests.get(qg_url, params=qg_params, headers=headers, timeout=10)
        if resp.status_code == 200:
            results["quality_gate"]["status"] = resp.json().get('projectStatus', {}).get('status', 'NONE')

        results["summary"] = {
            "total_issues": len(results["issues"]),
            "bugs": len([i for i in results["issues"] if i["type"] == "BUG"]),
            "vulnerabilities": len([i for i in results["issues"] if i["type"] == "VULNERABILITY"]),
            "code_smells": len([i for i in results["issues"] if i["type"] == "CODE_SMELL"]),
            "coverage": results["metrics"].get("coverage", 0)
        }
    except Exception as e:
        log(f"Error fetching Sonar results: {str(e)}")
        
    return results

def build_context_package(results, repo_url, branch):
    workspace = os.environ.get('WORKSPACE_PATH', '/tmp')
    github_token = os.environ.get('GITHUB_TOKEN')
    
    ctx_id = datetime.now().strftime("%H%M%S")
    repo_dir = os.path.join(workspace, f"ctx-{ctx_id}")
    
    clone_url = repo_url
    if github_token and "github.com" in repo_url:
        clone_url = repo_url.replace("https://github.com", f"https://{github_token}@github.com")
        
    try:
        subprocess.run(["git", "clone", "--depth", "1", "--branch", branch, clone_url, repo_dir], 
                       capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        log(f"Git clone failed: {e.stderr.decode()}")
        return []
    
    context_packages = []
    CONTEXT_LINES = 15
    
    for filename, file_data in results["issue_map"].items():
        file_path = os.path.join(repo_dir, filename)
        if not os.path.exists(file_path):
            continue
            
        try:
            with open(file_path, 'r', errors='replace') as f:
                lines = f.readlines()
                
            package = {
                "filename": filename,
                "sonar_findings": file_data["issues"],
                "code_blocks": []
            }
            
            processed_lines = set()
            for issue in file_data["issues"]:
                line_num = issue["line"]
                if line_num <= 0 or line_num in processed_lines: continue
                
                start = max(0, line_num - CONTEXT_LINES - 1)
                end = min(len(lines), line_num + CONTEXT_LINES)
                
                code_segment = ""
                for i in range(start, end):
                    curr_line = i + 1
                    marker = " >>> " if curr_line == line_num else "     "
                    code_segment += f"{curr_line:4d}{marker}{lines[i]}"
                    
                package["code_blocks"].append({
                    "line_start": start + 1,
                    "line_end": end,
                    "code": code_segment
                })
                processed_lines.add(line_num)
            context_packages.append(package)
        except Exception:
            continue
        
    subprocess.run(["rm", "-rf", repo_dir])
    return context_packages

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--pr", default=None)
    args = parser.parse_args()
    
    load_env()
    
    results = fetch_sonar_results(args.project, args.pr)
    context = build_context_package(results, args.repo, args.branch)
    
    output = {
        "scan_summary": results["summary"],
        "quality_gate": results["quality_gate"],
        "metrics": results["metrics"],
        "context_packages": context,
        "pr_metadata": {"project": args.project, "repo": args.repo, "branch": args.branch, "pr": args.pr}
    }
    
    print("--- CONTEXT_START ---")
    print(json.dumps(output, indent=2))
    print("--- CONTEXT_END ---")
