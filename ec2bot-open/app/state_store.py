#!/usr/bin/env python3
import os
import sqlite3
from typing import Optional


class StateStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS state_cache (
                    instance_id TEXT PRIMARY KEY,
                    state TEXT,
                    cpu_count INTEGER DEFAULT 0,
                    updated_at TEXT
                )
                """
            )
            conn.commit()

    def get_state(self, instance_id: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT state FROM state_cache WHERE instance_id=?", (instance_id,))
            row = c.fetchone()
            return row[0] if row else None

    def get_cpu_count(self, instance_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT cpu_count FROM state_cache WHERE instance_id=?", (instance_id,))
            row = c.fetchone()
            return int(row[0]) if row and row[0] is not None else 0

    def upsert(self, instance_id: str, state: str, cpu_count: int, updated_at: str):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO state_cache(instance_id,state,cpu_count,updated_at) VALUES(?,?,?,?) ON CONFLICT(instance_id) DO UPDATE SET state=excluded.state,cpu_count=excluded.cpu_count,updated_at=excluded.updated_at",
                (instance_id, state, cpu_count, updated_at),
            )
            conn.commit()
