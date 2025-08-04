"""models.py のテスト"""

import tempfile
from pathlib import Path

import pytest

from rd_burndown.models import DatabaseManager, IssueModel, SnapshotModel


@pytest.fixture
def temp_db():
    """テスト用の一時データベースを作成"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db_manager = DatabaseManager(db_path)
    db_manager.initialize_schema()

    yield db_manager

    # クリーンアップ
    Path(db_path).unlink(missing_ok=True)


class TestDatabaseManager:
    """DatabaseManager のテスト"""

    def test_initialize_schema(self, temp_db):
        """スキーマ初期化のテスト"""
        with temp_db.get_connection() as conn:
            # テーブルが作成されていることを確認（sqlite_sequenceは除外）
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name != 'sqlite_sequence'
                ORDER BY name
            """)
            tables = [row[0] for row in cursor.fetchall()]

            expected_tables = [
                "assignee_snapshots",
                "issue_journals",
                "issues",
                "meta",
                "snapshots",
                "versions",
            ]

            assert tables == expected_tables

    def test_get_connection(self, temp_db):
        """データベース接続のテスト"""
        with temp_db.get_connection() as conn:
            cursor = conn.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1


class TestIssueModel:
    """IssueModel のテスト"""

    def test_upsert_issue(self, temp_db):
        """課題データの挿入・更新テスト"""
        issue_model = IssueModel(temp_db)

        issue_data = {
            "id": 1,
            "project_id": 10,
            "version_id": 100,
            "parent_id": None,
            "subject": "テスト課題",
            "status_name": "新規",
            "estimated_hours": 8.0,
            "closed_on": None,
            "updated_on": "2024-01-01T10:00:00Z",
            "is_leaf": 1,
            "assigned_to_id": 5,
            "assigned_to_name": "田中太郎",
            "last_seen_at": "2024-01-01T10:00:00Z",
        }

        issue_model.upsert_issue(issue_data)

        # データが正しく挿入されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM issues WHERE id = ?", (1,))
            row = cursor.fetchone()

            assert row["id"] == 1
            assert row["subject"] == "テスト課題"
            assert row["assigned_to_id"] == 5
            assert row["assigned_to_name"] == "田中太郎"

    def test_get_issues_by_version(self, temp_db):
        """バージョン別課題取得のテスト"""
        issue_model = IssueModel(temp_db)

        # テストデータを挿入
        issue_data = {
            "id": 1,
            "project_id": 10,
            "version_id": 100,
            "parent_id": None,
            "subject": "テスト課題",
            "status_name": "新規",
            "estimated_hours": 8.0,
            "closed_on": None,
            "updated_on": "2024-01-01T10:00:00Z",
            "is_leaf": 1,
            "assigned_to_id": 5,
            "assigned_to_name": "田中太郎",
            "last_seen_at": "2024-01-01T10:00:00Z",
        }
        issue_model.upsert_issue(issue_data)

        issues = issue_model.get_issues_by_version(100)
        assert len(issues) == 1
        assert issues[0]["id"] == 1

    def test_get_root_issues_by_version(self, temp_db):
        """ルート課題取得のテスト"""
        issue_model = IssueModel(temp_db)

        # 親課題を挿入
        parent_issue = {
            "id": 1,
            "project_id": 10,
            "version_id": 100,
            "parent_id": None,
            "subject": "親課題",
            "status_name": "新規",
            "estimated_hours": 16.0,
            "closed_on": None,
            "updated_on": "2024-01-01T10:00:00Z",
            "is_leaf": 0,
            "assigned_to_id": 5,
            "assigned_to_name": "田中太郎",
            "last_seen_at": "2024-01-01T10:00:00Z",
        }
        issue_model.upsert_issue(parent_issue)

        # 子課題を挿入
        child_issue = {
            "id": 2,
            "project_id": 10,
            "version_id": 100,
            "parent_id": 1,
            "subject": "子課題",
            "status_name": "新規",
            "estimated_hours": 8.0,
            "closed_on": None,
            "updated_on": "2024-01-01T10:00:00Z",
            "is_leaf": 1,
            "assigned_to_id": 6,
            "assigned_to_name": "佐藤花子",
            "last_seen_at": "2024-01-01T10:00:00Z",
        }
        issue_model.upsert_issue(child_issue)

        # ルート課題のみが取得されることを確認
        root_issues = issue_model.get_root_issues_by_version(100)
        assert len(root_issues) == 1
        assert root_issues[0]["id"] == 1
        assert root_issues[0]["parent_id"] is None


