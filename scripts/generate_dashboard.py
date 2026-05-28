#!/usr/bin/env python3
"""
Generate a comprehensive HTML dashboard from SonarQube + Gemini AI review.

Usage:
    python3 generate_dashboard.py \
        sonar_raw.json \
        sonar_filtered.json \
        gemini_review.json \
        output.html \
        "Project Name" \
        "20250118_143022"
"""

import json
import sys
import os
from datetime import datetime
from html import escape


def load_json(path):
    """Safely load a JSON file."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️  Could not load {path}: {e}")
        return {}


def esc(text):
    """HTML-escape text safely."""
    if text is None:
        return ''
    return escape(str(text))


def severity_color(severity):
    colors = {
        'BLOCKER': '#ff1744', 'CRITICAL': '#ff5252',
        'HIGH': '#ff6d00', 'MAJOR': '#ffa726',
        'MEDIUM': '#ffd600', 'MINOR': '#69f0ae',
        'LOW': '#69f0ae', 'INFO': '#90a4ae'
    }
    return colors.get(str(severity).upper(), '#90a4ae')


def verdict_style(verdict):
    styles = {
        'CONFIRMED': ('✅', '#4caf50', 'Real Issue'),
        'FALSE_POSITIVE': ('❌', '#78909c', 'False Positive'),
        'ESCALATED': ('⬆️', '#ff5252', 'Escalated — Worse Than Reported')
    }
    return styles.get(verdict, ('❓', '#90a4ae', verdict))


def category_icon(category):
    icons = {
        'RACE_CONDITION': '🏎️', 'GOROUTINE_LEAK': '💧',
        'CHANNEL_DEADLOCK': '🔒', 'PARTIAL_FAILURE': '💔',
        'IDEMPOTENCY': '🔄', 'ERROR_HANDLING': '⚠️',
        'NIL_SAFETY': '🕳️', 'CONTEXT_MISUSE': '🧭',
        'PERFORMANCE': '⚡', 'SECURITY': '🛡️',
        'BUSINESS_LOGIC': '💰', 'DEFER_BUG': '📌',
        'CONCURRENCY': '🔀'
    }
    return icons.get(str(category).upper(), '📌')


def generate_html(sonar_raw, sonar_filtered, gemini_review,
                    project_name, timestamp, review_id=None):
    """Generate the complete HTML report."""    
    # Extract data
    ai = gemini_review
    assessment = ai.get('assessment', {})
    sonar_validations = ai.get('sonarValidation', [])
    logical_findings = ai.get('logicalFindings', [])
    suggested_tests = ai.get('suggestedTests', [])
    
    raw_issues = sonar_raw.get('issues', [])
    filtered_meta = sonar_filtered.get('metadata', {})
    filtered_summary = sonar_filtered.get('summary', {})
    filtered_issues = sonar_filtered.get('issues', [])
    files_affected = sonar_filtered.get('files_affected', [])
    
    confirmed = [v for v in sonar_validations if v.get('verdict') == 'CONFIRMED']
    false_pos = [v for v in sonar_validations if v.get('verdict') == 'FALSE_POSITIVE']
    escalated = [v for v in sonar_validations if v.get('verdict') == 'ESCALATED']
    
    risk = assessment.get('overallRisk', 'UNKNOWN')
    recommendation = assessment.get('recommendation', 'UNKNOWN')
    
    risk_colors = {
        'LOW': '#4caf50', 'MEDIUM': '#ffa726', 
        'HIGH': '#ff5252', 'CRITICAL': '#ff1744',
        'UNKNOWN': '#78909c'
    }
    rec_colors = {
        'APPROVE': '#4caf50', 'REQUEST_CHANGES': '#ff5252',
        'NEEDS_DISCUSSION': '#ffa726'
    }
    
    total_real_issues = len(confirmed) + len(escalated) + len(logical_findings)
    
    # Sort logical findings by severity
    sev_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
    logical_findings.sort(key=lambda x: sev_order.get(x.get('severity', 'LOW'), 99))
    
    # Build HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Code Review — {esc(project_name)}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
    --bg-0: #0d1117; --bg-1: #161b22; --bg-2: #21262d; --bg-3: #30363d;
    --border: #30363d; --text-1: #e6edf3; --text-2: #8b949e; --text-3: #6e7681;
    --blue: #58a6ff; --green: #3fb950; --red: #f85149; --yellow: #d29922;
    --orange: #f0883e; --purple: #bc8cff;
}}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: var(--bg-0); color: var(--text-1); line-height: 1.6; }}

.header {{ background: linear-gradient(135deg, #1a1e2e, #0d1117);
           border-bottom: 1px solid var(--border); padding: 32px 40px; }}
.header h1 {{ font-size: 26px; font-weight: 600; }}
.header .meta {{ color: var(--text-2); font-size: 13px; margin-top: 8px; }}
.header .risk-badge {{ display: inline-block; padding: 6px 20px; border-radius: 20px;
                       font-weight: 700; font-size: 14px; margin-top: 12px; }}

.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
         gap: 14px; padding: 24px 40px; }}
.card {{ background: var(--bg-1); border: 1px solid var(--border); border-radius: 8px;
         padding: 18px; text-align: center; }}
.card .lbl {{ color: var(--text-3); font-size: 11px; text-transform: uppercase;
              letter-spacing: 0.5px; margin-bottom: 6px; }}
.card .val {{ font-size: 28px; font-weight: 700; }}
.card .sub {{ color: var(--text-3); font-size: 11px; margin-top: 4px; }}

.content {{ width: 100%; margin: 0 auto; padding: 0 40px 40px; }}
.section {{ background: var(--bg-1); border: 1px solid var(--border);
            border-radius: 8px; margin-bottom: 20px; overflow: hidden; }}
.sec-head {{ padding: 14px 20px; border-bottom: 1px solid var(--border);
             display: flex; align-items: center; gap: 10px; }}
.sec-head h2 {{ font-size: 15px; font-weight: 600; }}
.badge {{ background: var(--bg-2); color: var(--text-2); padding: 2px 10px;
          border-radius: 10px; font-size: 11px; margin-left: auto; }}
.sec-body {{ padding: 18px 20px; }}

.summary-box {{ background: var(--bg-2); border-radius: 6px; padding: 16px;
                margin-bottom: 14px; font-size: 14px; line-height: 1.7; }}
.positive {{ color: var(--green); padding: 4px 0; }}

.finding {{ border: 1px solid var(--border); border-radius: 6px;
            margin-bottom: 14px; overflow: hidden; }}
.finding-head {{ padding: 12px 16px; display: flex; align-items: center;
                 gap: 10px; border-bottom: 1px solid var(--border); }}
.finding-head.critical {{ background: rgba(248,81,73,.08); border-left: 4px solid var(--red); }}
.finding-head.high {{ background: rgba(240,136,62,.08); border-left: 4px solid var(--orange); }}
.finding-head.medium {{ background: rgba(210,153,34,.08); border-left: 4px solid var(--yellow); }}
.finding-head.low {{ background: rgba(63,185,80,.08); border-left: 4px solid var(--green); }}
.finding-body {{ padding: 14px 16px; }}
.finding-body p {{ margin-bottom: 10px; color: var(--text-2); font-size: 13px; }}
.finding-meta {{ display: flex; gap: 14px; color: var(--text-3); font-size: 11px;
                 flex-wrap: wrap; margin-bottom: 10px; }}

.sev-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 10px;
              font-weight: 700; text-transform: uppercase; color: #fff; }}

pre {{ background: var(--bg-0); border: 1px solid var(--border); border-radius: 6px;
       padding: 14px; overflow-x: auto; font-family: 'SF Mono','Fira Code',monospace;
       font-size: 12px; line-height: 1.5; margin: 10px 0; white-space: pre-wrap;
       word-wrap: break-word; }}
pre.bad {{ border-left: 3px solid var(--red); }}
pre.good {{ border-left: 3px solid var(--green); }}
pre.test {{ border-left: 3px solid var(--purple); }}
code {{ font-family: 'SF Mono','Fira Code',monospace; background: var(--bg-2);
        padding: 2px 5px; border-radius: 3px; font-size: 12px; }}

table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ padding: 8px 14px; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ background: var(--bg-2); color: var(--text-3); font-size: 11px;
      text-transform: uppercase; letter-spacing: 0.5px; }}
td code {{ font-size: 11px; }}

details {{ border: 1px solid var(--border); border-radius: 6px; margin-bottom: 10px; }}
details summary {{ padding: 10px 14px; cursor: pointer; font-weight: 500;
                   background: var(--bg-2); font-size: 13px; }}
details[open] summary {{ border-bottom: 1px solid var(--border); }}
details .det-body {{ padding: 14px; }}

.footer {{ padding: 20px 40px; border-top: 1px solid var(--border);
           color: var(--text-3); font-size: 11px; text-align: center; }}

.bar {{ width: 100%; height: 6px; background: var(--bg-2); border-radius: 3px;
        margin-top: 6px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 3px; }}

@media print {{ body {{ background: #fff; color: #1a1a1a; }}
                .card, .section {{ border: 1px solid #ddd; }}
                pre {{ background: #f5f5f5; }} }}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
    <h1>🤖 AI Code Review Report</h1>
    <div class="meta">
        {esc(project_name)} &nbsp;|&nbsp; 
        {datetime.now().strftime('%B %d, %Y at %H:%M')} &nbsp;|&nbsp;
        Timestamp: {esc(timestamp)}
    </div>
    <div class="risk-badge" style="background:{risk_colors.get(risk,'#78909c')}; color:#fff;">
        {esc(risk)} RISK — {esc(recommendation)}
    </div>
</div>

<!-- DASHBOARD CARDS -->
<div class="grid">
    <div class="card">
        <div class="lbl">Overall Risk</div>
        <div class="val" style="color:{risk_colors.get(risk,'#78909c')}">{esc(risk)}</div>
        <div class="sub">{esc(recommendation)}</div>
    </div>
    <div class="card">
        <div class="lbl">SonarQube Issues</div>
        <div class="val">{filtered_meta.get('original_issue_count', len(raw_issues))}</div>
        <div class="sub">{filtered_meta.get('filtered_issue_count', len(filtered_issues))} sent to AI</div>
    </div>
    <div class="card">
        <div class="lbl">Real Issues</div>
        <div class="val" style="color:{'var(--red)' if total_real_issues > 0 else 'var(--green)'}">{total_real_issues}</div>
        <div class="sub">{len(confirmed)} confirmed + {len(logical_findings)} AI-found</div>
    </div>
    <div class="card">
        <div class="lbl">False Positives</div>
        <div class="val" style="color:var(--green)">{len(false_pos)}</div>
        <div class="sub">SonarQube noise removed by AI</div>
    </div>
    <div class="card">
        <div class="lbl">Escalated</div>
        <div class="val" style="color:var(--red)">{len(escalated)}</div>
        <div class="sub">Worse than SonarQube thinks</div>
    </div>
    <div class="card">
        <div class="lbl">Files Affected</div>
        <div class="val">{len(files_affected)}</div>
        <div class="sub">{filtered_summary.get('bugs',0)} bugs, {filtered_summary.get('vulnerabilities',0)} vulns</div>
    </div>
</div>

<div class="content">

<!-- SUMMARY -->
<div class="section">
    <div class="sec-head"><span>📝</span><h2>Executive Summary</h2></div>
    <div class="sec-body">
        <div class="summary-box">{esc(assessment.get('summary', 'No summary available.'))}</div>
'''

    # Positives
    positives = assessment.get('positives', [])
    if positives:
        for p in positives:
            html += f'        <div class="positive">✨ {esc(p)}</div>\n'

    # Top Risks
    top_risks = assessment.get('topRisks', [])
    if top_risks:
        html += '        <h3 style="margin-top:14px;color:var(--yellow);font-size:14px;">⚠️ Top Risks</h3>\n'
        html += '        <ul style="padding-left:20px;margin-top:6px;">\n'
        for r in top_risks:
            html += f'            <li style="color:var(--text-2);font-size:13px;margin:4px 0;">{esc(r)}</li>\n'
        html += '        </ul>\n'

    html += '    </div>\n</div>\n'

    # ── ESCALATED ISSUES ──
    if escalated:
        html += f'''
<div class="section">
    <div class="sec-head"><span>🚨</span><h2>Escalated Issues</h2>
        <span class="badge" style="background:var(--red);color:#fff;">{len(escalated)}</span></div>
    <div class="sec-body">
        <p style="color:var(--text-3);margin-bottom:14px;font-size:12px;">
            SonarQube flagged these but AI determined they are MORE SEVERE than reported.</p>
'''
        for v in escalated:
            html += _render_validation(v, 'critical')
        html += '    </div>\n</div>\n'

    # ── RISK PREDICTIONS ──
    risk_predictions = ai.get('riskPredictions', {})
    if risk_predictions and risk_predictions.get('predictions'):
        html += f'''
<div class="section">
    <div class="sec-head">
        <h2 style="color: var(--primary);">🔮 Neural Risk Predictor</h2>
    </div>
    <div class="sec-body" style="background: linear-gradient(135deg, #f8fafc 0%, #ffffff 100%);">
        <div style="font-size: 13px; color: var(--text-2); margin-bottom: 20px; font-weight: 600;">Future Bug Probability Analysis</div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 20px;">
'''
        for pred in risk_predictions.get('predictions', []):
            p_risk = pred.get('risk', 'MEDIUM')
            border_color = risk_colors.get(p_risk, '#ffb300')
            html += f'''
            <div style="background: #fff; border: 1px solid var(--border); border-top: 4px solid {border_color}; border-radius: 8px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.02);">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 12px;">
                    <code style="font-size: 11px; color: var(--text-1); word-break: break-all;">{esc(pred.get('file', ''))}</code>
                    <span style="background: {border_color}20; color: {border_color}; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 12px;">{esc(p_risk)} RISK</span>
                </div>
                <div style="font-size: 13px; line-height: 1.5; color: var(--text-2); margin-bottom: 16px;">{esc(pred.get('reason', ''))}</div>
                <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px dashed var(--border); padding-top: 12px;">
                    <span style="font-size: 10px; font-weight: 700; color: var(--text-2); text-transform: uppercase;">Probability</span>
                    <span style="font-size: 16px; font-weight: 800; color: var(--text-1); font-family: monospace;">{esc(pred.get('probability', ''))}</span>
                </div>
            </div>
'''
        html += '        </div>'
        
        rec = risk_predictions.get('recommendation')
        if rec:
            html += f'''
        <div style="background: rgba(99, 102, 241, 0.05); border: 1px solid rgba(99, 102, 241, 0.2); border-radius: 8px; padding: 16px;">
            <div style="font-size: 11px; font-weight: 800; color: var(--primary); text-transform: uppercase; margin-bottom: 8px;">Strategic Recommendation</div>
            <div style="font-size: 14px; line-height: 1.6; color: var(--text-1);">{esc(rec)}</div>
        </div>
'''
        html += '    </div>\n</div>\n'

    # ── AI LOGICAL FINDINGS ──
    if logical_findings:
        html += f'''
<div class="section">
    <div class="sec-head"><span>🤖</span><h2>AI-Discovered Logical Issues</h2>
        <span class="badge">{len(logical_findings)} issues SonarQube cannot detect</span></div>
    <div class="sec-body">
'''
        for f in logical_findings:
            sev = f.get('severity', 'MEDIUM').upper()
            sev_lower = sev.lower()
            cat = f.get('category', '')
            icon = category_icon(cat)
            conf = f.get('confidence', 0)
            if isinstance(conf, str):
                try: conf = float(conf)
                except: conf = 0.7

            html += f'''
        <div class="finding">
            <div class="finding-head {sev_lower}">
                <span class="sev-badge" style="background:{severity_color(sev)}">{esc(sev)}</span>
                <span>{icon}</span>
                <strong style="font-size:14px;">{esc(f.get('title', 'Issue'))}</strong>
            </div>
            <div class="finding-body">
                <div class="finding-meta">
                    <span>📄 <code>{esc(f.get('file', '?'))}:{esc(str(f.get('lineStart', '?')))}</code></span>
                    <span>🏷️ {esc(cat)}</span>
                    <span>🎯 Confidence: {int(conf * 100) if isinstance(conf, float) else conf}%</span>
                    {f'<span>📏 Standard: {esc(f.get("standard", ""))}</span>' if f.get('standard') else ''}
                </div>
                <p><strong>The Logic Failure:</strong></p>
                <div class="summary-box" style="white-space:pre-wrap;font-size:12px;">{esc(f.get('theLogicFailure', f.get('description', 'N/A')))}</div>
'''
            if f.get('currentCode'):
                html += f'                <p><strong>Current Code:</strong></p>\n'
                html += f'                <pre class="bad">{esc(f["currentCode"])}</pre>\n'

            if f.get('thePrincipalFix'):
                html += f'                <p><strong>The Principal Fix:</strong></p>\n'
                html += f'                <pre class="good">{esc(f["thePrincipalFix"])}</pre>\n'

            if f.get('proofTest'):
                html += f'''
                <details>
                    <summary>🧪 Proof Test (click to expand)</summary>
                    <div class="det-body"><pre class="test">{esc(f["proofTest"])}</pre></div>
                </details>
'''
            if f.get('productionImpact'):
                html += f'                <p style="color:var(--orange);font-size:12px;">💥 <strong>Production Impact:</strong> {esc(f["productionImpact"])}</p>\n'

            html += '            </div>\n        </div>\n'

        html += '    </div>\n</div>\n'

    # ── CONFIRMED SONARQUBE ISSUES ──
    if confirmed:
        html += f'''
<div class="section">
    <div class="sec-head"><span>✅</span><h2>Confirmed SonarQube Issues</h2>
        <span class="badge">{len(confirmed)} verified real</span></div>
    <div class="sec-body">
'''
        for v in confirmed:
            html += _render_validation(v, 'medium')
        html += '    </div>\n</div>\n'

    # ── FALSE POSITIVES ──
    if false_pos:
        html += f'''
<div class="section">
    <div class="sec-head"><span>❌</span><h2>False Positives — Safe to Ignore</h2>
        <span class="badge" style="background:var(--green);color:#000;">{len(false_pos)} dismissed</span></div>
    <div class="sec-body">
        <details>
            <summary>{len(false_pos)} SonarQube alerts dismissed by AI (click to expand)</summary>
            <div class="det-body">
                <table>
                    <thead><tr><th>File</th><th>Line</th><th>Rule</th><th>Why It's Safe</th></tr></thead>
                    <tbody>
'''
        for v in false_pos:
            html += f'''                        <tr>
                            <td><code>{esc(v.get('file', '?'))}</code></td>
                            <td>{esc(str(v.get('line', '?')))}</td>
                            <td><code>{esc(v.get('sonarRule', ''))}</code></td>
                            <td style="font-size:12px;">{esc(v.get('explanation', ''))}</td>
                        </tr>
'''
        html += '''                    </tbody>
                </table>
            </div>
        </details>
    </div>
</div>
'''

    # ── SONARQUBE METRICS ──
    html += f'''
<div class="section">
    <div class="sec-head"><span>📊</span><h2>SonarQube Breakdown</h2></div>
    <div class="sec-body">
        <div class="grid" style="padding:0;">
            <div class="card">
                <div class="lbl">Bugs</div>
                <div class="val" style="color:{'var(--red)' if filtered_summary.get('bugs',0) > 0 else 'var(--green)'}">
                    {filtered_summary.get('bugs', 0)}</div>
            </div>
            <div class="card">
                <div class="lbl">Vulnerabilities</div>
                <div class="val" style="color:{'var(--red)' if filtered_summary.get('vulnerabilities',0) > 0 else 'var(--green)'}">
                    {filtered_summary.get('vulnerabilities', 0)}</div>
            </div>
            <div class="card">
                <div class="lbl">Code Smells</div>
                <div class="val" style="color:var(--yellow)">{filtered_summary.get('code_smells', 0)}</div>
            </div>
            <div class="card">
                <div class="lbl">Blockers</div>
                <div class="val" style="color:{'var(--red)' if filtered_summary.get('blockers',0) > 0 else 'var(--green)'}">
                    {filtered_summary.get('blockers', 0)}</div>
            </div>
        </div>
    </div>
</div>
'''

    # ── FILES TABLE ──
    if files_affected:
        html += '''
<div class="section">
    <div class="sec-head"><span>📁</span><h2>Affected Files</h2></div>
    <div class="sec-body">
        <details>
            <summary>''' + str(len(files_affected)) + ''' files with issues</summary>
            <div class="det-body">
                <table>
                    <thead><tr><th>File</th><th>Issues</th><th>Severities</th></tr></thead>
                    <tbody>
'''
        # Count issues per file
        file_issues = {}
        for issue in filtered_issues:
            fp = issue.get('file', '?')
            if fp not in file_issues:
                file_issues[fp] = {'count': 0, 'severities': set()}
            file_issues[fp]['count'] += 1
            file_issues[fp]['severities'].add(issue.get('severity', '?'))

        for fp in files_affected:
            fi = file_issues.get(fp, {'count': 0, 'severities': set()})
            sev_badges = ' '.join(
                f'<span class="sev-badge" style="background:{severity_color(s)};font-size:9px;">{s}</span>'
                for s in sorted(fi['severities'])
            )
            html += f'''                        <tr>
                            <td><code>{esc(fp)}</code></td>
                            <td>{fi['count']}</td>
                            <td>{sev_badges}</td>
                        </tr>
'''
        html += '''                    </tbody>
                </table>
            </div>
        </details>
    </div>
</div>
'''

    # ── ALL SONARQUBE ISSUES TABLE ──
    html += f'''
<div class="section">
    <div class="sec-head"><span>📋</span><h2>All SonarQube Issues</h2></div>
    <div class="sec-body">
        <details>
            <summary>{len(filtered_issues)} issues (filtered, sorted by severity)</summary>
            <div class="det-body">
                <table>
                    <thead><tr><th>Severity</th><th>Type</th><th>File</th><th>Line</th><th>Message</th><th>AI Verdict</th></tr></thead>
                    <tbody>
'''
    # Build verdict lookup
    verdict_lookup = {}
    for v in sonar_validations:
        key = f"{v.get('file','')}:{v.get('line','')}"
        verdict_lookup[key] = v.get('verdict', '—')

    for issue in filtered_issues:
        sev = issue.get('severity', '?')
        key = f"{issue.get('file','')}:{issue.get('line', '')}"
        v = verdict_lookup.get(key, '—')
        v_icon, v_color, _ = verdict_style(v) if v != '—' else ('—', '#78909c', '—')

        html += f'''                        <tr>
                            <td><span class="sev-badge" style="background:{severity_color(sev)}">{esc(sev)}</span></td>
                            <td>{esc(issue.get('type', '?'))}</td>
                            <td><code>{esc(issue.get('file', '?'))}</code></td>
                            <td>{issue.get('line', '?')}</td>
                            <td style="font-size:12px;">{esc(issue.get('message', '')[:120])}</td>
                            <td style="color:{v_color}">{v_icon} {esc(v)}</td>
                        </tr>
'''
    html += '''                    </tbody>
                </table>
            </div>
        </details>
    </div>
</div>
'''
# ── RAW AI REVIEW (if structured parsing failed) ──
    raw_review = gemini_review.get('rawReview', '')
    if raw_review and not logical_findings and not sonar_validations:
        html += f'''
<div class="section">
    <div class="sec-head"><span>🤖</span><h2>AI Review (Raw Output)</h2>
        <span class="badge" style="background:var(--orange);color:#000;">Parsing could not extract structured data</span></div>
    <div class="sec-body">
        <p style="color:var(--text-3);margin-bottom:10px;font-size:12px;">
            The AI review output could not be parsed into structured findings. 
            The raw review is shown below. Consider adjusting the prompt or using the Python API instead of CLI.</p>
        <div class="summary-box" style="white-space:pre-wrap;font-size:12px;max-height:800px;overflow-y:auto;">
{esc(raw_review)}
        </div>
    </div>
</div>
'''
        
    # ── FOOTER ──
    html += f'''
</div>

<div class="footer">
    <p>🤖 <strong>AI Code Review</strong> — SonarQube + Google Gemini &nbsp;|&nbsp;
       {esc(project_name)} &nbsp;|&nbsp;
       Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p style="margin-top:4px;">
       SonarQube: {filtered_meta.get('original_issue_count', '?')} issues →
       Filtered: {filtered_meta.get('filtered_issue_count', '?')} →
       AI validated: {len(sonar_validations)} →
       AI discovered: {len(logical_findings)} additional
    </p>
</div>

</body>
</html>'''

    return html


def _render_validation(v, default_class='medium'):
    """Render a single SonarQube validation finding."""
    conf = v.get('confidence', 0)
    if isinstance(conf, str):
        try: conf = float(conf)
        except: conf = 0.7

    cls = 'critical' if v.get('verdict') == 'ESCALATED' else default_class

    html = f'''
        <div class="finding">
            <div class="finding-head {cls}">
                <span class="sev-badge" style="background:{severity_color(v.get('verdict','MAJOR'))}">{esc(v.get('verdict', '?'))}</span>
                <strong>{esc(v.get('file', '?'))}:{esc(str(v.get('line', '?')))}</strong>
                <code style="margin-left:auto;font-size:11px;">{esc(v.get('sonarRule', ''))}</code>
            </div>
            <div class="finding-body">
                <div class="finding-meta">
                    <span>🎯 Confidence: {int(conf * 100) if isinstance(conf, float) else conf}%</span>
                    {f'<span>📏 {esc(v.get("standard", ""))}</span>' if v.get('standard') else ''}
                </div>
                <p><strong>Analysis:</strong> {esc(v.get('explanation', 'N/A'))}</p>
'''
    if v.get('productionImpact'):
        html += f'                <p style="color:var(--orange);font-size:12px;">💥 <strong>Impact:</strong> {esc(v["productionImpact"])}</p>\n'

    if v.get('fix'):
        html += f'                <details>\n'
        html += f'                    <summary>🔧 Fix (click to expand)</summary>\n'
        html += f'                    <div class="det-body"><pre class="good">{esc(v["fix"])}</pre></div>\n'
        html += f'                </details>\n'

    html += '            </div>\n        </div>\n'
    return html


def main():
    if len(sys.argv) < 5:
        print("Usage: generate_dashboard.py <sonar_raw.json> <sonar_filtered.json> "
              "<gemini_review.json> <output.html> [project_name] [timestamp]")
        sys.exit(1)

    sonar_raw_path = sys.argv[1]
    sonar_filtered_path = sys.argv[2]
    gemini_path = sys.argv[3]
    output_path = sys.argv[4]
    project_name = sys.argv[5] if len(sys.argv) > 5 else "Code Review"
    timestamp = sys.argv[6] if len(sys.argv) > 6 else datetime.now().strftime('%Y%m%d_%H%M%S')

    # Load data
    sonar_raw = load_json(sonar_raw_path)
    sonar_filtered = load_json(sonar_filtered_path)
    gemini_review = load_json(gemini_path)

    # Generate HTML
    html = generate_html(sonar_raw, sonar_filtered, gemini_review, 
                          project_name, timestamp)

    # Write output
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    size_kb = round(os.path.getsize(output_path) / 1024, 1)
    print(f"  ✅ Report generated: {output_path} ({size_kb} KB)")


if __name__ == '__main__':
    main()