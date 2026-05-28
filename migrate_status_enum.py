#!/usr/bin/env python3
"""
Migration: Add 'analyzing' to reviews.status ENUM.
"""
import mysql.connector
from config import Config

def migrate():
    print("Running migration: Update reviews status ENUM...")
    conn = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE
    )
    cursor = conn.cursor()

    try:
        # Update ENUM to include 'analyzing'
        cursor.execute("""
            ALTER TABLE reviews 
            MODIFY COLUMN status ENUM('pending', 'cloning', 'scanning', 'waiting_sonar',
                                     'fetching_results', 'filtering', 'ai_reviewing',
                                     'analyzing', 'generating_report', 'complete', 'failed') 
            DEFAULT 'pending'
        """)
        print("✅ Added 'analyzing' to 'reviews.status' ENUM")
    except mysql.connector.Error as err:
        print(f"❌ Error updating reviews status ENUM: {err}")

    conn.commit()
    cursor.close()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate()
