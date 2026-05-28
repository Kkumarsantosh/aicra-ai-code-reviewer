#!/usr/bin/env python3
"""
AICRA Dashboard — Main Entry Point.
"""

import os
import threading
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, session
from functools import wraps
from werkzeug.security import check_password_hash
from config import Config
from engine import db
from engine.git_manager import GitManager
from engine.review_runner import ReviewRunner
from engine.roi_auditor import ROIAuditor
from engine.fds_analyzer import FDSAnalyzer

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

git = GitManager()
runner = ReviewRunner()
roi_engine = ROIAuditor()
fds_engine = FDSAnalyzer()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('user', {}).get('role') != 'admin':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_now():
    from datetime import datetime, UTC
    return {'now': datetime.now(UTC), 'config_obj': Config, 'user': session.get('user')}

# ── USER MANAGEMENT ──

@app.route('/users')
@admin_required
def list_users():
    users = db.execute("SELECT id, username, email, role, is_active, last_login, created_at FROM users ORDER BY created_at DESC")
    return render_template('users.html', users=users, active_page='users')

@app.route('/users/create', methods=['POST'])
@admin_required
def create_user():
    username = request.form.get('username')
    password = request.form.get('password')
    email = request.form.get('email')
    role = request.form.get('role', 'developer')
    
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
        
    from werkzeug.security import generate_password_hash
    try:
        db.execute("INSERT INTO users (username, password_hash, email, role) VALUES (%s, %s, %s, %s)", 
                   (username, generate_password_hash(password), email, role), fetch=False)
        return redirect(url_for('list_users'))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_user(user_id):
    db.execute("UPDATE users SET is_active = NOT is_active WHERE id = %s", (user_id,), fetch=False)
    return jsonify({"success": True})

@app.after_request
def add_header(response):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 10 minutes.
    """
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Industry Standard: Redirect if already logged in
    if 'user_id' in session:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_rows = db.execute("SELECT * FROM users WHERE username = %s AND is_active = 1", (username,))
        if user_rows:
            user = user_rows[0]
            # Check if locked
            from datetime import datetime
            if user['locked_until'] and user['locked_until'] > datetime.now():
                return jsonify({"error": "Account locked. Please try later."}), 403
            
            if check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                # Store a clean, serializable version of the user
                session['user'] = {
                    'id': user['id'],
                    'username': user['username'],
                    'role': user['role'],
                    'email': user.get('email')
                }
                db.execute("UPDATE users SET login_attempts = 0, last_login = NOW() WHERE id = %s", (user['id'],), fetch=False)
                return redirect(url_for('index'))
            else:
                # Increment attempts
                new_attempts = user['login_attempts'] + 1
                if new_attempts >= 5:
                    import datetime
                    locked_until = datetime.datetime.now() + datetime.timedelta(minutes=15)
                    db.execute("UPDATE users SET login_attempts = %s, locked_until = %s WHERE id = %s", (new_attempts, locked_until, user['id']), fetch=False)
                    return jsonify({"error": "Maximum attempts reached. Account locked for 15 mins."}), 403
                else:
                    db.execute("UPDATE users SET login_attempts = %s WHERE id = %s", (new_attempts, user['id']), fetch=False)
                    return jsonify({"error": "Invalid credentials."}), 401
        
        return jsonify({"error": "User not found."}), 401
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    try:
        repos = git.get_repos()
        recent_reviews = db.execute("SELECT r.*, rp.name as repo_name FROM reviews r JOIN repos rp ON r.repo_id = rp.id ORDER BY r.created_at DESC LIMIT 10")
        
        # Calculate Aggregates
        stats_rows = db.execute("""
            SELECT 
                COUNT(*) as total_reviews,
                SUM(sonar_bugs) as total_bugs,
                SUM(sonar_vulnerabilities) as total_vulnerabilities,
                SUM(sonar_code_smells) as total_smells,
                AVG(sonar_coverage) as avg_coverage,
                SUM(total_real_issues) as total_issues,
                SUM(duration_seconds) as total_time_saved_sec
            FROM reviews 
            WHERE status = 'complete'
        """)
        stats = stats_rows[0] if stats_rows else {}

        # Issues by severity
        severity_stats = db.execute("""
            SELECT ai_risk_level, COUNT(*) as count 
            FROM reviews 
            WHERE status = 'complete' 
            GROUP BY ai_risk_level
        """)
        
        return render_template('dashboard.html', 
                             repos=repos, 
                             recent_reviews=recent_reviews, 
                             stats=stats,
                             severity_stats=severity_stats,
                             active_page='dashboard')
    except Exception as e: return f"Error: {e}", 500

@app.route('/reviews')
@login_required
def list_reviews():
    try:
        page = int(request.args.get('page', 1))
        per_page = 10
        offset = (page - 1) * per_page
        
        total_count = db.execute("SELECT COUNT(*) as count FROM reviews")[0]['count']
        total_pages = (total_count + per_page - 1) // per_page
        
        reviews = db.execute("""
            SELECT r.*, rp.name as repo_name 
            FROM reviews r 
            JOIN repos rp ON r.repo_id = rp.id 
            ORDER BY r.created_at DESC 
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        
        return render_template('reviews_list.html', 
                             reviews=reviews, 
                             page=page, 
                             total_pages=total_pages,
                             active_page='reviews')
    except Exception as e: return f"Error: {e}", 500

