#!/usr/bin/env python3
"""
AICRA — Database Setup
Run once on a fresh install, or re-run safely on an existing database.

    python3 setup_database.py

Strategy:
  - CREATE TABLE IF NOT EXISTS  → safe for fresh installs
  - ALTER TABLE ADD COLUMN      → safe for existing installs (errors ignored)
"""

import mysql.connector
from config import Config


def _add_column(cursor, table, column_def):
    """Add a column to an existing table, ignoring duplicate-column errors."""
    try:
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN {column_def}")
    except mysql.connector.Error as e:
        if e.errno == 1060:  # ER_DUP_FIELDNAME
            pass
        else:
            raise


_VERSION_COL = "version INT DEFAULT 1 AFTER status"


def setup():
    print("=" * 55)
    print("  AICRA — Database Setup")
    print("=" * 55)
    print(f"  Host     : {Config.MYSQL_HOST}:{Config.MYSQL_PORT}")
    print(f"  Database : {Config.MYSQL_DATABASE}")
    print()

    # Connect without selecting a database so we can create it
    conn = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        charset="utf8mb4",
    )
    cursor = conn.cursor()

    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{Config.MYSQL_DATABASE}` "
        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cursor.execute(f"USE `{Config.MYSQL_DATABASE}`")
    print(f"✅ Database '{Config.MYSQL_DATABASE}' ready\n")

    # ─────────────────────────────────────────────────────────────────────────
    # Core tables
    # ─────────────────────────────────────────────────────────────────────────

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS repos (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            github_id       BIGINT UNIQUE,
            name            VARCHAR(255) NOT NULL,
            full_name       VARCHAR(500) NOT NULL UNIQUE,
            git_url         VARCHAR(1000) NOT NULL,
            clone_url       VARCHAR(1000) NOT NULL,
            default_branch  VARCHAR(100) DEFAULT 'main',
            language        VARCHAR(50)  DEFAULT '',
            description     TEXT,
            is_private      BOOLEAN DEFAULT FALSE,
            is_active       BOOLEAN DEFAULT TRUE,
            jira_project_key   VARCHAR(50)  DEFAULT NULL,
            jira_parent_epic   VARCHAR(50)  DEFAULT NULL,
            last_synced_at  DATETIME,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_name   (name),
            INDEX idx_active (is_active)
        ) ENGINE=InnoDB
    """)
    print("✅ repos")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            username      VARCHAR(100) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            email         VARCHAR(255) UNIQUE,
            role          ENUM('admin', 'developer', 'viewer') DEFAULT 'developer',
            is_active     BOOLEAN DEFAULT TRUE,
            last_login    DATETIME,
            login_attempts INT DEFAULT 0,
            locked_until  DATETIME,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    """)
    print("✅ users")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sonar_configs (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            repo_id             INT NOT NULL,
            sonar_project_key   VARCHAR(255) NOT NULL,
            sonar_project_name  VARCHAR(255) DEFAULT '',
            sonar_host          VARCHAR(500) DEFAULT NULL,
            sonar_token         VARCHAR(500) DEFAULT NULL,
            sources_path        VARCHAR(500) DEFAULT '.',
            exclusions          TEXT,
            test_inclusions     VARCHAR(500) DEFAULT '**/*_test.go',
            is_configured       BOOLEAN DEFAULT TRUE,
            last_scan_at        DATETIME,
            quality_gate_status VARCHAR(20)  DEFAULT '',
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_repo        (repo_id),
            UNIQUE KEY uk_project_key (sonar_project_key),
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ sonar_configs")

    # ─────────────────────────────────────────────────────────────────────────
    # Code Review
    # ─────────────────────────────────────────────────────────────────────────

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            repo_id         INT NOT NULL,
            branch          VARCHAR(255) NOT NULL,
            compare_branch  VARCHAR(255) DEFAULT '',
            commit_sha      VARCHAR(64)  DEFAULT '',
            triggered_by    ENUM('manual', 'n8n', 'schedule') DEFAULT 'manual',
            status          ENUM('pending', 'cloning', 'scanning', 'waiting_sonar',
                                 'fetching_results', 'filtering', 'ai_reviewing',
                                 'analyzing', 'generating_report', 'complete', 'failed')
                            DEFAULT 'pending',
            version         INT DEFAULT 1,
            error_message   TEXT,

            -- SonarQube results
            sonar_total_issues    INT     DEFAULT 0,
            sonar_filtered_issues INT     DEFAULT 0,
            sonar_bugs            INT     DEFAULT 0,
            sonar_vulnerabilities INT     DEFAULT 0,
            sonar_code_smells     INT     DEFAULT 0,
            sonar_blockers        INT     DEFAULT 0,
            sonar_criticals       INT     DEFAULT 0,
            sonar_majors          INT     DEFAULT 0,
            sonar_quality_gate    VARCHAR(20)     DEFAULT '',
            sonar_coverage        DECIMAL(5,2)    DEFAULT 0,

            -- AI review results
            ai_confirmed        INT DEFAULT 0,
            ai_false_positives  INT DEFAULT 0,
            ai_escalated        INT DEFAULT 0,
            ai_logical_findings INT DEFAULT 0,
            ai_risk_level       ENUM('LOW','MEDIUM','HIGH','CRITICAL','UNKNOWN') DEFAULT 'UNKNOWN',
            ai_recommendation   VARCHAR(50)  DEFAULT '',
            ai_summary          TEXT,
            ai_model_used       VARCHAR(50)  DEFAULT '',

            -- Quality score (0-10)
            quality_score         DECIMAL(4,2) DEFAULT NULL,
            score_sonar_issues    INT     DEFAULT NULL,
            score_ai_severity     INT     DEFAULT NULL,
            score_test_coverage   INT     DEFAULT NULL,
            score_commit_msg      INT     DEFAULT NULL,
            score_complexity      INT     DEFAULT NULL,
            score_standards       INT     DEFAULT NULL,
            score_documentation   INT     DEFAULT NULL,
            score_details_json    TEXT    DEFAULT NULL,

            -- Computed
            total_real_issues INT DEFAULT 0,
            files_affected    INT DEFAULT 0,

            -- Storage
            sonar_raw_json      LONGTEXT,
            sonar_filtered_json LONGTEXT,
            gemini_raw_output   LONGTEXT,
            gemini_parsed_json  LONGTEXT,
            report_html_path    VARCHAR(1000) DEFAULT '',
            ai_risk_predictions LONGTEXT,

            -- Timing
            duration_seconds INT DEFAULT 0,
            scan_duration    INT DEFAULT 0,
            ai_duration      INT DEFAULT 0,
            started_at       DATETIME,
            completed_at     DATETIME,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
            INDEX idx_repo_branch (repo_id, branch),
            INDEX idx_status  (status),
            INDEX idx_risk    (ai_risk_level),
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB
    """)
    print("✅ reviews")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_logs (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            review_id  INT NOT NULL,
            step       VARCHAR(100) NOT NULL,
            status     ENUM('started', 'completed', 'failed') NOT NULL,
            message    TEXT,
            duration_ms INT DEFAULT 0,
            created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
            FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE,
            INDEX idx_review_step (review_id, step)
        ) ENGINE=InnoDB
    """)
    print("✅ review_logs")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_suggestions (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            review_id       INT NOT NULL,
            suggestion_text TEXT NOT NULL,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE,
            INDEX idx_review (review_id)
        ) ENGINE=InnoDB
    """)
    print("✅ review_suggestions")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS findings (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            review_id  INT NOT NULL,
            source     ENUM('sonar_confirmed', 'sonar_false_positive',
                            'sonar_escalated',  'ai_finding', 'arch_finding') NOT NULL,
            ai_verdict VARCHAR(50) DEFAULT '',
            title      VARCHAR(500) DEFAULT '',
            category   VARCHAR(100) DEFAULT '',
            severity   ENUM('CRITICAL','HIGH','MEDIUM','LOW','INFO') DEFAULT 'MEDIUM',
            confidence DECIMAL(3,2) DEFAULT 0.70,

            file_path  VARCHAR(1000) DEFAULT '',
            line_start INT DEFAULT 0,
            line_end   INT DEFAULT 0,
            sonar_rule VARCHAR(100) DEFAULT '',

            explanation       TEXT,
            production_impact TEXT,
            current_code      TEXT,
            fix_code          TEXT,
            test_code         TEXT,
            remediation_plan  TEXT,
            mermaid_diagram   TEXT,
            strategic_approach TEXT,
            standard_violated  TEXT,

            -- User feedback
            feedback         ENUM('helpful', 'not_helpful', 'false_positive') DEFAULT NULL,
            feedback_comment TEXT,
            feedback_at      DATETIME,

            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE,
            INDEX idx_review   (review_id),
            INDEX idx_severity (severity),
            INDEX idx_category (category),
            INDEX idx_file     (file_path(255)),
            INDEX idx_feedback (feedback)
        ) ENGINE=InnoDB
    """)
    print("✅ findings")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coding_standards (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            repo_id    INT DEFAULT NULL,
            name       VARCHAR(255) NOT NULL,
            content    LONGTEXT NOT NULL,
            is_global  BOOLEAN DEFAULT FALSE,
            version    VARCHAR(50) DEFAULT '1.0',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE SET NULL
        ) ENGINE=InnoDB
    """)
    print("✅ coding_standards")

    # ─────────────────────────────────────────────────────────────────────────
    # Developer Activity
    # ─────────────────────────────────────────────────────────────────────────

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS developers (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            github_username VARCHAR(100) NOT NULL,
            display_name    VARCHAR(255) DEFAULT '',
            avatar_url      VARCHAR(1000) DEFAULT '',
            email           VARCHAR(255) NOT NULL UNIQUE,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_email (email)
        ) ENGINE=InnoDB
    """)
    print("✅ developers")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS developer_daily_stats (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            developer_id   INT NOT NULL,
            stats_date     DATE NOT NULL,
            commits_count  INT DEFAULT 0,
            lines_added    INT DEFAULT 0,
            lines_removed  INT DEFAULT 0,
            files_touched_count INT DEFAULT 0,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (developer_id) REFERENCES developers(id) ON DELETE CASCADE,
            UNIQUE KEY uk_dev_date (developer_id, stats_date)
        ) ENGINE=InnoDB
    """)
    print("✅ developer_daily_stats")

    # ─────────────────────────────────────────────────────────────────────────
    # ROI Auditor
    # ─────────────────────────────────────────────────────────────────────────

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_analyses (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            repo_id        INT NOT NULL,
            branch         VARCHAR(255) NOT NULL,
            base_branch    VARCHAR(255) DEFAULT 'main',
            status         ENUM('pending', 'analyzing', 'complete', 'failed') DEFAULT 'pending',
            version        INT DEFAULT 1,
            target_commits INT DEFAULT 10,
            analysis_data  LONGTEXT,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
            INDEX idx_repo   (repo_id),
            INDEX idx_status (status)
        ) ENGINE=InnoDB
    """)
    print("✅ roi_analyses")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_logs (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            analysis_id INT NOT NULL,
            step        VARCHAR(100) NOT NULL,
            message     TEXT,
            created_at  DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
            FOREIGN KEY (analysis_id) REFERENCES roi_analyses(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ roi_logs")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_work_units (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            analysis_id   INT NOT NULL,
            unit_name     VARCHAR(500) NOT NULL,
            author        VARCHAR(255) DEFAULT 'Engineering Team',
            intent        TEXT,
            -- Deterministic complexity
            files_impacted INT DEFAULT 0,
            lines_added    INT DEFAULT 0,
            lines_removed  INT DEFAULT 0,
            logic_lines    INT DEFAULT 0,
            complexity_tier INT DEFAULT 1,
            cloc_data_json  TEXT,
            -- AI classification
            work_category      VARCHAR(50) DEFAULT 'MAINTENANCE',
            ai_confidence      DECIMAL(3,2) DEFAULT 0.70,
            executive_summary  TEXT,
            business_impact    TEXT,
            risk_assessment    TEXT,
            -- Jira
            jira_tickets_json  TEXT,
            created_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (analysis_id) REFERENCES roi_analyses(id) ON DELETE CASCADE,
            INDEX idx_analysis (analysis_id),
            INDEX idx_author   (author(100))
        ) ENGINE=InnoDB
    """)
    print("✅ roi_work_units")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_work_unit_files (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            work_unit_id INT NOT NULL,
            file_path    VARCHAR(1000) NOT NULL,
            change_type  VARCHAR(10)   DEFAULT 'M',
            lines_added  INT DEFAULT 0,
            lines_removed INT DEFAULT 0,
            commits_json  TEXT,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (work_unit_id) REFERENCES roi_work_units(id) ON DELETE CASCADE,
            INDEX idx_unit (work_unit_id)
        ) ENGINE=InnoDB
    """)
    print("✅ roi_work_unit_files")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_unit_overrides (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            repo_id      INT NOT NULL,
            unit_name    VARCHAR(255) NOT NULL,
            tier         INT NOT NULL,
            reason       TEXT,
            overridden_by VARCHAR(100),
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
            UNIQUE KEY uk_repo_unit (repo_id, unit_name)
        ) ENGINE=InnoDB
    """)
    print("✅ roi_unit_overrides")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS roi_dismissed_risks (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            repo_id      INT NOT NULL,
            risk_hash    VARCHAR(100) NOT NULL,
            dismissed_by VARCHAR(100) NOT NULL,
            reason       TEXT NOT NULL,
            dismissed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_risk (repo_id, risk_hash),
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ roi_dismissed_risks")

    # ─────────────────────────────────────────────────────────────────────────
    # FDS Gap Analyzer
    # ─────────────────────────────────────────────────────────────────────────

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_documents (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            repo_id    INT,
            title      VARCHAR(255) NOT NULL,
            content    LONGTEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE SET NULL
        ) ENGINE=InnoDB
    """)
    print("✅ fds_documents")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_structural_index (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            fds_id      INT NOT NULL,
            parent_id   INT DEFAULT NULL,
            title       VARCHAR(500) NOT NULL,
            summary     TEXT,
            page_start  INT,
            page_end    INT,
            level       INT DEFAULT 1,
            path_trace  TEXT,
            token_estimate INT DEFAULT 0,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fds_id) REFERENCES fds_documents(id) ON DELETE CASCADE,
            INDEX idx_fds    (fds_id),
            INDEX idx_parent (parent_id)
        ) ENGINE=InnoDB
    """)
    print("✅ fds_structural_index")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_requirements (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            fds_id      INT NOT NULL,
            section_id  INT DEFAULT NULL,
            req_id      VARCHAR(50) NOT NULL,
            description TEXT NOT NULL,
            req_type    VARCHAR(50) DEFAULT 'Functional',
            source_page VARCHAR(50) DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fds_id)     REFERENCES fds_documents(id)       ON DELETE CASCADE,
            FOREIGN KEY (section_id) REFERENCES fds_structural_index(id) ON DELETE SET NULL
        ) ENGINE=InnoDB
    """)
    print("✅ fds_requirements")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_gap_analyses (
            id                   INT AUTO_INCREMENT PRIMARY KEY,
            fds_id               INT NOT NULL,
            repo_id              INT NOT NULL,
            branch               VARCHAR(255) NOT NULL,
            status               ENUM('pending', 'analyzing', 'complete', 'failed') DEFAULT 'pending',
            version              INT DEFAULT 1,
            -- Summary stats
            total_requirements   INT DEFAULT 0,
            verified_count       INT DEFAULT 0,
            partial_count        INT DEFAULT 0,
            not_implemented_count INT DEFAULT 0,
            coverage_percentage  DECIMAL(5,2) DEFAULT 0,
            -- Storage
            results_json         LONGTEXT,
            analysis_data        LONGTEXT,
            completed_at         DATETIME,
            created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fds_id)    REFERENCES fds_documents(id) ON DELETE CASCADE,
            FOREIGN KEY (repo_id)   REFERENCES repos(id)         ON DELETE CASCADE,
            INDEX idx_fds    (fds_id),
            INDEX idx_status (status)
        ) ENGINE=InnoDB
    """)
    print("✅ fds_gap_analyses")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_logs (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            analysis_id INT NOT NULL,
            step        VARCHAR(100) NOT NULL,
            message     TEXT,
            created_at  DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
            FOREIGN KEY (analysis_id) REFERENCES fds_gap_analyses(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
    print("✅ fds_logs")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_requirement_verifications (
            id                     INT AUTO_INCREMENT PRIMARY KEY,
            analysis_id            INT NOT NULL,
            requirement_id         VARCHAR(50) NOT NULL,
            title                  VARCHAR(255),
            status                 ENUM('VERIFIED','PARTIAL','NOT_IMPLEMENTED','NOT_VERIFIED','CONFLICTING') NOT NULL,
            confidence             DECIMAL(3,2) DEFAULT 0.00,
            implementation_coverage DECIMAL(3,2) DEFAULT 0.00,
            assessment_confidence  DECIMAL(3,2) DEFAULT 0.00,
            reliability            VARCHAR(50),
            evidence_json          LONGTEXT,
            gaps_json              LONGTEXT,
            reasoning              TEXT,
            created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (analysis_id) REFERENCES fds_gap_analyses(id) ON DELETE CASCADE,
            INDEX idx_analysis (analysis_id),
            INDEX idx_status   (status)
        ) ENGINE=InnoDB
    """)
    print("✅ fds_requirement_verifications")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_extraction_cache (
            id                INT AUTO_INCREMENT PRIMARY KEY,
            cache_key         VARCHAR(64) NOT NULL UNIQUE,
            requirements_json LONGTEXT NOT NULL,
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_key (cache_key)
        ) ENGINE=InnoDB
    """)
    print("✅ fds_extraction_cache")

    # ─────────────────────────────────────────────────────────────────────────
    # Misc
    # ─────────────────────────────────────────────────────────────────────────

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auto_generated_tickets (
            id        INT AUTO_INCREMENT PRIMARY KEY,
            repo_id   INT NOT NULL,
            unit_name VARCHAR(255) NOT NULL,
            jira_key  VARCHAR(50)  NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE,
            UNIQUE KEY uk_repo_unit (repo_id, unit_name)
        ) ENGINE=InnoDB
    """)
    print("✅ auto_generated_tickets")

    # ─────────────────────────────────────────────────────────────────────────
    # Upgrade path — safe column additions for existing installations
    # Each call is a no-op if the column already exists.
    # ─────────────────────────────────────────────────────────────────────────
    print("\nApplying upgrade patches for existing installs...")

    # reviews — columns added incrementally during development
    _add_column(cursor, "reviews", _VERSION_COL)
    _add_column(cursor, "reviews", "quality_score DECIMAL(4,2) DEFAULT NULL")
    _add_column(cursor, "reviews", "score_sonar_issues INT DEFAULT NULL")
    _add_column(cursor, "reviews", "score_ai_severity INT DEFAULT NULL")
    _add_column(cursor, "reviews", "score_test_coverage INT DEFAULT NULL")
    _add_column(cursor, "reviews", "score_commit_msg INT DEFAULT NULL")
    _add_column(cursor, "reviews", "score_complexity INT DEFAULT NULL")
    _add_column(cursor, "reviews", "score_standards INT DEFAULT NULL")
    _add_column(cursor, "reviews", "score_documentation INT DEFAULT NULL")
    _add_column(cursor, "reviews", "score_details_json TEXT DEFAULT NULL")

    # repos
    _add_column(cursor, "repos", "jira_parent_epic VARCHAR(50) DEFAULT NULL AFTER jira_project_key")

    # roi_analyses
    _add_column(cursor, "roi_analyses", _VERSION_COL)

    # fds_requirements
    _add_column(cursor, "fds_requirements", "section_id INT DEFAULT NULL AFTER fds_id")
    _add_column(cursor, "fds_requirements", "source_page VARCHAR(50) DEFAULT '' AFTER req_type")

    # fds_gap_analyses
    _add_column(cursor, "fds_gap_analyses", _VERSION_COL)
    _add_column(cursor, "fds_gap_analyses", "total_requirements INT DEFAULT 0")
    _add_column(cursor, "fds_gap_analyses", "verified_count INT DEFAULT 0")
    _add_column(cursor, "fds_gap_analyses", "partial_count INT DEFAULT 0")
    _add_column(cursor, "fds_gap_analyses", "not_implemented_count INT DEFAULT 0")
    _add_column(cursor, "fds_gap_analyses", "coverage_percentage DECIMAL(5,2) DEFAULT 0")
    _add_column(cursor, "fds_gap_analyses", "results_json LONGTEXT")
    _add_column(cursor, "fds_gap_analyses", "completed_at DATETIME")

    # findings.source ENUM — add arch_finding for Job 4 architectural health
    try:
        cursor.execute("""
            ALTER TABLE findings MODIFY COLUMN source
            ENUM('sonar_confirmed','sonar_false_positive','sonar_escalated',
                 'ai_finding','arch_finding') NOT NULL
        """)
        print("✅ Updated findings.source ENUM (added arch_finding)")
    except mysql.connector.Error:
        pass  # already up to date

    print("✅ Upgrade patches applied")

    conn.commit()
    cursor.close()
    conn.close()

    print()
    print("=" * 55)
    print("  ✅ Database setup complete!")
    print("=" * 55)
    print()
    print("  Next step:  python3 app.py")
    print()


if __name__ == "__main__":
    setup()
