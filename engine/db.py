"""
MySQL database connection helper.
"""

import mysql.connector
from mysql.connector import pooling
from config import Config

_pool = None


def get_pool():
    """Get or create connection pool."""
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="review_pool",
            pool_size=20,
            host=Config.MYSQL_HOST,
            port=Config.MYSQL_PORT,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE,
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci',
            autocommit=False
        )
    return _pool


def get_conn():
    """Get a connection from the pool."""
    return get_pool().get_connection()


def execute(query, params=None, fetch=True):
    """Execute a query and return results."""
    conn = get_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params or ())
        
        if fetch:
            result = cursor.fetchall()
        else:
            conn.commit()
            result = cursor.lastrowid
        
        cursor.close()
        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def execute_many(query, params_list):
    """Execute a query with multiple parameter sets."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.executemany(query, params_list)
        conn.commit()
        cursor.close()
    finally:
        conn.close()


def insert(query, params=None):
    """Insert and return last insert ID."""
    return execute(query, params, fetch=False)


def update(query, params=None):
    """Update and return affected rows."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        return affected
    finally:
        conn.close()