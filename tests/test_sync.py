"""sync.py のテスト"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from rd_burndown.models import DatabaseManager
from rd_burndown.sync import DataSyncService


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


@pytest.fixture
def mock_client():
    """モックRedmineクライアント"""
    client = MagicMock()

    # プロジェクトレスポンス
    client.get_project.return_value = {
        "project": {"id": 1, "name": "テストプロジェクト", "identifier": "test-project"}
    }

    # バージョンレスポンス
    client.get_versions.return_value = {
        "versions": [
            {
                "id": 10,
                "name": "Sprint-2025.01",
                "created_on": "2025-01-01T00:00:00Z",
                "updated_on": "2025-01-01T00:00:00Z",
                "due_date": "2025-01-31",
            }
        ]
    }

    # 課題レスポンス
    client.get_issues.return_value = {
        "issues": [
            {
                "id": 100,
                "subject": "テスト課題",
                "project": {"id": 1, "name": "テストプロジェクト"},
                "fixed_version": {"id": 10, "name": "Sprint-2025.01"},
                "status": {"id": 1, "name": "新規"},
                "estimated_hours": 8.0,
                "assigned_to": {"id": 5, "name": "田中太郎"},
                "updated_on": "2025-01-01T12:00:00Z",
                "journals": [
                    {
                        "id": 1,
                        "created_on": "2025-01-01T12:00:00Z",
                        "details": [
                            {
                                "property": "attr",
                                "name": "estimated_hours",
                                "old_value": "4.0",
                                "new_value": "8.0",
                            }
                        ],
                    }
                ],
            }
        ],
        "total_count": 1,
    }

    return client


@pytest.fixture
def sync_service(mock_client, temp_db):
    """DataSyncServiceのインスタンス"""
    console = Console()
    return DataSyncService(mock_client, temp_db, console)


class TestDataSyncService:
    """DataSyncService のテスト"""

    def test_sync_project_data_success(self, sync_service, mock_client):
        """プロジェクトデータ同期の成功テスト"""
        result = sync_service.sync_project_data(
            project_id="test-project",
            version_name="Sprint-2025.01",
            full_sync=True,
            verbose=False,
        )

        # API呼び出しの確認
        mock_client.get_project.assert_called_once_with("test-project")
        mock_client.get_versions.assert_called_once_with("test-project")
        mock_client.get_issues.assert_called_once()

        # 結果の確認
        assert result["target_id"] == 10
        assert result["target_type"] == "version"
        assert result["issues_synced"] == 1
        assert result["journals_synced"] == 1
        assert "duration" in result
        assert isinstance(result["warnings"], list)

    def test_sync_project_data_project_not_found(self, sync_service, mock_client):
        """存在しないプロジェクトの場合のテスト"""
        from rd_burndown.api import RedmineAPIError

        mock_client.get_project.side_effect = RedmineAPIError("Project not found")

        with pytest.raises(
            RedmineAPIError, match="プロジェクト 'invalid-project' が見つかりません"
        ):
            sync_service.sync_project_data(
                project_id="invalid-project", version_name="Sprint-2025.01"
            )

    def test_sync_project_data_version_not_found(self, sync_service, mock_client):
        """存在しないバージョンの場合のテスト"""
        from rd_burndown.api import RedmineAPIError

        with pytest.raises(
            RedmineAPIError, match="バージョン 'invalid-version' が見つかりません"
        ):
            sync_service.sync_project_data(
                project_id="test-project", version_name="invalid-version"
            )

    def test_save_version(self, sync_service, temp_db):
        """バージョン保存のテスト"""
        version_data = {
            "id": 10,
            "name": "Sprint-2025.01",
            "created_on": "2025-01-01T00:00:00Z",
            "updated_on": "2025-01-01T00:00:00Z",
            "due_date": "2025-01-31",
        }

        sync_service._save_version(version_data, 1)

        # データベースに保存されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM versions WHERE id = ?", (10,))
            row = cursor.fetchone()

            assert row["id"] == 10
            assert row["project_id"] == 1
            assert row["name"] == "Sprint-2025.01"
            assert row["due_date"] == "2025-01-31"

    def test_save_issue_with_assignee(self, sync_service, temp_db):
        """担当者ありの課題保存テスト"""
        issue_data = {
            "id": 100,
            "subject": "テスト課題",
            "project": {"id": 1, "name": "テストプロジェクト"},
            "fixed_version": {"id": 10, "name": "Sprint-2025.01"},
            "status": {"id": 1, "name": "新規"},
            "estimated_hours": 8.0,
            "assigned_to": {"id": 5, "name": "田中太郎"},
            "updated_on": "2025-01-01T12:00:00Z",
        }

        sync_service._save_issue(issue_data, False)

        # データベースに保存されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM issues WHERE id = ?", (100,))
            row = cursor.fetchone()

            assert row["id"] == 100
            assert row["subject"] == "テスト課題"
            assert row["assigned_to_id"] == 5
            assert row["assigned_to_name"] == "田中太郎"
            assert row["estimated_hours"] == 8.0

    def test_save_issue_without_assignee(self, sync_service, temp_db):
        """担当者なしの課題保存テスト"""
        issue_data = {
            "id": 101,
            "subject": "未アサイン課題",
            "project": {"id": 1, "name": "テストプロジェクト"},
            "fixed_version": {"id": 10, "name": "Sprint-2025.01"},
            "status": {"id": 1, "name": "新規"},
            "estimated_hours": 4.0,
            "updated_on": "2025-01-01T12:00:00Z",
        }

        sync_service._save_issue(issue_data, False)

        # データベースに保存されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM issues WHERE id = ?", (101,))
            row = cursor.fetchone()

            assert row["id"] == 101
            assert row["subject"] == "未アサイン課題"
            assert row["assigned_to_id"] is None
            assert row["assigned_to_name"] is None
            assert row["estimated_hours"] == 4.0

    def test_save_journal(self, sync_service, temp_db):
        """ジャーナル保存のテスト"""
        journal_data = {
            "id": 1,
            "created_on": "2025-01-01T12:00:00Z",
            "details": [
                {
                    "property": "attr",
                    "name": "estimated_hours",
                    "old_value": "4.0",
                    "new_value": "8.0",
                },
                {
                    "property": "attr",
                    "name": "assigned_to_id",
                    "old_value": None,
                    "new_value": "5",
                },
            ],
        }

        sync_service._save_journal(100, journal_data)

        # データベースに保存されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM issue_journals WHERE issue_id = ? ORDER BY field", (100,)
            )
            rows = cursor.fetchall()

            assert len(rows) == 2
            assert rows[0]["field"] == "assigned_to_id"
            assert rows[0]["new_value"] == "5"
            assert rows[1]["field"] == "estimated_hours"
            assert rows[1]["old_value"] == "4.0"
            assert rows[1]["new_value"] == "8.0"

    def test_get_last_sync_timestamp(self, sync_service, temp_db):
        """最終同期タイムスタンプ取得のテスト"""
        # テストデータを挿入
        with temp_db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO issues (id, project_id, version_id, subject, status_name,
                                   last_seen_at)
                VALUES (100, 1, 10, 'Test', 'New', '2025-01-01T12:00:00Z')
                """
            )
            conn.commit()

        # 最終同期タイムスタンプを取得
        timestamp = sync_service._get_last_sync_timestamp(10)
        assert timestamp == "2025-01-01T12:00:00Z"

        # データがない場合
        timestamp = sync_service._get_last_sync_timestamp(999)
        assert timestamp is None