@app.route('/repos')
@login_required
def list_repos():
    show_all = request.args.get('all', '0') == '1'
    repos = git.get_repos(active_only=not show_all)
    return render_template('repos.html', repos=repos, show_all=show_all, active_page='repos')

@app.route('/repos/sync', methods=['POST'])
@login_required
def sync_repos():
    try: return jsonify(git.sync_repos())
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/repo/<int:repo_id>')
@login_required
def repo_detail(repo_id):
    try:
        repo = git.get_repo(repo_id)
        if not repo: return "Repo not found", 404
        
        page = int(request.args.get('page', 1))
        per_page = 10
        offset = (page - 1) * per_page
        
        total_count = db.execute("SELECT COUNT(*) as count FROM reviews WHERE repo_id = %s", (repo_id,))[0]['count']
        total_pages = (total_count + per_page - 1) // per_page
        
        branches = git.get_branches(repo_id)
        reviews = db.execute("""
            SELECT * FROM reviews 
            WHERE repo_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s OFFSET %s
        """, (repo_id, per_page, offset))
        
        return render_template('repo_detail.html', 
                             repo=repo, 
                             branches=branches, 
                             reviews=reviews, 
                             page=page,
                             total_pages=total_pages,
                             active_page='repos')
    except Exception as e: return f"Error: {e}", 500

@app.route('/repo/<int:repo_id>/branches')
@login_required
def get_repo_branches(repo_id):
    branches = git.get_branches(repo_id)
    return jsonify(branches)

@app.route('/repo/<int:repo_id>/configure', methods=['POST'])
@login_required
def repo_configure(repo_id):
    try:
        git.save_sonar_config(repo_id, request.form)
        return redirect(url_for('repo_detail', repo_id=repo_id))
    except Exception as e: return f"Error: {e}", 500

@app.route('/review/start', methods=['POST'])
@login_required
def start_review():
    repo_id = request.form.get('repo_id')
    branch = request.form.get('branch', 'main')
    review_id = db.insert("INSERT INTO reviews (repo_id, branch, status, triggered_by, started_at) VALUES (%s, %s, 'pending', 'manual', NOW())", (repo_id, branch))
    threading.Thread(target=lambda: runner.run_review(review_id), daemon=True).start()
    return redirect(url_for('review_progress', review_id=review_id))

