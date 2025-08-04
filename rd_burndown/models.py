"""データベースモデル定義"""

import sqlite3
from abc import ABC
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class DatabaseManager:
    """SQLiteデータベース管理クラス"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """データベース接続のコンテキストマネージャ"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        """データベーススキーマを初期化"""
        with self.get_connection() as conn:
            # versions テーブル
            conn.execute("""
                CREATE TABLE IF NOT EXISTS versions (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    start_date TEXT,
                    due_date TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # issues テーブル（担当者情報を追加）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS issues (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    version_id INTEGER,
                    parent_id INTEGER,
                    subject TEXT NOT NULL,
                    status_name TEXT NOT NULL,
                    estimated_hours REAL,
                    closed_on TEXT,
                    updated_on TEXT,
                    is_leaf INTEGER DEFAULT 1,
                    assigned_to_id INTEGER,
                    assigned_to_name TEXT,
                    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (version_id) REFERENCES versions (id),
                    FOREIGN KEY (parent_id) REFERENCES issues (id)
                )
            """)

            # issue_journals テーブル（担当者変更履歴を含む）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS issue_journals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_id INTEGER NOT NULL,
                    at TEXT NOT NULL,
                    field TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    FOREIGN KEY (issue_id) REFERENCES issues (id)
                )
            """)

            # snapshots テーブル（全体集計）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    date TEXT NOT NULL,
                    version_id INTEGER NOT NULL,
                    scope_hours REAL DEFAULT 0,
                    remaining_hours REAL DEFAULT 0,
                    completed_hours REAL DEFAULT 0,
                    ideal_remaining_hours REAL DEFAULT 0,
                    v_avg REAL DEFAULT 0,
                    v_max REAL DEFAULT 0,
                    v_min REAL DEFAULT 0,
                    PRIMARY KEY (date, version_id),
                    FOREIGN KEY (version_id) REFERENCES versions (id)
                )
            """)

            # assignee_snapshots テーブル（担当者別集計）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assignee_snapshots (
                    date TEXT NOT NULL,
                    version_id INTEGER NOT NULL,
                    assigned_to_id INTEGER,
                    assigned_to_name TEXT,
                    scope_hours REAL DEFAULT 0,
                    remaining_hours REAL DEFAULT 0,
                    completed_hours REAL DEFAULT 0,
                    PRIMARY KEY (date, version_id, assigned_to_id),
                    FOREIGN KEY (version_id) REFERENCES versions (id)
                )
            """)

            # meta テーブル
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # インデックス作成
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_issues_version_id "
                "ON issues (version_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_issues_parent_id ON issues (parent_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_issues_assigned_to_id "
                "ON issues (assigned_to_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_issue_journals_issue_id "
                "ON issue_journals (issue_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_issue_journals_at "
                "ON issue_journals (at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots (date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_assignee_snapshots_date "
                "ON assignee_snapshots (date)"
            )

            conn.commit()


class BaseModel(ABC):
    """データベース操作の基底クラス"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def _execute_insert_or_replace(
        self, table: str, columns: list[str], data: dict[str, Any]
    ) -> None:
        """INSERT OR REPLACE文の共通実行"""
        placeholders = ", ".join(["?" for _ in columns])
        sql = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

        values = tuple(data.get(col) for col in columns)

        with self.db_manager.get_connection() as conn:
            conn.execute(sql, values)
            conn.commit()

    def _execute_select_by_version(
        self,
        table: str,
        version_id: int,
        additional_where: str = "",
        order_by: str = "",
    ) -> list[sqlite3.Row]:
        """version_idでSELECTする共通処理"""
        where_clause = f"WHERE version_id = ?{' AND ' + additional_where if additional_where else ''}"
        order_clause = f"ORDER BY {order_by}" if order_by else ""
        sql = f"SELECT * FROM {table} {where_clause} {order_clause}"

        with self.db_manager.get_connection() as conn:
            cursor = conn.execute(sql, (version_id,))
            return cursor.fetchall()


class IssueModel(BaseModel):
    """課題データのCRUD操作"""

    def upsert_issue(self, issue_data: dict[str, Any]) -> None:
        """課題データを挿入または更新"""
        columns = [
            "id",
            "project_id",
            "version_id",
            "parent_id",
            "subject",
            "status_name",
            "estimated_hours",
            "closed_on",
            "updated_on",
            "is_leaf",
            "assigned_to_id",
            "assigned_to_name",
            "last_seen_at",
        ]
        # is_leafのデフォルト値を設定
        if "is_leaf" not in issue_data:
            issue_data["is_leaf"] = 1
        self._execute_insert_or_replace("issues", columns, issue_data)

    def get_issues_by_version(self, version_id: int) -> list[sqlite3.Row]:
        """バージョンIDで課題を取得"""
        return self._execute_select_by_version("issues", version_id, order_by="id")

    def get_root_issues_by_version(self, version_id: int) -> list[sqlite3.Row]:
        """バージョンIDでルート課題（親なし）を取得"""
        return self._execute_select_by_version(
            "issues", version_id, additional_where="parent_id IS NULL", order_by="id"
        )


class SnapshotModel(BaseModel):
    """スナップショットデータのCRUD操作"""

    def save_snapshot(self, snapshot_data: dict[str, Any]) -> None:
        """全体スナップショットを保存"""
        columns = [
            "date",
            "version_id",
            "scope_hours",
            "remaining_hours",
            "completed_hours",
            "ideal_remaining_hours",
            "v_avg",
            "v_max",
            "v_min",
        ]
        self._execute_insert_or_replace("snapshots", columns, snapshot_data)

    def save_assignee_snapshot(self, assignee_snapshot_data: dict[str, Any]) -> None:
        """担当者別スナップショットを保存"""
        columns = [
            "date",
            "version_id",
            "assigned_to_id",
            "assigned_to_name",
            "scope_hours",
            "remaining_hours",
            "completed_hours",
        ]
        self._execute_insert_or_replace(
            "assignee_snapshots", columns, assignee_snapshot_data
        )

    def get_snapshots_by_version(self, version_id: int) -> list[sqlite3.Row]:
        """バージョンIDでスナップショットを取得"""
        return self._execute_select_by_version("snapshots", version_id, order_by="date")

    def get_assignee_snapshots_by_version(self, version_id: int) -> list[sqlite3.Row]:
        """バージョンIDで担当者別スナップショットを取得"""
        return self._execute_select_by_version(
            "assignee_snapshots", version_id, order_by="date, assigned_to_id"
        )
