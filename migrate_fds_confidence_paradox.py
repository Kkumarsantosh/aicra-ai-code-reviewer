#!/usr/bin/env python3
"""
Migration: Fix the "100% Confidence Score" Paradox.
Adds implementation_coverage, assessment_confidence, and reliability columns.
"""
import mysql.connector
from config import Config

def migrate():
    print("Running migration: Fix Confidence Score Paradox...")
    conn = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE
    )
    cursor = conn.cursor()

    try:
        # 1. Ensure the table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fds_requirement_verifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                analysis_id INT NOT NULL,
                requirement_id VARCHAR(50) NOT NULL,
                status VARCHAR(50) NOT NULL,
                confidence DECIMAL(3,2) DEFAULT 0.00,
                evidence_json LONGTEXT,
                gaps_json LONGTEXT,
                reasoning TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_analysis (analysis_id),
                FOREIGN KEY (analysis_id) REFERENCES fds_gap_analyses(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
        """)
        print("✅ Table 'fds_requirement_verifications' ensured")

        # 2. Add new columns if they don't exist
        # Check column existence first
        cursor.execute("SHOW COLUMNS FROM fds_requirement_verifications")
        existing_cols = {col[0] for col in cursor.fetchall()}

        if "implementation_coverage" not in existing_cols:
            cursor.execute("ALTER TABLE fds_requirement_verifications ADD COLUMN implementation_coverage DECIMAL(3,2) DEFAULT 0.00")
            print("✅ Added column 'implementation_coverage'")
        if "assessment_confidence" not in existing_cols:
            cursor.execute("ALTER TABLE fds_requirement_verifications ADD COLUMN assessment_confidence DECIMAL(3,2) DEFAULT 0.00")
            print("✅ Added column 'assessment_confidence'")
        if "reliability" not in existing_cols:
            cursor.execute("ALTER TABLE fds_requirement_verifications ADD COLUMN reliability VARCHAR(50)")
            print("✅ Added column 'reliability'")

        # 3. Update existing records
        print("Updating existing records...")
        cursor.execute("""
            UPDATE fds_requirement_verifications 
            SET implementation_coverage = CASE 
                    WHEN status = 'VERIFIED' OR status = 'IMPLEMENTED' THEN 1.00
                    WHEN status = 'PARTIAL' THEN 0.50
                    WHEN status = 'NOT_IMPLEMENTED' OR status = 'MISSING' THEN 0.00
                    ELSE 0.00
                END,
                assessment_confidence = confidence,
                reliability = CASE 
                    WHEN (status = 'NOT_IMPLEMENTED' OR status = 'MISSING') AND confidence >= 0.9 THEN 'DEFINITE_GAP'
                    WHEN (status = 'VERIFIED' OR status = 'IMPLEMENTED') AND confidence >= 0.9 THEN 'DEFINITE_IMPLEMENTED'
                    WHEN status = 'PARTIAL' THEN 'NEEDS_WORK'
                    ELSE 'UNCERTAIN'
                END
        """)
        print(f"✅ Updated {cursor.rowcount} records")
        conn.commit()

    except mysql.connector.Error as err:
        print(f"❌ Migration failed: {err}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate()