@app.route('/review/<int:review_id>/progress')
@login_required
def review_progress(review_id):
    review_rows = db.execute("SELECT r.*, rp.name as repo_name FROM reviews r JOIN repos rp ON r.repo_id = rp.id WHERE r.id = %s", (review_id,))
    if not review_rows: return "Review not found", 404
    review = review_rows[0]
    repo = git.get_repo(review['repo_id'])
    logs = db.execute("SELECT * FROM review_logs WHERE review_id = %s ORDER BY created_at DESC", (review_id,))
    
    # Calculate elapsed time
    from datetime import datetime
    elapsed_seconds = 0
    if review.get('started_at'):
        end_time = review.get('completed_at') or datetime.now()
        elapsed_seconds = int((end_time - review['started_at']).total_seconds())
        
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'status': review['status'], 
            'logs': logs, 
            'is_complete': review['status'] in ('complete', 'failed'),
            'elapsed_seconds': elapsed_seconds
        })
    return render_template('review_progress.html', review=review, repo=repo, logs=logs, elapsed_seconds=elapsed_seconds, active_page='reviews')

@app.route('/review/<int:review_id>/report')
@login_required
def review_report(review_id):
    review_rows = db.execute("SELECT r.*, rp.name as repo_name FROM reviews r JOIN repos rp ON r.repo_id = rp.id WHERE r.id = %s", (review_id,))
    if not review_rows: return "Review not found", 404
    review = review_rows[0]
    findings = db.execute("SELECT * FROM findings WHERE review_id = %s ORDER BY severity, confidence DESC", (review_id,))
    suggestions = db.execute("SELECT * FROM review_suggestions WHERE review_id = %s", (review_id,))
    
    import json
    risk_predictions = json.loads(review['ai_risk_predictions']) if review.get('ai_risk_predictions') else {}
    return render_template('review_report.html', review=review, findings=findings, suggestions=suggestions, risk_predictions=risk_predictions, active_page='reviews')

