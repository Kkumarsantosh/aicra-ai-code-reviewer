#!/usr/bin/env python3
"""
Migration: Add fds_structural_index table for PageIndex support.
"""

import mysql.connector
from config import Config

def migrate():
    print("🚀 Running Migration: Add fds_structural_index...")
    
    conn = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE
    )
    cursor = conn.cursor()

    # 1. Create fds_structural_index table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fds_structural_index (
            id INT AUTO_INCREMENT PRIMARY KEY,
            fds_id INT NOT NULL,
            parent_id INT DEFAULT NULL,
            title VARCHAR(500) NOT NULL,
            summary TEXT,
            page_start INT,
            page_end INT,
            level INT DEFAULT 1,
            path_trace TEXT,
            token_estimate INT DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (fds_id) REFERENCES fds_documents(id) ON DELETE CASCADE,
            INDEX idx_fds (fds_id),
            INDEX idx_parent (parent_id)
        ) ENGINE=InnoDB
    """)
    print("✅ Table 'fds_structural_index' created")

    # 2. Add column to fds_requirements to link back to index node if needed
    try:
        cursor.execute("ALTER TABLE fds_requirements ADD COLUMN section_id INT DEFAULT NULL AFTER fds_id")
        cursor.execute("ALTER TABLE fds_requirements ADD CONSTRAINT fk_section FOREIGN KEY (section_id) REFERENCES fds_structural_index(id) ON DELETE SET NULL")
        print("✅ Column 'section_id' added to 'fds_requirements'")
    except mysql.connector.Error as err:
        print(f"ℹ️  Requirement link already exists or error: {err}")

    conn.commit()
    cursor.close()
    conn.close()
    print("✨ Migration complete!")

if __name__ == '__main__':
    migrate()
