"""Database connection helpers converted from includes/db_connect.php.

This module exposes `get_connection()` which reads credentials from environment
variables (with sensible defaults matching the original PHP) and returns a
pymysql connection. It also provides a `cursor` context manager helper.
"""
import os
import pymysql
from contextlib import contextmanager


def get_db_config():
    return {
        'host': os.environ.get('DB_HOST', '192.168.204.15'),
        'user': os.environ.get('DB_USER', 'swg'),
        'password': os.environ.get('DB_PASS', 'Enterprise1701!'),
        'db': os.environ.get('DB_NAME', 'swgusers'),
        'charset': 'utf8mb4',
        'cursorclass': pymysql.cursors.DictCursor,
    }


def get_connection():
    cfg = get_db_config()
    return pymysql.connect(host=cfg['host'], user=cfg['user'], password=cfg['password'], db=cfg['db'], charset=cfg['charset'], cursorclass=cfg['cursorclass'])


@contextmanager
def cursor(conn=None):
    """Context manager to yield a cursor and ensure cleanup.

    If conn is None, this will open a new connection and close it afterwards.
    """
    close_conn = False
    cur = None
    if conn is None:
        conn = get_connection()
        close_conn = True
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        if close_conn:
            try:
                conn.close()
            except Exception:
                pass
