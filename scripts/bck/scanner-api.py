#!/usr/bin/env python3
# scripts/scanner-api.py
# N8N Integration Service: Exposes an API to trigger the 4-piece review system.

import os
import subprocess
import uuid
import logging
from flask import Flask, request, jsonify, send_file
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MASTER_SCRIPT = os.path.join(PROJECT_ROOT, 'scripts', 'master-review.sh')

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})

@app.route('/full-review', methods=['POST'])
def full_review():
    """
    Trigger the complete 4-piece pipeline.
    Expected JSON: { "repo_url": "...", "branch": "...", "pr_number": 123, "project_key": "..." }
    """
    data = request.json
    repo_url = data.get('repo_url')
    branch = data.get('branch', 'main')
    pr_number = data.get('pr_number', '0')
    project_key = data.get('project_key', os.environ.get('SONAR_PROJECT_KEY'))
    
    if not repo_url:
        return jsonify({"error": "repo_url is required"}), 400
        
    pipeline_id = str(uuid.uuid4())[:8]
    logger.info(f"[{pipeline_id}] Starting pipeline for {repo_url}...")
    
    try:
        # Execute the master orchestration script
        cmd = [
            'bash', MASTER_SCRIPT,
            repo_url,
            str(branch),
            str(pr_number),
            str(project_key)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            logger.error(f"[{pipeline_id}] Pipeline failed: {result.stderr}")
            return jsonify({
                "status": "failed",
                "pipeline_id": pipeline_id,
                "error": result.stderr,
                "stdout": result.stdout
            }), 500
            
        # Extract report path from stdout
        report_path = ""
        for line in result.stdout.split('\n'):
            if "REPORT:" in line:
                report_path = line.split("REPORT:")[1].strip()
                
        return jsonify({
            "status": "success",
            "pipeline_id": pipeline_id,
            "report_path": report_path,
            "download_url": f"/download-report/{os.path.basename(report_path)}" if report_path else None
        })
        
    except Exception as e:
        logger.error(f"[{pipeline_id}] Unexpected error: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/download-report/<filename>', methods=['GET'])
def download_report(filename):
    report_dir = os.environ.get('REPORTS_PATH', os.path.join(PROJECT_ROOT, 'reports'))
    path = os.path.join(report_dir, filename)
    if not os.path.exists(path):
        return jsonify({"error": "Report not found"}), 404
    return send_file(path, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8585)
