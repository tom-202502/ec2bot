#!/usr/bin/env python3
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


def now_local(tz: str = "Asia/Shanghai") -> str:
    return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S")


class AuditStore:
    def __init__(self, db_path: str, tz: str = "Asia/Shanghai"):
        self.db_path = db_path
        self.tz = tz
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    user_id INTEGER,
                    account_alias TEXT,
                    instance_name TEXT,
                    instance_id TEXT,
                    action TEXT,
                    result TEXT,
                    detail TEXT
                )
                """
            )
            conn.commit()

    def write(self, user_id: int, account_alias: str, instance_name: str, instance_id: str,
              action: str, result: str, detail: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO audit_logs(ts,user_id,account_alias,instance_name,instance_id,action,result,detail) VALUES(?,?,?,?,?,?,?,?)",
                (now_local(self.tz), user_id, account_alias, instance_name, instance_id, action, result, detail),
            )
            conn.commit()

    def recent(self, limit: int = 20):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT ts,user_id,account_alias,instance_name,action,result FROM audit_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return c.fetchall()

    def recent_by_user(self, user_id: int, limit: int = 20):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT ts,user_id,account_alias,instance_name,action,result FROM audit_logs WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
            return c.fetchall()
