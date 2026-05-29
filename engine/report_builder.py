"""
HTML Report Builder.
Generates a self-contained dark-theme HTML report from SonarQube
metrics and AI review findings.

Can be imported by the Flask app:
    from engine.report_builder import build_html_report

Or run as a CLI tool by run-review.sh:
    python3 engine/report_builder.py sonar_raw.json sonar_filtered.json \
        gemini_review.json output.html "Project Name"
"""

import json
import sys
import os
from datetime import datetime
from html import escape


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(text):
    if text is None:
        return ''
    return escape(str(text))


def _severity_color(severity):
    return {
        'BLOCKER':  '#ff1744', 'CRITICAL': '#ff5252',
        'HIGH':     '#ff6d00', 'MAJOR':    '#ffa726',
        'MEDIUM':   '#ffd600', 'MINOR':    '#69f0ae',
        'LOW':      '#69f0ae', 'INFO':     '#90a4ae',
    }.get(str(severity).upper(), '#90a4ae')


def _verdict_style(verdict):
    return {
        'CONFIRMED':     ('✅', '#4caf50', 'Real Issue'),
        'FALSE_POSITIVE':('❌', '#78909c', 'False Positive'),
        'ESCALATED':     ('⬆️', '#ff5252', 'Escalated — Worse Than Reported'),
    }.get(verdict, ('❓', '#90a4ae', verdict))


def _category_icon(category):
    return {
        'RACE_CONDITION':   '🏎️', 'GOROUTINE_LEAK':  '💧',
        'CHANNEL_DEADLOCK': '🔒', 'PARTIAL_FAILURE': '💔',
        'IDEMPOTENCY':      '🔄', 'ERROR_HANDLING':  '⚠️',
        'NIL_SAFETY':       '🕳️', 'CONTEXT_MISUSE':  '🧭',
        'PERFORMANCE':      '⚡', 'SECURITY':        '🛡️',
        'BUSINESS_LOGIC':   '💰', 'DEFER_BUG':       '📌',
        'CONCURRENCY':      '🔀',
    }.get(str(category).upper(), '📌')


def _render_validation(v, default_class='medium'):
    """Render a single SonarQube validation card."""
    conf = v.get('confidence', 0)
    if isinstance(conf, str):
        try:
            conf = float(conf)
        except ValueError:
            conf = 0.7
    css_class = 'critical' if v.get('verdict') == 'ESCALATED' else default_class
    html = f'''
        <div class="finding">
            <div class="finding-head {css_class}">
                <span class="sev-badge" style="background:{_severity_color(v.get('verdict','MAJOR'))}">{_esc(v.get('verdict', '?'))}</span>
                <strong>{_esc(v.get('file', '?'))}:{_esc(str(v.get('line', '?')))}</strong>
                <code style="margin-left:auto;font-size:11px;">{_esc(v.get('sonarRule', ''))}</code>
            </div>
            <div class="finding-body">
                <div class="finding-meta">
                    <span>🎯 Confidence: {int(conf * 100) if isinstance(conf, float) else conf}%</span>
                    {f'<span>📏 {_esc(v.get("standard", ""))}</span>' if v.get('standard') else ''}
                </div>
                <p><strong>Analysis:</strong> {_esc(v.get('explanation', 'N/A'))}</p>
'''
    if v.get('productionImpact'):
        html += f'                <p style="color:var(--orange);font-size:12px;">💥 <strong>Impact:</strong> {_esc(v["productionImpact"])}</p>\n'
    if v.get('fix'):
        html += (
            '                <details>\n'
            '                    <summary>🔧 Fix (click to expand)</summary>\n'
            f'                    <div class="det-body"><pre class="good">{_esc(v["fix"])}</pre></div>\n'
            '                </details>\n'
        )
    html += '            </div>\n        </div>\n'
    return html


# ── Main builder ─────────────────────────────────────────────────────────────

