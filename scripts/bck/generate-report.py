#!/usr/bin/env python3
# scripts/generate-report.py
# Piece 4: Final Report Builder that generates an HTML report.

import os
import json
import sys
from datetime import datetime

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

def generate_html(ai_review):
    assessment = ai_review.get('assessment', {})
    sonar_val = ai_review.get('sonarValidation', [])
    add_findings = ai_review.get('additionalFindings', [])
    
    risk = assessment.get('risk', 'MEDIUM')
    risk_colors = {'LOW': '#27ae60', 'MEDIUM': '#f39c12', 'HIGH': '#e67e22', 'CRITICAL': '#e74c3c'}
    risk_color = risk_colors.get(risk, '#f39c12')
    
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>AI Code Review Report</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; background-color: #f8f9fa; color: #333; }}
        .header {{ background-color: #2c3e50; color: white; padding: 2rem; text-align: center; }}
        .container {{ max-width: 1000px; margin: 2rem auto; padding: 0 1rem; }}
        .card {{ background: white; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 2rem; padding: 1.5rem; }}
        .summary-header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #eee; padding-bottom: 1rem; margin-bottom: 1rem; }}
        .risk-badge {{ padding: 0.5rem 1rem; border-radius: 20px; color: white; font-weight: bold; text-transform: uppercase; }}
        .finding {{ border: 1px solid #ddd; border-radius: 6px; margin-bottom: 1rem; overflow: hidden; }}
        .finding-header {{ padding: 0.75rem 1rem; background-color: #f1f3f5; border-bottom: 1px solid #ddd; font-weight: bold; display: flex; justify-content: space-between; }}
        .finding-body {{ padding: 1rem; }}
        .CONFIRMED {{ border-left: 5px solid #e74c3c; }}
        .FALSE_POSITIVE {{ border-left: 5px solid #27ae60; opacity: 0.7; }}
        .ESCALATED {{ border-left: 5px solid #8e44ad; }}
        .CRITICAL {{ border-left: 5px solid #c0392b; }}
        .HIGH {{ border-left: 5px solid #e67e22; }}
        pre {{ background-color: #282c34; color: #abb2bf; padding: 1rem; border-radius: 4px; overflow-x: auto; font-family: 'Consolas', 'Monaco', monospace; font-size: 0.9rem; }}
        .fix-label {{ color: #27ae60; font-weight: bold; margin-top: 1rem; display: block; }}
        .positives {{ color: #27ae60; }}
        .footer {{ text-align: center; color: #7f8c8d; font-size: 0.8rem; margin-top: 3rem; padding-bottom: 2rem; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>AI Code Review Insights</h1>
        <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <div class="container">
        <div class="card">
            <div class="summary-header">
                <h2>Executive Summary</h2>
                <span class="risk-badge" style="background-color: {risk_color}">{risk} RISK</span>
            </div>
            <p><strong>Recommendation:</strong> {assessment.get('recommendation', 'N/A')}</p>
            <p>{assessment.get('summary', '')}</p>
            
            <h3>Strengths</h3>
            <ul class="positives">
                {"".join(f"<li>{p}</li>" for p in assessment.get('positives', []))}
            </ul>
        </div>
        
        <h2>SonarQube Analysis Validation</h2>
        """
    for v in sonar_val:
        html += f"""
        <div class="finding {v.get('verdict')}">
            <div class="finding-header">
                <span>{v.get('file')}:{v.get('line')}</span>
                <span>{v.get('verdict')}</span>
            </div>
            <div class="finding-body">
                <p><strong>Rule:</strong> {v.get('sonarRule')}</p>
                <p>{v.get('explanation')}</p>
                {f'<span class="fix-label">Suggested Fix:</span><pre><code>{v.get("fix")}</code></pre>' if v.get('fix') else ''}
            </div>
        </div>"""
            
    html += "<h2>Additional AI Discoveries</h2>"
    for f in add_findings:
        html += f"""
        <div class="finding {f.get('severity')}">
            <div class="finding-header">
                <span>{f.get('file')}:{f.get('line')} - {f.get('title')}</span>
                <span>{f.get('severity')}</span>
            </div>
            <div class="finding-body">
                <p><strong>Category:</strong> {f.get('category')}</p>
                <p>{f.get('description')}</p>
                {f'<span class="fix-label">Suggested Fix:</span><pre><code>{f.get("fix")}</code></pre>' if f.get('fix') else ''}
            </div>
        </div>"""
            
    html += f"""
        <div class="footer">
            Powered by Google Gemini CLI & SonarQube | {datetime.now().year}
        </div>
    </div>
</body>
</html>
    """
    return html

if __name__ == "__main__":
    load_env()
    
    input_data = sys.stdin.read()
    
    if "--- AI_REVIEW_START ---" in input_data:
        ai_json_str = input_data.split("--- AI_REVIEW_START ---")[1].split("--- AI_REVIEW_END ---")[0]
        try:
            ai_review = json.loads(ai_json_str.strip())
        except json.JSONDecodeError:
            print("Error parsing AI review JSON", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            ai_review = json.loads(input_data)
        except json.JSONDecodeError:
            print("Error: Invalid JSON input", file=sys.stderr)
            sys.exit(1)
            
    html_content = generate_html(ai_review)
    
    report_dir = os.environ.get('REPORTS_PATH', './reports')
    os.makedirs(report_dir, exist_ok=True)
    
    report_path = os.path.join(report_dir, f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html")
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
        
    print(f"Report generated: {report_path}")
    print(f"--- REPORT_PATH_START ---")
    print(report_path)
    print(f"--- REPORT_PATH_END ---")
