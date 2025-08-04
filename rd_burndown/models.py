"""データベースモデル定義"""

import sqlite3
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


class IssueModel:
    """課題データのCRUD操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def upsert_issue(self, issue_data: dict[str, Any]) -> None:
        """課題データを挿入または更新"""
        with self.db_manager.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO issues (
                    id, project_id, version_id, parent_id, subject, status_name,
                    estimated_hours, closed_on, updated_on, is_leaf,
                    assigned_to_id, assigned_to_name, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    issue_data["id"],
                    issue_data["project_id"],
                    issue_data.get("version_id"),
                    issue_data.get("parent_id"),
                    issue_data["subject"],
                    issue_data["status_name"],
                    issue_data.get("estimated_hours"),
                    issue_data.get("closed_on"),
                    issue_data.get("updated_on"),
                    issue_data.get("is_leaf", 1),
                    issue_data.get("assigned_to_id"),
                    issue_data.get("assigned_to_name"),
                    issue_data.get("last_seen_at"),
                ),
            )
            conn.commit()

    def get_issues_by_version(self, version_id: int) -> list[sqlite3.Row]:
        """バージョンIDで課題を取得"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM issues WHERE version_id = ? ORDER BY id
            """,
                (version_id,),
            )
            return cursor.fetchall()

    def get_root_issues_by_version(self, version_id: int) -> list[sqlite3.Row]:
        """バージョンIDでルート課題（親なし）を取得"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM issues
                WHERE version_id = ? AND parent_id IS NULL
                ORDER BY id
            """,
                (version_id,),
            )
            return cursor.fetchall()


class SnapshotModel:
    """スナップショットデータのCRUD操作"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def save_snapshot(self, snapshot_data: dict[str, Any]) -> None:
        """全体スナップショットを保存"""
        with self.db_manager.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO snapshots (
                    date, version_id, scope_hours, remaining_hours, completed_hours,
                    ideal_remaining_hours, v_avg, v_max, v_min
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    snapshot_data["date"],
                    snapshot_data["version_id"],
                    snapshot_data["scope_hours"],
                    snapshot_data["remaining_hours"],
                    snapshot_data["completed_hours"],
                    snapshot_data["ideal_remaining_hours"],
                    snapshot_data["v_avg"],
                    snapshot_data["v_max"],
                    snapshot_data["v_min"],
                ),
            )
            conn.commit()

    def save_assignee_snapshot(self, assignee_snapshot_data: dict[str, Any]) -> None:
        """担当者別スナップショットを保存"""
        with self.db_manager.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO assignee_snapshots (
                    date, version_id, assigned_to_id, assigned_to_name,
                    scope_hours, remaining_hours, completed_hours
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    assignee_snapshot_data["date"],
                    assignee_snapshot_data["version_id"],
                    assignee_snapshot_data.get("assigned_to_id"),
                    assignee_snapshot_data.get("assigned_to_name"),
                    assignee_snapshot_data["scope_hours"],
                    assignee_snapshot_data["remaining_hours"],
                    assignee_snapshot_data["completed_hours"],
                ),
            )
            conn.commit()

    def get_snapshots_by_version(self, version_id: int) -> list[sqlite3.Row]:
        """バージョンIDでスナップショットを取得"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM snapshots
                WHERE version_id = ?
                ORDER BY date
            """,
                (version_id,),
            )
            return cursor.fetchall()

    def get_assignee_snapshots_by_version(self, version_id: int) -> list[sqlite3.Row]:
        """バージョンIDで担当者別スナップショットを取得"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM assignee_snapshots
                WHERE version_id = ?
                ORDER BY date, assigned_to_id
            """,
                (version_id,),
            )
            return cursor.fetchall()