# ── ROI AUDITOR ──
@app.route('/roi')
@login_required
def list_roi():
    try:
        repos = db.execute("SELECT id, name, default_branch FROM repos WHERE is_active = TRUE ORDER BY name")
        
        page = int(request.args.get('page', 1))
        per_page = 10
        offset = (page - 1) * per_page
        
        total_count = db.execute("SELECT COUNT(*) as count FROM roi_analyses")[0]['count']
        total_pages = (total_count + per_page - 1) // per_page
        
        analyses = db.execute("""
            SELECT a.id, a.status, a.created_at, r.name as repo_name, a.branch
            FROM roi_analyses a
            JOIN repos r ON a.repo_id = r.id
            ORDER BY a.created_at DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        
        return render_template('roi_list.html', 
                             analyses=analyses, 
                             repos=repos, 
                             page=page,
                             total_pages=total_pages,
                             active_page='roi')
    except Exception as e: return f"Error: {e}", 500

@app.route('/roi/new', methods=['POST'])
@login_required
def start_roi():
    repo_id = request.form.get('repo_id')
    branch = request.form.get('branch', 'main')
    base_branch = request.form.get('base_branch', 'main')
    commit_count = int(request.form.get('commits', 10))
    if repo_id:
        analysis_id = roi_engine.start_analysis(repo_id, branch, base_branch, commit_count)
        return redirect(url_for('roi_progress', analysis_id=analysis_id))
    return redirect(url_for('list_roi'))

@app.route('/roi/<int:analysis_id>/progress')
@login_required
def roi_progress(analysis_id):
    analysis_rows = db.execute("SELECT a.*, r.name as repo_name FROM roi_analyses a JOIN repos r ON a.repo_id = r.id WHERE a.id = %s", (analysis_id,))
    if not analysis_rows: return "Not found", 404
    return render_template('roi_progress.html', analysis=analysis_rows[0], active_page='roi')

@app.route('/roi/<int:analysis_id>/status')
@login_required
def roi_status(analysis_id):
    analysis = db.execute("SELECT status FROM roi_analyses WHERE id = %s", (analysis_id,))
    logs = db.execute("SELECT step, message, created_at FROM roi_logs WHERE analysis_id = %s ORDER BY created_at ASC", (analysis_id,))
    return jsonify({
        "status": analysis[0]['status'] if analysis else 'unknown',
        "logs": logs
    })

@app.route('/roi/weekly')
@login_required
def roi_weekly_report():
    report = roi_engine.get_weekly_report()
    work_units = roi_engine.get_weekly_work_units()
    dev_breakdown = roi_engine._get_developer_breakdown(work_units)
    return render_template('roi_report.html', report=report, work_units=work_units, dev_breakdown=dev_breakdown, active_page='roi')

@app.route('/roi/<int:analysis_id>/report')
@login_required
def view_roi_report(analysis_id):
    analysis_rows = db.execute("SELECT a.*, r.name as repo_name FROM roi_analyses a JOIN repos r ON a.repo_id = r.id WHERE a.id = %s", (analysis_id,))
    if not analysis_rows: return "Not found", 404
    analysis = analysis_rows[0]
    work_units, aggregates, dev_breakdown = roi_engine.build_roi_report(analysis_id)
    return render_template('roi_report.html', analysis=analysis, work_units=work_units, aggregates=aggregates, dev_breakdown=dev_breakdown, active_page='roi')

@app.route('/roi/<int:analysis_id>')
@login_required
def view_roi(analysis_id):
    analysis_rows = db.execute("SELECT a.*, r.name as repo_name FROM roi_analyses a JOIN repos r ON a.repo_id = r.id WHERE a.id = %s", (analysis_id,))
    if not analysis_rows:
        return "Not found", 404
    analysis = analysis_rows[0]
    import json
    report = json.loads(analysis['analysis_data']) if analysis['analysis_data'] else {}
    
    # ── v7.1 Apply Manual Overrides ──
    overrides = db.execute("SELECT unit_name, tier, reason FROM roi_unit_overrides WHERE repo_id = %s", (analysis['repo_id'],))
    override_dict = {o['unit_name']: o for o in overrides}
    
    for unit in report.get('logical_units', []):
        unit_name = unit.get('unit_name')
        if unit_name in override_dict:
            audit = unit.get('shadow_audit', {})
            audit['complexity_tier'] = override_dict[unit_name]['tier']
            audit['complexity_justification'] = f"Manual Override: {override_dict[unit_name]['reason']}"
            unit['is_overridden'] = True

    # ── v7.2 Filter Dismissed Risks ──
    dismissed_hashes = roi_engine.get_dismissed_risks(analysis['repo_id'])
    for unit in report.get('logical_units', []):
        audit = unit.get('shadow_audit', {})
        if 'structural_risks' in audit:
            # Filter out risks whose hash is in the dismissed list
            audit['structural_risks'] = [r for r in audit['structural_risks'] if r.get('risk_hash') not in dismissed_hashes]

    return render_template('roi_detail.html', analysis=analysis, report=report, active_page='roi')

@app.route('/roi/dismiss-risk', methods=['POST'])
@login_required
def roi_dismiss_risk():
    repo_id = request.form.get('repo_id')
    analysis_id = request.form.get('analysis_id')
    risk_hash = request.form.get('risk_hash')
    reason = request.form.get('reason')
    
    if repo_id and risk_hash and reason:
        roi_engine.dismiss_risk(repo_id, risk_hash, current_user.username, reason)
    
    return redirect(url_for('view_roi', analysis_id=analysis_id))

@app.route('/roi/override', methods=['POST'])
@login_required
def roi_override():
    repo_id = request.form.get('repo_id')
    unit_name = request.form.get('unit_name')
    tier = request.form.get('tier')
    reason = request.form.get('reason')
    analysis_id = request.form.get('analysis_id')
    
    if repo_id and unit_name and tier:
        # Use a transaction-safe insert or update
        db.execute("""
            INSERT INTO roi_unit_overrides (repo_id, unit_name, tier, reason, overridden_by)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE tier = VALUES(tier), reason = VALUES(reason), overridden_by = VALUES(overridden_by)
        """, (repo_id, unit_name, tier, reason, current_user.username))
        
    return redirect(url_for('view_roi', analysis_id=analysis_id))

@app.route('/roi/unlinked')
@login_required
def unlinked_work():
    repo_id = request.args.get('repo_id')
    if not repo_id:
        # Get first active repo
        repos = db.execute("SELECT id FROM repos WHERE is_active = TRUE LIMIT 1")
        if not repos: return "No active repos found", 404
        repo_id = repos[0]['id']
    
    report = roi_engine.get_unlinked_work_report(repo_id)
    repos = db.execute("SELECT id, name FROM repos WHERE is_active = TRUE ORDER BY name")
    return render_template('unlinked_report.html', report=report, repos=repos, selected_repo=int(repo_id), active_page='roi')

@app.route('/dashboard/delivery')
@login_required
def delivery_dashboard():
    project_key = request.args.get('project', 'APPMBHK') # Default or from settings
    metrics = jira_client.get_delivery_metrics(project_key)
    return render_template('delivery_dashboard.html', metrics=metrics, project_key=project_key, active_page='dashboard')

@app.route('/dashboard/quality')
@login_required
def quality_dashboard():
    project_key = request.args.get('project', 'APPMBHK')
    trends = jira_client.get_quality_trends(project_key)
    return render_template('quality_dashboard.html', trends=trends, project_key=project_key, active_page='dashboard')

@app.route('/dashboard/alignment')
@login_required
def alignment_dashboard():
    project_key = request.args.get('project', 'APPMBHK')
    objectives = jira_client.get_business_alignment(project_key)
    return render_template('alignment_dashboard.html', objectives=objectives, project_key=project_key, active_page='dashboard')

@app.route('/settings')
@login_required
def app_settings(): return render_template('settings.html', config_obj=Config, active_page='settings')

@app.route('/reports/<path:filename>')
def serve_report(filename): return send_from_directory(Config.REPORTS_DIR, filename)

# ── FDS GAP ANALYSIS ──
@app.route('/fds')
@login_required
def list_fds():
    try:
        page = int(request.args.get('page', 1))
        per_page = 10
        offset = (page - 1) * per_page
        
        total_count = db.execute("SELECT COUNT(*) as count FROM fds_documents")[0]['count']
        total_pages = (total_count + per_page - 1) // per_page
        
        docs = db.execute("""
            SELECT f.*, r.name as repo_name, 
                   (SELECT COUNT(*) FROM fds_requirements WHERE fds_id = f.id) as req_count
            FROM fds_documents f 
            LEFT JOIN repos r ON f.repo_id = r.id 
            ORDER BY f.created_at DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        
        repos = db.execute("SELECT id, name FROM repos WHERE is_active = TRUE ORDER BY name")
        return render_template('fds_list.html', 
                             docs=docs, 
                             repos=repos, 
                             page=page,
                             total_pages=total_pages,
                             active_page='fds')
    except Exception as e: return f"Error: {e}", 500

@app.route('/fds/new', methods=['POST'])
@login_required
def new_fds():
    title = request.form.get('title')
    repo_id = request.form.get('repo_id') or None
    raw_content = request.form.get('content') or ""
    
    pdf_file = request.files.get('fds_pdf')
    pdf_content = ""
    
    if pdf_file and pdf_file.filename.endswith('.pdf'):
        # --- PDF EXTRACTION v2 (PageIndex Ready) ---
        import logging
        # Suppress noisy FontBBox warnings from pdfminer.six (used by pdfplumber)
        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        
        try:
            import pdfplumber
            from pypdf import PdfReader
            
            # Use pypdf for raw structure (sometimes better at page breaks)
            reader = PdfReader(pdf_file)
            
            # Reset file pointer after pypdf read
            pdf_file.seek(0)
            
            # Primary: pdfplumber (Better for layout and complex fonts)
            with pdfplumber.open(pdf_file) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    
                    # Fallback to pypdf if pdfplumber fails to extract text for this page
                    if not text or len(text.strip()) < 10:
                        try:
                            text = reader.pages[i].extract_text()
                        except: text = ""
                        
                    pdf_content += f"--- PAGE {i+1} ---\n" + (text or "[NO_TEXT_EXTRACTED]") + "\n"
                    
        except Exception as e:
            return f"Error reading PDF: {e}", 500
            
    # Combine content: PDF first, then raw text for "special handling"
    content = ""
    if pdf_content:
        content += "--- FDS DOCUMENT CONTENT ---\n" + pdf_content + "\n"
    if raw_content:
        content += "--- SPECIAL HANDLING / ADDITIONAL REQUIREMENTS ---\n" + raw_content
        
    if not title or not content.strip():
        return "Title and either PDF or raw content are required", 400
        
    fds_id = db.insert("INSERT INTO fds_documents (repo_id, title, content) VALUES (%s, %s, %s)", (repo_id, title, content))
    
    # Trigger parsing
    try:
        # Since this is a new FDS, we don't have a gap analysis ID yet
        req_count = fds_engine.parse_fds_document(fds_id, content)
    except Exception as e:
        return f"Error parsing FDS: {e}", 500
        
    return redirect(url_for('view_fds', fds_id=fds_id))

@app.route('/fds/<int:fds_id>')
@login_required
def view_fds(fds_id):
    doc = db.execute("SELECT f.*, r.name as repo_name FROM fds_documents f LEFT JOIN repos r ON f.repo_id = r.id WHERE f.id = %s", (fds_id,))
    if not doc: return "Not found", 404
    
    reqs = db.execute("SELECT * FROM fds_requirements WHERE fds_id = %s", (fds_id,))
    sections = db.execute("SELECT * FROM fds_structural_index WHERE fds_id = %s ORDER BY page_start", (fds_id,))
    analyses = db.execute("SELECT * FROM fds_gap_analyses WHERE fds_id = %s ORDER BY created_at DESC", (fds_id,))
    
    # If the document is linked to a repo, get its branches for the gap analysis dropdown
    branches = []
    if doc[0]['repo_id']:
        try:
            branches = git.get_branches(doc[0]['repo_id'])
        except: pass
        
    return render_template('fds_detail.html', doc=doc[0], reqs=reqs, sections=sections, analyses=analyses, branches=branches, active_page='fds')

@app.route('/fds/<int:fds_id>/requirement/new', methods=['POST'])
@login_required
def add_custom_requirement(fds_id):
    raw_text = request.form.get('requirement_text')
    if not raw_text: return "Requirement text is required", 400
    
    # Standardize using Gemini
    std = fds_engine.standardize_custom_requirement(raw_text)
    
    db.insert(
        "INSERT INTO fds_requirements (fds_id, req_id, description, req_type, source_page) VALUES (%s, %s, %s, %s, %s)",
        (fds_id, std['req_id'], std['description'], std['req_type'], "Manual Entry")
    )
    
    return redirect(url_for('view_fds', fds_id=fds_id))

@app.route('/fds/requirement/<int:req_id>/delete', methods=['POST'])
@login_required
def delete_fds_requirement(req_id):
    # Get fds_id before deleting so we can redirect back
    req = db.execute("SELECT fds_id FROM fds_requirements WHERE id = %s", (req_id,))
    if not req: 
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {"success": False, "error": "Requirement not found"}, 404
        return "Requirement not found", 404
    fds_id = req[0]['fds_id']
    
    fds_engine.delete_requirement(req_id)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return {"success": True}
    return redirect(url_for('view_fds', fds_id=fds_id))

@app.route('/fds/<int:fds_id>/delete', methods=['POST'])
@login_required
def delete_fds(fds_id):
    # Delete the document (ON DELETE CASCADE should handle requirements and analyses)
    db.execute("DELETE FROM fds_documents WHERE id = %s", (fds_id,), fetch=False)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return {"success": True}
    return redirect(url_for('list_fds'))

@app.route('/fds/<int:fds_id>/analyze', methods=['POST'])
@login_required
def start_gap_analysis(fds_id):
    doc = db.execute("SELECT repo_id FROM fds_documents WHERE id = %s", (fds_id,))
    if not doc or not doc[0]['repo_id']: return "Repo not linked", 400
    
    branch = request.form.get('branch', 'main')
    repo_id = doc[0]['repo_id']

    # Insert a pending analysis record first
    analysis_id = db.insert(
        "INSERT INTO fds_gap_analyses (fds_id, repo_id, branch, status) VALUES (%s, %s, %s, 'pending')",
        (fds_id, repo_id, branch)
    )

    def run_async_analysis(aid, rid, br, fid):
        try:
            # v7.1 Optimized: Passes analysis_id to analyze_gap for internal state management
            fds_engine.analyze_gap(rid, br, fid, aid)
        except Exception as e:
            import traceback
            print(f"Background Analysis Failed: {e}\n{traceback.format_exc()}")
            db.update("UPDATE fds_gap_analyses SET status = 'failed', analysis_data = %s WHERE id = %s", (str(e), aid))

    thread = threading.Thread(target=run_async_analysis, args=(analysis_id, repo_id, branch, fds_id))
    thread.daemon = True
    thread.start()
        
    return redirect(url_for('view_fds', fds_id=fds_id))

@app.route('/fds/analysis/<int:analysis_id>/progress')
@login_required
def fds_analysis_progress(analysis_id):
    analysis = db.execute("""
        SELECT a.*, f.title as fds_title, r.name as repo_name 
        FROM fds_gap_analyses a 
        JOIN fds_documents f ON a.fds_id = f.id
        JOIN repos r ON a.repo_id = r.id
        WHERE a.id = %s
    """, (analysis_id,))
    if not analysis: return "Not found", 404
    
    if analysis[0]['status'] == 'complete':
        return redirect(url_for('view_gap_analysis', analysis_id=analysis_id))
        
    return render_template('fds_progress.html', analysis=analysis[0], active_page='fds')

@app.route('/fds/analysis/<int:analysis_id>/logs')
@login_required
def fds_analysis_logs(analysis_id):
    logs = db.execute("SELECT * FROM fds_logs WHERE analysis_id = %s ORDER BY created_at ASC", (analysis_id,))
    return jsonify(logs)

@app.route('/fds/analysis/<int:analysis_id>/status_json')
@login_required
def fds_analysis_status_json(analysis_id):
    analysis = db.execute("SELECT status FROM fds_gap_analyses WHERE id = %s", (analysis_id,))
    if not analysis: return jsonify({"status": "not_found"})
    return jsonify({"status": analysis[0]['status']})

@app.route('/fds/analysis/<int:analysis_id>')
@login_required
def view_gap_analysis(analysis_id):
    analysis = db.execute("""
        SELECT a.*, f.title as fds_title, r.name as repo_name 
        FROM fds_gap_analyses a 
        JOIN fds_documents f ON a.fds_id = f.id
        JOIN repos r ON a.repo_id = r.id
        WHERE a.id = %s
    """, (analysis_id,))
    if not analysis: return "Not found", 404
    
    if analysis[0]['status'] == 'pending' or analysis[0]['status'] == 'analyzing':
        return redirect(url_for('fds_analysis_progress', analysis_id=analysis_id))
    
    import json
    data = json.loads(analysis[0]['analysis_data']) if analysis[0]['analysis_data'] else {}
    
    # Fetch granular verifications if they exist
    verifications = db.execute("SELECT * FROM fds_requirement_verifications WHERE analysis_id = %s", (analysis_id,))
    if verifications:
        # Map verifications for template if needed, or just pass them
        for v in verifications:
            v['evidence'] = json.loads(v['evidence_json']) if v['evidence_json'] else []
            v['gaps'] = json.loads(v['gaps_json']) if v['gaps_json'] else []
        data['verifications'] = verifications

    # ── v7.2 Description Injection for Legacy Reports ──
    # If the JSON data is missing descriptions (from older runs), fetch them from DB
    if data.get('gap_analysis'):
        has_missing_desc = any(not item.get('description') for item in data['gap_analysis'])
        if has_missing_desc:
            req_rows = db.execute("SELECT req_id, description FROM fds_requirements WHERE fds_id = %s", (analysis[0]['fds_id'],))
            desc_map = {r['req_id']: r['description'] for r in req_rows}
            for item in data['gap_analysis']:
                if not item.get('description') and item.get('req_id') in desc_map:
                    item['description'] = desc_map[item['req_id']]

    return render_template('fds_analysis_detail.html', analysis=analysis[0], data=data, active_page='fds')

if __name__ == '__main__':
    os.makedirs(Config.WORKSPACE_DIR, exist_ok=True)
    os.makedirs(Config.REPORTS_DIR, exist_ok=True)
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
