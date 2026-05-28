#!/usr/bin/env python3
"""
Migration: Add version column for optimistic locking.
"""
import mysql.connector
from config import Config

def migrate():
    print("Running migration: Add version column...")
    conn = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE
    )
    cursor = conn.cursor()

    tables = ['reviews', 'roi_analyses', 'fds_gap_analyses']
    for table in tables:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN version INT DEFAULT 1")
            print(f"✅ Added 'version' to '{table}'")
        except mysql.connector.Error as err:
            if err.errno == 1060: # Duplicate column name
                print(f"ℹ️ 'version' already exists in '{table}'")
            else:
                print(f"❌ Error adding 'version' to '{table}': {err}")

    conn.commit()
    cursor.close()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate()
