import sqlite3
import os
from pathlib import Path


class Connection:
    """SQLite 连接管理，WAL 模式，启动时自动建表。"""

    def __init__(self, db_path: str, schema_path: str):
        self.db_path = db_path
        self.schema_path = schema_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async def init(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        schema = Path(self.schema_path).read_text()
        conn.executescript(schema)
        conn.commit()
        return conn
