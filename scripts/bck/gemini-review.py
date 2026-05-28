#!/usr/bin/env python3
# scripts/gemini-review.py
# Piece 3: Google Gemini Code CLI integration.

import os
import json
import subprocess
import sys

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

def build_review_prompt(data):
    pr = data.get('pr_metadata', {})
    summary = data.get('scan_summary', {})
    packages = data.get('context_packages', [])
    
    prompt = f"""You are a senior code reviewer. SonarQube has scanned this code and found specific issues.

YOUR JOB:
1. VALIDATE each SonarQube finding: CONFIRMED (real issue), FALSE_POSITIVE (safe to ignore), ESCALATED (worse than reported)
2. Find ADDITIONAL issues SonarQube missed: logic bugs, security flaws, performance problems, error handling gaps
3. Provide FIX code for every confirmed/new issue
4. Assess overall PR risk

RESPOND WITH VALID JSON ONLY:
{{
  "sonarValidation": [
    {{
      "sonarRule": "<rule>",
      "file": "<file>",
      "line": 0,
      "verdict": "CONFIRMED|FALSE_POSITIVE|ESCALATED",
      "explanation": "<why>",
      "fix": "<corrected code>"
    }}
  ],
  "additionalFindings": [
    {{
      "category": "LOGIC|SECURITY|PERFORMANCE|ERROR_HANDLING",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "file": "<file>",
      "line": 0,
      "title": "<title>",
      "description": "<detail>",
      "fix": "<good code>"
    }}
  ],
  "assessment": {{
    "risk": "LOW|MEDIUM|HIGH|CRITICAL",
    "recommendation": "APPROVE|REQUEST_CHANGES",
    "summary": "<2-3 sentences>",
    "positives": ["<good thing>"]
  }}
}}

## PR: {pr.get('project', 'Unknown')}
## SonarQube Summary: {json.dumps(summary)}

## Files to Review:
"""
    for pkg in packages:
        prompt += f"\n### 📄 {pkg['filename']}\n"
        prompt += "**SonarQube Findings:**\n"
        for finding in pkg.get('sonar_findings', []):
            prompt += f"- [{finding.get('severity')}] Line {finding.get('line')}: {finding.get('message')}\n"
        
        prompt += "\n**Code Context:**\n"
        for block in pkg.get('code_blocks', []):
            prompt += f"```\n{block.get('code')}\n```\n"
            
    return prompt

if __name__ == "__main__":
    load_env()
    
    # Read from stdin
    input_data = sys.stdin.read()
    if "--- CONTEXT_START ---" in input_data:
        json_str = input_data.split("--- CONTEXT_START ---")[1].split("--- CONTEXT_END ---")[0]
        data = json.loads(json_str)
    else:
        try:
            data = json.loads(input_data)
        except json.JSONDecodeError:
            print("Error: Invalid JSON input", file=sys.stderr)
            sys.exit(1)
        
    prompt = build_review_prompt(data)
    
    # Call Gemini CLI
    gemini_bin = os.environ.get('GEMINI_CLI_BIN', 'gemini')
    
    # Set Google Cloud Project variables
    os.environ["GOOGLE_CLOUD_PROJECT"] = "elab-code-assist"
    os.environ["GOOGLE_CLOUD_PROJECT_ID"] = "elab-code-assist"
    
    cmd = [
        gemini_bin,
        "--prompt", prompt,
        "--output-format", "json",
        "--approval-mode", "plan"
    ]
    
    # Pass sonar data in the prompt as text
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        print(f"EXCEPTION calling Gemini CLI: {str(e)}", file=sys.stderr)
        sys.exit(1)
    
    if result.returncode != 0:
        print(f"Error calling Gemini CLI (Return Code: {result.returncode})", file=sys.stderr)
        print(f"STDOUT: {result.stdout}", file=sys.stderr)
        print(f"STDERR: {result.stderr}", file=sys.stderr)
        sys.exit(1)
        
    # Output the AI review wrapped in markers for Piece 4
    print("--- AI_REVIEW_START ---")
    print(result.stdout)
    print("--- AI_REVIEW_END ---")