class TestSnapshotModel:
    """SnapshotModel のテスト"""

    def test_save_snapshot(self, temp_db):
        """全体スナップショット保存のテスト"""
        snapshot_model = SnapshotModel(temp_db)

        snapshot_data = {
            "date": "2024-01-01",
            "version_id": 100,
            "scope_hours": 80.0,
            "remaining_hours": 64.0,
            "completed_hours": 16.0,
            "ideal_remaining_hours": 60.0,
            "v_avg": 2.0,
            "v_max": 4.0,
            "v_min": 1.0,
        }

        snapshot_model.save_snapshot(snapshot_data)

        # データが正しく保存されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM snapshots WHERE date = ? AND version_id = ?",
                ("2024-01-01", 100),
            )
            row = cursor.fetchone()

            assert row["scope_hours"] == 80.0
            assert row["remaining_hours"] == 64.0
            assert row["v_avg"] == 2.0

    def test_save_assignee_snapshot(self, temp_db):
        """担当者別スナップショット保存のテスト"""
        snapshot_model = SnapshotModel(temp_db)

        assignee_snapshot_data = {
            "date": "2024-01-01",
            "version_id": 100,
            "assigned_to_id": 5,
            "assigned_to_name": "田中太郎",
            "scope_hours": 24.0,
            "remaining_hours": 16.0,
            "completed_hours": 8.0,
        }

        snapshot_model.save_assignee_snapshot(assignee_snapshot_data)

        # データが正しく保存されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM assignee_snapshots "
                "WHERE date = ? AND version_id = ? AND assigned_to_id = ?",
                ("2024-01-01", 100, 5),
            )
            row = cursor.fetchone()

            assert row["assigned_to_name"] == "田中太郎"
            assert row["scope_hours"] == 24.0
            assert row["remaining_hours"] == 16.0

    def test_save_assignee_snapshot_unassigned(self, temp_db):
        """未アサイン課題のスナップショット保存テスト"""
        snapshot_model = SnapshotModel(temp_db)

        unassigned_snapshot_data = {
            "date": "2024-01-01",
            "version_id": 100,
            "assigned_to_id": None,
            "assigned_to_name": None,
            "scope_hours": 16.0,
            "remaining_hours": 16.0,
            "completed_hours": 0.0,
        }

        snapshot_model.save_assignee_snapshot(unassigned_snapshot_data)

        # データが正しく保存されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM assignee_snapshots "
                "WHERE date = ? AND version_id = ? AND assigned_to_id IS NULL",
                ("2024-01-01", 100),
            )
            row = cursor.fetchone()

            assert row["assigned_to_id"] is None
            assert row["assigned_to_name"] is None
            assert row["scope_hours"] == 16.0

    def test_get_snapshots_by_version(self, temp_db):
        """バージョン別スナップショット取得のテスト"""
        snapshot_model = SnapshotModel(temp_db)

        # テストデータを挿入
        snapshot_data = {
            "date": "2024-01-01",
            "version_id": 100,
            "scope_hours": 80.0,
            "remaining_hours": 64.0,
            "completed_hours": 16.0,
            "ideal_remaining_hours": 60.0,
            "v_avg": 2.0,
            "v_max": 4.0,
            "v_min": 1.0,
        }
        snapshot_model.save_snapshot(snapshot_data)

        snapshots = snapshot_model.get_snapshots_by_version(100)
        assert len(snapshots) == 1
        assert snapshots[0]["date"] == "2024-01-01"

    def test_get_assignee_snapshots_by_version(self, temp_db):
        """バージョン別担当者スナップショット取得のテスト"""
        snapshot_model = SnapshotModel(temp_db)

        # テストデータを挿入
        assignee_snapshot_data = {
            "date": "2024-01-01",
            "version_id": 100,
            "assigned_to_id": 5,
            "assigned_to_name": "田中太郎",
            "scope_hours": 24.0,
            "remaining_hours": 16.0,
            "completed_hours": 8.0,
        }
        snapshot_model.save_assignee_snapshot(assignee_snapshot_data)

        snapshots = snapshot_model.get_assignee_snapshots_by_version(100)
        assert len(snapshots) == 1
        assert snapshots[0]["assigned_to_name"] == "田中太郎"