def build_html_report(sonar_raw, sonar_filtered, gemini_review,
                      project_name, timestamp, review_id=None):
    """
    Generate a complete self-contained HTML report.

    Args:
        sonar_raw:      Raw SonarQube API response dict.
        sonar_filtered: Filtered/summarised SonarQube dict.
        gemini_review:  Parsed AI review result dict.
        project_name:   Display name for the project.
        timestamp:      Timestamp string (used in filename and header).
        review_id:      Optional DB review ID for back-links.

    Returns:
        str: Full HTML string.
    """
    ai = gemini_review
    assessment            = ai.get('assessment', {})
    sonar_validations      = ai.get('sonarValidation', [])
    logical_findings       = ai.get('logicalFindings', [])
    architectural_findings = ai.get('architecturalFindings', [])

    raw_issues       = sonar_raw.get('issues', [])
    filtered_meta    = sonar_filtered.get('metadata', {})
    filtered_summary = sonar_filtered.get('summary', {})
    filtered_issues  = sonar_filtered.get('issues', [])
    files_affected   = sonar_filtered.get('files_affected', [])

    confirmed  = [v for v in sonar_validations if v.get('verdict') == 'CONFIRMED']
    false_pos  = [v for v in sonar_validations if v.get('verdict') == 'FALSE_POSITIVE']
    escalated  = [v for v in sonar_validations if v.get('verdict') == 'ESCALATED']

    risk           = assessment.get('overallRisk', 'UNKNOWN')
    recommendation = assessment.get('recommendation', 'UNKNOWN')
    total_real     = len(confirmed) + len(escalated) + len(logical_findings)

    risk_colors = {
        'LOW':     '#4caf50', 'MEDIUM':  '#ffa726',
        'HIGH':    '#ff5252', 'CRITICAL':'#ff1744', 'UNKNOWN': '#78909c',
    }

    sev_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
    logical_findings.sort(key=lambda x: sev_order.get(x.get('severity', 'LOW'), 99))

    # ── CSS ──────────────────────────────────────────────────────────────────
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Code Review — {_esc(project_name)}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
:root {{
    --bg-0:#0d1117; --bg-1:#161b22; --bg-2:#21262d; --bg-3:#30363d;
    --border:#30363d; --text-1:#e6edf3; --text-2:#8b949e; --text-3:#6e7681;
    --blue:#58a6ff; --green:#3fb950; --red:#f85149; --yellow:#d29922;
    --orange:#f0883e; --purple:#bc8cff;
}}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        background:var(--bg-0); color:var(--text-1); line-height:1.6; }}
.header {{ background:linear-gradient(135deg,#1a1e2e,#0d1117);
           border-bottom:1px solid var(--border); padding:32px 40px; }}
.header h1 {{ font-size:26px; font-weight:600; }}
.header .meta {{ color:var(--text-2); font-size:13px; margin-top:8px; }}
.header .risk-badge {{ display:inline-block; padding:6px 20px; border-radius:20px;
                       font-weight:700; font-size:14px; margin-top:12px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
         gap:14px; padding:24px 40px; }}
.card {{ background:var(--bg-1); border:1px solid var(--border); border-radius:8px;
         padding:18px; text-align:center; }}
.card .lbl {{ color:var(--text-3); font-size:11px; text-transform:uppercase;
              letter-spacing:.5px; margin-bottom:6px; }}
.card .val {{ font-size:28px; font-weight:700; }}
.card .sub {{ color:var(--text-3); font-size:11px; margin-top:4px; }}
.content {{ width:100%; margin:0 auto; padding:0 40px 40px; }}
.section {{ background:var(--bg-1); border:1px solid var(--border);
            border-radius:8px; margin-bottom:20px; overflow:hidden; }}
.sec-head {{ padding:14px 20px; border-bottom:1px solid var(--border);
             display:flex; align-items:center; gap:10px; }}
.sec-head h2 {{ font-size:15px; font-weight:600; }}
.badge {{ background:var(--bg-2); color:var(--text-2); padding:2px 10px;
          border-radius:10px; font-size:11px; margin-left:auto; }}
.sec-body {{ padding:18px 20px; }}
.summary-box {{ background:var(--bg-2); border-radius:6px; padding:16px;
                margin-bottom:14px; font-size:14px; line-height:1.7; }}
.positive {{ color:var(--green); padding:4px 0; }}
.finding {{ border:1px solid var(--border); border-radius:6px; margin-bottom:14px; overflow:hidden; }}
.finding-head {{ padding:12px 16px; display:flex; align-items:center;
                 gap:10px; border-bottom:1px solid var(--border); }}
.finding-head.critical {{ background:rgba(248,81,73,.08); border-left:4px solid var(--red); }}
.finding-head.high     {{ background:rgba(240,136,62,.08); border-left:4px solid var(--orange); }}
.finding-head.medium   {{ background:rgba(210,153,34,.08); border-left:4px solid var(--yellow); }}
.finding-head.low      {{ background:rgba(63,185,80,.08);  border-left:4px solid var(--green); }}
.finding-body {{ padding:14px 16px; }}
.finding-body p {{ margin-bottom:10px; color:var(--text-2); font-size:13px; }}
.finding-meta {{ display:flex; gap:14px; color:var(--text-3); font-size:11px;
                 flex-wrap:wrap; margin-bottom:10px; }}
.sev-badge {{ padding:2px 8px; border-radius:4px; font-size:10px;
              font-weight:700; text-transform:uppercase; color:#fff; }}
pre {{ background:var(--bg-0); border:1px solid var(--border); border-radius:6px;
       padding:14px; overflow-x:auto; font-family:'SF Mono','Fira Code',monospace;
       font-size:12px; line-height:1.5; margin:10px 0; white-space:pre-wrap; word-wrap:break-word; }}
pre.bad  {{ border-left:3px solid var(--red); }}
pre.good {{ border-left:3px solid var(--green); }}
pre.test {{ border-left:3px solid var(--purple); }}
code {{ font-family:'SF Mono','Fira Code',monospace; background:var(--bg-2);
        padding:2px 5px; border-radius:3px; font-size:12px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:8px 14px; text-align:left; border-bottom:1px solid var(--border); }}
th {{ background:var(--bg-2); color:var(--text-3); font-size:11px;
      text-transform:uppercase; letter-spacing:.5px; }}
details {{ border:1px solid var(--border); border-radius:6px; margin-bottom:10px; }}
details summary {{ padding:10px 14px; cursor:pointer; font-weight:500;
                   background:var(--bg-2); font-size:13px; }}
details[open] summary {{ border-bottom:1px solid var(--border); }}
details .det-body {{ padding:14px; }}
.footer {{ padding:20px 40px; border-top:1px solid var(--border);
           color:var(--text-3); font-size:11px; text-align:center; }}
@media print {{ body{{background:#fff;color:#1a1a1a}} .card,.section{{border:1px solid #ddd}} pre{{background:#f5f5f5}} }}
</style>
</head>
<body>

<div class="header">
    <h1>🤖 AI Code Review Report</h1>
    <div class="meta">
        {_esc(project_name)} &nbsp;|&nbsp;
        {datetime.now().strftime('%B %d, %Y at %H:%M')} &nbsp;|&nbsp;
        Timestamp: {_esc(timestamp)}
    </div>
    <div class="risk-badge" style="background:{risk_colors.get(risk,'#78909c')};color:#fff;">
        {_esc(risk)} RISK — {_esc(recommendation)}
    </div>
</div>

<div class="grid">
    <div class="card">
        <div class="lbl">Overall Risk</div>
        <div class="val" style="color:{risk_colors.get(risk,'#78909c')}">{_esc(risk)}</div>
        <div class="sub">{_esc(recommendation)}</div>
    </div>
    <div class="card">
        <div class="lbl">SonarQube Issues</div>
        <div class="val">{filtered_meta.get('original_issue_count', len(raw_issues))}</div>
        <div class="sub">{filtered_meta.get('filtered_issue_count', len(filtered_issues))} sent to AI</div>
    </div>
    <div class="card">
        <div class="lbl">Real Issues</div>
        <div class="val" style="color:{'var(--red)' if total_real > 0 else 'var(--green)'}">{total_real}</div>
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

<div class="section">
    <div class="sec-head"><span>📝</span><h2>Executive Summary</h2></div>
    <div class="sec-body">
        <div class="summary-box">{_esc(assessment.get('summary', 'No summary available.'))}</div>
'''

    for p in assessment.get('positives', []):
        html += f'        <div class="positive">✨ {_esc(p)}</div>\n'

    top_risks = assessment.get('topRisks', [])
    if top_risks:
        html += '        <h3 style="margin-top:14px;color:var(--yellow);font-size:14px;">⚠️ Top Risks</h3>\n'
        html += '        <ul style="padding-left:20px;margin-top:6px;">\n'
        for r in top_risks:
            html += f'            <li style="color:var(--text-2);font-size:13px;margin:4px 0;">{_esc(r)}</li>\n'
        html += '        </ul>\n'
    html += '    </div>\n</div>\n'

    # Escalated
    if escalated:
        html += f'''
<div class="section">
    <div class="sec-head"><span>🚨</span><h2>Escalated Issues</h2>
        <span class="badge" style="background:var(--red);color:#fff;">{len(escalated)}</span></div>
    <div class="sec-body">
        <p style="color:var(--text-3);margin-bottom:14px;font-size:12px;">
            These were flagged by SonarQube but AI determined they are MORE SEVERE than reported.</p>
'''
        for v in escalated:
            html += _render_validation(v, 'critical')
        html += '    </div>\n</div>\n'

    # Risk predictions
    risk_predictions = ai.get('riskPredictions', {})
    if risk_predictions and risk_predictions.get('predictions'):
        html += '''
<div class="section">
    <div class="sec-head"><h2>🔮 Neural Risk Predictor</h2></div>
    <div class="sec-body">
        <div style="font-size:13px;color:var(--text-2);margin-bottom:20px;font-weight:600;">Future Bug Probability Analysis</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;margin-bottom:20px;">
'''
        for pred in risk_predictions.get('predictions', []):
            p_risk = pred.get('risk', 'MEDIUM')
            bc = risk_colors.get(p_risk, '#ffb300')
            html += f'''
            <div style="background:var(--bg-2);border:1px solid var(--border);border-top:4px solid {bc};border-radius:8px;padding:16px;">
                <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:12px;">
                    <code style="font-size:11px;word-break:break-all;">{_esc(pred.get('file',''))}</code>
                    <span style="background:{bc}20;color:{bc};font-size:10px;font-weight:800;padding:2px 8px;border-radius:12px;">{_esc(p_risk)} RISK</span>
                </div>
                <div style="font-size:13px;line-height:1.5;color:var(--text-2);margin-bottom:16px;">{_esc(pred.get('reason',''))}</div>
                <div style="display:flex;justify-content:space-between;align-items:center;border-top:1px dashed var(--border);padding-top:12px;">
                    <span style="font-size:10px;font-weight:700;text-transform:uppercase;">Probability</span>
                    <span style="font-size:16px;font-weight:800;font-family:monospace;">{_esc(pred.get('probability',''))}</span>
                </div>
            </div>
'''
        html += '        </div>'
        rec = risk_predictions.get('recommendation')
        if rec:
            html += f'''
        <div style="background:rgba(99,102,241,.05);border:1px solid rgba(99,102,241,.2);border-radius:8px;padding:16px;">
            <div style="font-size:11px;font-weight:800;text-transform:uppercase;margin-bottom:8px;">Strategic Recommendation</div>
            <div style="font-size:14px;line-height:1.6;">{_esc(rec)}</div>
        </div>
'''
        html += '    </div>\n</div>\n'

    # AI logical findings
    if logical_findings:
        html += f'''
<div class="section">
    <div class="sec-head"><span>🤖</span><h2>AI-Discovered Logical Issues</h2>
        <span class="badge">{len(logical_findings)} issues SonarQube cannot detect</span></div>
    <div class="sec-body">
'''
        for f in logical_findings:
            sev      = f.get('severity', 'MEDIUM').upper()
            cat      = f.get('category', '')
            icon     = _category_icon(cat)
            conf     = f.get('confidence', 0)
            if isinstance(conf, str):
                try:
                    conf = float(conf)
                except ValueError:
                    conf = 0.7
            html += f'''
        <div class="finding">
            <div class="finding-head {sev.lower()}">
                <span class="sev-badge" style="background:{_severity_color(sev)}">{_esc(sev)}</span>
                <span>{icon}</span>
                <strong style="font-size:14px;">{_esc(f.get('title','Issue'))}</strong>
            </div>
            <div class="finding-body">
                <div class="finding-meta">
                    <span>📄 <code>{_esc(f.get('file','?'))}:{_esc(str(f.get('lineStart','?')))}</code></span>
                    <span>🏷️ {_esc(cat)}</span>
                    <span>🎯 Confidence: {int(conf*100) if isinstance(conf,float) else conf}%</span>
                    {f'<span>📏 Standard: {_esc(f.get("standard",""))}</span>' if f.get('standard') else ''}
                </div>
                <p><strong>The Logic Failure:</strong></p>
                <div class="summary-box" style="white-space:pre-wrap;font-size:12px;">{_esc(f.get('theLogicFailure',f.get('description','N/A')))}</div>
'''
            if f.get('currentCode'):
                html += f'                <p><strong>Current Code:</strong></p>\n                <pre class="bad">{_esc(f["currentCode"])}</pre>\n'
            if f.get('thePrincipalFix'):
                html += f'                <p><strong>The Principal Fix:</strong></p>\n                <pre class="good">{_esc(f["thePrincipalFix"])}</pre>\n'
            if f.get('proofTest'):
                html += f'                <details><summary>🧪 Proof Test</summary><div class="det-body"><pre class="test">{_esc(f["proofTest"])}</pre></div></details>\n'
            if f.get('productionImpact'):
                html += f'                <p style="color:var(--orange);font-size:12px;">💥 <strong>Production Impact:</strong> {_esc(f["productionImpact"])}</p>\n'
            html += '            </div>\n        </div>\n'
        html += '    </div>\n</div>\n'

    # Confirmed Sonar issues
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

    # Architectural findings (Job 4)
    if architectural_findings:
        _pattern_meta = {
            'SHALLOW_PASS_THROUGH':    ('🪟', '#8b5cf6', 'Shallow Pass-Through'),
            'RESPONSIBILITY_OVERFLOW': ('🌊', '#ef4444', 'Responsibility Overflow'),
            'MISSING_SEAM':            ('🔌', '#f97316', 'Missing Seam'),
            'TIGHT_COUPLING':          ('🔗', '#f59e0b', 'Tight Coupling'),
            'UNTESTABLE_SIDE_EFFECT':  ('🧪', '#ec4899', 'Untestable Side Effect'),
            'PREMATURE_ABSTRACTION':   ('🏗️',  '#06b6d4', 'Premature Abstraction'),
            'FEATURE_ENVY':            ('👀', '#84cc16', 'Feature Envy'),
            'REPEATED_STRUCTURE':      ('📋', '#64748b', 'Repeated Structure'),
        }
        _effort_colors = {'SMALL': '#3fb950', 'MEDIUM': '#ffa726', 'LARGE': '#f85149'}

        html += f'''
<div class="section">
    <div class="sec-head"><span>🏛️</span><h2>Architectural Health</h2>
        <span class="badge">{len(architectural_findings)} pattern{" " if len(architectural_findings)==1 else "s "} found in changed code</span></div>
    <div class="sec-body">
        <p style="color:var(--text-3);font-size:12px;margin-bottom:16px;">
            These are structural decisions visible in the diff that will make the codebase harder to change or test over time.
            They are not bugs — they are friction. Address them in the next refactoring sprint.</p>
'''
        for a in architectural_findings:
            pattern    = str(a.get('pattern', 'UNKNOWN')).upper()
            icon, color, label = _pattern_meta.get(pattern, ('🔧', '#8b949e', pattern.replace('_', ' ').title()))
            sev        = str(a.get('severity', 'MEDIUM')).upper()
            sev_color  = {'HIGH': 'var(--red)', 'MEDIUM': 'var(--yellow)', 'LOW': 'var(--green)'}.get(sev, 'var(--text-2)')
            effort     = str(a.get('effort', 'MEDIUM')).upper()
            effort_color = _effort_colors.get(effort, '#8b949e')
            conf       = a.get('confidence', 0)
            conf_pct   = int(float(conf) * 100) if conf else 0

            html += f'''
        <div class="finding">
            <div class="finding-head medium" style="border-left:4px solid {color};">
                <span style="font-size:18px;">{icon}</span>
                <div>
                    <div style="font-size:13px;font-weight:600;color:var(--text-1);">{_esc(label)}</div>
                    <div style="font-size:11px;color:var(--text-3);">{_esc(a.get("id",""))} &nbsp;·&nbsp; {_esc(a.get("location",""))}</div>
                </div>
                <div style="margin-left:auto;display:flex;gap:8px;align-items:center;">
                    <span class="sev-badge" style="background:{sev_color.replace('var(--red)','#f85149').replace('var(--yellow)','#d29922').replace('var(--green)','#3fb950')}">{_esc(sev)}</span>
                    <span style="background:{effort_color}22;color:{effort_color};font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;">
                        {_esc(effort)} EFFORT</span>
                    <span style="color:var(--text-3);font-size:11px;">🎯 {conf_pct}%</span>
                </div>
            </div>
            <div class="finding-body">
                <p><strong>Problem:</strong></p>
                <div class="summary-box" style="font-size:13px;">{_esc(a.get("problem",""))}</div>
                <details style="margin-top:10px;">
                    <summary>🗑️ Deletion Test</summary>
                    <div class="det-body" style="font-size:13px;color:var(--text-2);">{_esc(a.get("deletion_test",""))}</div>
                </details>
                <details style="margin-top:6px;">
                    <summary>✨ Deepening Opportunity</summary>
                    <div class="det-body" style="font-size:13px;color:var(--text-2);">{_esc(a.get("deepening_opportunity",""))}</div>
                </details>
            </div>
        </div>
'''
        html += '    </div>\n</div>\n'

    # False positives
    if false_pos:
        html += f'''
<div class="section">
    <div class="sec-head"><span>❌</span><h2>False Positives — Safe to Ignore</h2>
        <span class="badge" style="background:var(--green);color:#000;">{len(false_pos)} dismissed</span></div>
    <div class="sec-body">
        <details>
            <summary>{len(false_pos)} SonarQube alerts dismissed by AI</summary>
            <div class="det-body">
                <table>
                    <thead><tr><th>File</th><th>Line</th><th>Rule</th><th>Why It\'s Safe</th></tr></thead>
                    <tbody>
'''
        for v in false_pos:
            html += f'''                        <tr>
                            <td><code>{_esc(v.get('file','?'))}</code></td>
                            <td>{_esc(str(v.get('line','?')))}</td>
                            <td><code>{_esc(v.get('sonarRule',''))}</code></td>
                            <td style="font-size:12px;">{_esc(v.get('explanation',''))}</td>
                        </tr>\n'''
        html += '                    </tbody>\n                </table>\n            </div>\n        </details>\n    </div>\n</div>\n'

    # SonarQube metrics
    html += f'''
<div class="section">
    <div class="sec-head"><span>📊</span><h2>SonarQube Breakdown</h2></div>
    <div class="sec-body">
        <div class="grid" style="padding:0;">
            <div class="card"><div class="lbl">Bugs</div>
                <div class="val" style="color:{'var(--red)' if filtered_summary.get('bugs',0)>0 else 'var(--green)'}">{filtered_summary.get('bugs',0)}</div></div>
            <div class="card"><div class="lbl">Vulnerabilities</div>
                <div class="val" style="color:{'var(--red)' if filtered_summary.get('vulnerabilities',0)>0 else 'var(--green)'}">{filtered_summary.get('vulnerabilities',0)}</div></div>
            <div class="card"><div class="lbl">Code Smells</div>
                <div class="val" style="color:var(--yellow)">{filtered_summary.get('code_smells',0)}</div></div>
            <div class="card"><div class="lbl">Blockers</div>
                <div class="val" style="color:{'var(--red)' if filtered_summary.get('blockers',0)>0 else 'var(--green)'}">{filtered_summary.get('blockers',0)}</div></div>
        </div>
    </div>
</div>
'''

    # All issues table
    verdict_lookup = {
        f"{v.get('file','')}:{v.get('line','')}": v.get('verdict', '—')
        for v in sonar_validations
    }
    html += f'''
<div class="section">
    <div class="sec-head"><span>📋</span><h2>All SonarQube Issues</h2></div>
    <div class="sec-body">
        <details>
            <summary>{len(filtered_issues)} issues (sorted by severity)</summary>
            <div class="det-body">
                <table>
                    <thead><tr><th>Severity</th><th>Type</th><th>File</th><th>Line</th><th>Message</th><th>AI Verdict</th></tr></thead>
                    <tbody>
'''
    for issue in filtered_issues:
        sev = issue.get('severity', '?')
        key = f"{issue.get('file','')}:{issue.get('line','')}"
        v   = verdict_lookup.get(key, '—')
        v_icon, v_color, _ = _verdict_style(v) if v != '—' else ('—', '#78909c', '—')
        html += f'''                        <tr>
                            <td><span class="sev-badge" style="background:{_severity_color(sev)}">{_esc(sev)}</span></td>
                            <td>{_esc(issue.get('type','?'))}</td>
                            <td><code>{_esc(issue.get('file','?'))}</code></td>
                            <td>{issue.get('line','?')}</td>
                            <td style="font-size:12px;">{_esc(str(issue.get('message',''))[:120])}</td>
                            <td style="color:{v_color}">{v_icon} {_esc(v)}</td>
                        </tr>\n'''
    html += '                    </tbody>\n                </table>\n            </div>\n        </details>\n    </div>\n</div>\n'

    # Footer
    html += f'''
</div>
<div class="footer">
    <p>🤖 <strong>AICRA</strong> — SonarQube + AI Code Review &nbsp;|&nbsp;
       {_esc(project_name)} &nbsp;|&nbsp;
       Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p style="margin-top:4px;">
       SonarQube: {filtered_meta.get('original_issue_count','?')} issues →
       Filtered: {filtered_meta.get('filtered_issue_count','?')} →
       AI validated: {len(sonar_validations)} →
       AI discovered: {len(logical_findings)} additional
    </p>
</div>
</body>
</html>'''
    return html


# ── CLI entry point (used by run-review.sh) ───────────────────────────────────

def _load_json(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return json.load(f)
    except Exception as e:
        print(f"  Warning: Could not load {path}: {e}")
        return {}


def main():
    if len(sys.argv) < 5:
        print("Usage: python3 engine/report_builder.py "
              "<sonar_raw.json> <sonar_filtered.json> "
              "<gemini_review.json> <output.html> [project_name] [timestamp]")
        sys.exit(1)

    sonar_raw      = _load_json(sys.argv[1])
    sonar_filtered = _load_json(sys.argv[2])
    gemini_review  = _load_json(sys.argv[3])
    output_path    = sys.argv[4]
    project_name   = sys.argv[5] if len(sys.argv) > 5 else "Code Review"
    timestamp      = sys.argv[6] if len(sys.argv) > 6 else datetime.now().strftime('%Y%m%d_%H%M%S')

    html = build_html_report(sonar_raw, sonar_filtered, gemini_review, project_name, timestamp)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  Report generated: {output_path} ({round(os.path.getsize(output_path)/1024,1)} KB)")


if __name__ == '__main__':
    main()
