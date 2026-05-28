#!/usr/bin/env python3
"""
Setup MySQL database and tables.
Run once: python3 setup_database.py
"""

import mysql.connector
from config import Config


def setup():
    print("Setting up AICRA database...")
    print(f"Host: {Config.MYSQL_HOST}:{Config.MYSQL_PORT}")
    print(f"Database: {Config.MYSQL_DATABASE}")
    print()

    # Connect without database first to create it
    conn = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD
    )
    cursor = conn.cursor()

    # Create database
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{Config.MYSQL_DATABASE}` "
        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    print(f"✅ Database '{Config.MYSQL_DATABASE}' ready")

    cursor.execute(f"USE `{Config.MYSQL_DATABASE}`")

    # ── repos ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS repos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            github_id BIGINT UNIQUE,
            name VARCHAR(255) NOT NULL,
            full_name VARCHAR(500) NOT NULL UNIQUE,
            git_url VARCHAR(1000) NOT NULL,
            clone_url VARCHAR(1000) NOT NULL,
            default_branch VARCHAR(100) DEFAULT 'main',
            language VARCHAR(50) DEFAULT '',
            description TEXT,
            is_private BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            jira_project_key VARCHAR(50) DEFAULT NULL,
            jira_parent_epic VARCHAR(50) DEFAULT NULL,
            last_synced_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            
            INDEX idx_name (name),
            INDEX idx_active (is_active)
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'repos' ready")

    # Migration: Add column to existing table
    try:
        cursor.execute("ALTER TABLE repos ADD COLUMN jira_parent_epic VARCHAR(50) DEFAULT NULL AFTER jira_project_key")
        print("✅ Added 'jira_parent_epic' to 'repos'")
    except:
        pass # Already exists

    # ── sonar_configs ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sonar_configs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            repo_id INT NOT NULL,
            sonar_project_key VARCHAR(255) NOT NULL,
            sonar_project_name VARCHAR(255) DEFAULT '',
            sonar_host VARCHAR(500) DEFAULT NULL,
            sonar_token VARCHAR(500) DEFAULT NULL,
            sources_path VARCHAR(500) DEFAULT '.',
            exclusions TEXT,
            test_inclusions VARCHAR(500) DEFAULT '**/*_test.go',
            is_configured BOOLEAN DEFAULT TRUE,
            last_scan_at DATETIME,
            quality_gate_status VARCHAR(20) DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            
            UNIQUE KEY uk_repo (repo_id),
            UNIQUE KEY uk_project_key (sonar_project_key),
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'sonar_configs' ready")

    # ── reviews ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INT AUTO_INCREMENT PRIMARY KEY,
            repo_id INT NOT NULL,
            branch VARCHAR(255) NOT NULL,
            compare_branch VARCHAR(255) DEFAULT '',
            commit_sha VARCHAR(64) DEFAULT '',
            triggered_by ENUM('manual', 'n8n', 'schedule') DEFAULT 'manual',
            status ENUM('pending', 'cloning', 'scanning', 'waiting_sonar',
                        'fetching_results', 'filtering', 'ai_reviewing',
                        'generating_report', 'complete', 'failed') DEFAULT 'pending',
            error_message TEXT,
            
            -- SonarQube results
            sonar_total_issues INT DEFAULT 0,
            sonar_filtered_issues INT DEFAULT 0,
            sonar_bugs INT DEFAULT 0,
            sonar_vulnerabilities INT DEFAULT 0,
            sonar_code_smells INT DEFAULT 0,
            sonar_blockers INT DEFAULT 0,
            sonar_criticals INT DEFAULT 0,
            sonar_majors INT DEFAULT 0,
            sonar_quality_gate VARCHAR(20) DEFAULT '',
            sonar_coverage DECIMAL(5,2) DEFAULT 0,
            
            -- AI review results
            ai_confirmed INT DEFAULT 0,
            ai_false_positives INT DEFAULT 0,
            ai_escalated INT DEFAULT 0,
            ai_logical_findings INT DEFAULT 0,
            ai_risk_level ENUM('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', 'UNKNOWN') DEFAULT 'UNKNOWN',
            ai_recommendation VARCHAR(50) DEFAULT '',
            ai_summary TEXT,
            ai_model_used VARCHAR(50) DEFAULT '',
            
            -- Computed
            total_real_issues INT DEFAULT 0,
            files_affected INT DEFAULT 0,
            
            -- Storage
            sonar_raw_json LONGTEXT,
            sonar_filtered_json LONGTEXT,
            gemini_raw_output LONGTEXT,
            gemini_parsed_json LONGTEXT,
            report_html_path VARCHAR(1000) DEFAULT '',
            ai_risk_predictions LONGTEXT,
            
            -- Timing
            duration_seconds INT DEFAULT 0,
            scan_duration INT DEFAULT 0,
            ai_duration INT DEFAULT 0,
            started_at DATETIME,
            completed_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
            INDEX idx_repo_branch (repo_id, branch),
            INDEX idx_status (status),
            INDEX idx_risk (ai_risk_level),
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'reviews' ready")

    # ── findings ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS findings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            review_id INT NOT NULL,
            source ENUM('sonar_confirmed', 'sonar_false_positive',
                        'sonar_escalated', 'ai_finding') NOT NULL,
            
            title VARCHAR(500) DEFAULT '',
            category VARCHAR(100) DEFAULT '',
            severity ENUM('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO') DEFAULT 'MEDIUM',
            confidence DECIMAL(3,2) DEFAULT 0.70,
            
            file_path VARCHAR(1000) DEFAULT '',
            line_start INT DEFAULT 0,
            line_end INT DEFAULT 0,
            sonar_rule VARCHAR(100) DEFAULT '',
            
            explanation TEXT,
            production_impact TEXT,
            current_code TEXT,
            fix_code TEXT,
            test_code TEXT,
            
            -- 2026 Pro Remediation
            remediation_plan TEXT,
            mermaid_diagram TEXT,
            strategic_approach TEXT,
            
            standard_violated TEXT,
            
            -- Feedback
            feedback ENUM('helpful', 'not_helpful', 'false_positive') DEFAULT NULL,
            feedback_comment TEXT,
            feedback_at DATETIME,
            
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE,
            INDEX idx_review (review_id),
            INDEX idx_severity (severity),
            INDEX idx_category (category),
            INDEX idx_file (file_path(255)),
            INDEX idx_feedback (feedback)
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'findings' ready")

    # ── coding_standards ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coding_standards (
            id INT AUTO_INCREMENT PRIMARY KEY,
            repo_id INT DEFAULT NULL,
            name VARCHAR(255) NOT NULL,
            content LONGTEXT NOT NULL,
            is_global BOOLEAN DEFAULT FALSE,
            version VARCHAR(50) DEFAULT '1.0',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE SET NULL
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'coding_standards' ready")

    # ── review_logs (for progress tracking) ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            review_id INT NOT NULL,
            step VARCHAR(100) NOT NULL,
            status ENUM('started', 'completed', 'failed') NOT NULL,
            message TEXT,
            duration_ms INT DEFAULT 0,
            created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
            
            FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE,
            INDEX idx_review_step (review_id, step)
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'review_logs' ready")

    # ── users ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE,
            role ENUM('admin', 'developer', 'viewer') DEFAULT 'developer',
            is_active BOOLEAN DEFAULT TRUE,
            last_login DATETIME,
            login_attempts INT DEFAULT 0,
            locked_until DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'users' ready")

    # ── roi_analyses ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_analyses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            repo_id INT NOT NULL,
            branch VARCHAR(255) NOT NULL,
            base_branch VARCHAR(255) DEFAULT 'main',
            status ENUM('pending', 'analyzing', 'complete', 'failed') DEFAULT 'pending',
            target_commits INT DEFAULT 10,
            analysis_data LONGTEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'roi_analyses' ready")

    # ── roi_logs ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            analysis_id INT NOT NULL,
            step VARCHAR(100) NOT NULL,
            message TEXT,
            created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
            FOREIGN KEY (analysis_id) REFERENCES roi_analyses(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'roi_logs' ready")

    # ── auto_generated_tickets (DEPRECATED - READ ONLY) ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auto_generated_tickets (
            id INT AUTO_INCREMENT PRIMARY KEY,
            repo_id INT NOT NULL,
            unit_name VARCHAR(255) NOT NULL,
            jira_key VARCHAR(50) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
            UNIQUE KEY uk_repo_unit (repo_id, unit_name)
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'auto_generated_tickets' ready")

    # ── roi_unit_overrides ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_unit_overrides (
            id INT AUTO_INCREMENT PRIMARY KEY,
            repo_id INT NOT NULL,
            unit_name VARCHAR(255) NOT NULL,
            tier INT NOT NULL,
            reason TEXT,
            overridden_by VARCHAR(100),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
            UNIQUE KEY uk_repo_unit (repo_id, unit_name)
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'roi_unit_overrides' ready")

    # ── fds_documents ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_documents (
            id INT AUTO_INCREMENT PRIMARY KEY,
            repo_id INT,
            title VARCHAR(255) NOT NULL,
            content LONGTEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE SET NULL
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'fds_documents' ready")

    # ── fds_requirements ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_requirements (
            id INT AUTO_INCREMENT PRIMARY KEY,
            fds_id INT NOT NULL,
            req_id VARCHAR(50) NOT NULL,
            description TEXT NOT NULL,
            req_type VARCHAR(50) DEFAULT 'Functional',
            source_page VARCHAR(50) DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fds_id) REFERENCES fds_documents(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'fds_requirements' ready")

    # Migration: Add source_page if it doesn't exist
    try:
        cursor.execute("ALTER TABLE fds_requirements ADD COLUMN source_page VARCHAR(50) DEFAULT '' AFTER req_type")
        print("✅ Added 'source_page' to 'fds_requirements'")
    except:
        pass

    # ── fds_gap_analyses ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_gap_analyses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            fds_id INT NOT NULL,
            repo_id INT NOT NULL,
            branch VARCHAR(255) NOT NULL,
            status ENUM('pending', 'analyzing', 'complete', 'failed') DEFAULT 'pending',
            analysis_data LONGTEXT,
            version INT DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fds_id) REFERENCES fds_documents(id) ON DELETE CASCADE,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'fds_gap_analyses' ready")

    # ── fds_logs ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            analysis_id INT NOT NULL,
            step VARCHAR(100) NOT NULL,
            message TEXT,
            created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
            FOREIGN KEY (analysis_id) REFERENCES fds_gap_analyses(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'fds_logs' ready")

    # ── roi_dismissed_risks ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_dismissed_risks (
            id INT AUTO_INCREMENT PRIMARY KEY,
            repo_id INT NOT NULL,
            risk_hash VARCHAR(100) NOT NULL,
            dismissed_by VARCHAR(100) NOT NULL,
            reason TEXT NOT NULL,
            dismissed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_risk (repo_id, risk_hash),
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'roi_dismissed_risks' ready")

    # ── fds_requirement_verifications ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_requirement_verifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            analysis_id INT NOT NULL,
            requirement_id VARCHAR(50) NOT NULL,
            title VARCHAR(255),
            status ENUM('VERIFIED', 'PARTIAL', 'NOT_IMPLEMENTED', 'NOT_VERIFIED', 'CONFLICTING') NOT NULL,
            confidence DECIMAL(3,2) DEFAULT 0.00,
            implementation_coverage DECIMAL(3,2) DEFAULT 0.00,
            assessment_confidence DECIMAL(3,2) DEFAULT 0.00,
            reliability VARCHAR(50),
            evidence_json TEXT,
            gaps_json TEXT,
            reasoning TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (analysis_id) REFERENCES fds_gap_analyses(id) ON DELETE CASCADE,
            INDEX idx_analysis (analysis_id),
            INDEX idx_status (status)
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'fds_requirement_verifications' ready")

    conn.commit()
    cursor.close()
    conn.close()

    print()
    print("════════════════════════════════════════")
    print("  ✅ Database setup complete!")
    print("════════════════════════════════════════")
    print()
    print("  Next: python3 app.py")


if __name__ == '__main__':
    setup()