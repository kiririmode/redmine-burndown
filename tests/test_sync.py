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

    def test_sync_project_data_release_mode(self, sync_service, mock_client):
        """期日指定モード同期の成功テスト"""
        # リリース用の課題データをモック
        mock_client.get_issues.return_value = {
            "issues": [
                {
                    "id": 200,
                    "subject": "リリース課題",
                    "project": {"id": 1, "name": "テストプロジェクト"},
                    "status": {"id": 1, "name": "新規"},
                    "estimated_hours": 10.0,
                    "assigned_to": {"id": 6, "name": "佐藤花子"},
                    "due_date": "2025-02-15",
                    "updated_on": "2025-01-01T12:00:00Z",
                    "journals": [],
                }
            ],
            "total_count": 1,
        }

        result = sync_service.sync_project_data(
            project_id="test-project",
            release_due_date="2025-02-15",
            release_name="Release v1.0",
            full_sync=True,
            verbose=False,
        )

        # API呼び出しの確認
        mock_client.get_project.assert_called_once_with("test-project")
        mock_client.get_issues.assert_called_once()

        # 結果の確認
        assert result["target_type"] == "release"
        assert result["issues_synced"] == 1
        assert "target_id" in result
        assert "duration" in result
        assert isinstance(result["warnings"], list)

    def test_sync_project_data_no_mode_specified(self, sync_service):
        """モード未指定の場合のエラーテスト"""
        with pytest.raises(
            ValueError,
            match="version_name または release_due_date のいずれかを指定してください",
        ):
            sync_service.sync_project_data(project_id="test-project")

    def test_sync_release_mode_error_handling(self, sync_service, mock_client):
        """期日指定モードのエラーハンドリングテスト"""
        from rd_burndown.api import RedmineAPIError

        # API エラーの模擬
        mock_client.get_issues.side_effect = RedmineAPIError("API Error")

        with pytest.raises(RedmineAPIError):
            sync_service.sync_project_data(
                project_id="test-project",
                release_due_date="2025-02-15",
                release_name="Release v1.0",
            )

    def test_validate_and_get_project_not_found(self, sync_service, mock_client):
        """プロジェクト検証でプロジェクトが見つからない場合のテスト"""
        from rd_burndown.api import RedmineAPIError

        mock_client.get_project.side_effect = RedmineAPIError("404 Not Found")

        with pytest.raises(
            RedmineAPIError, match="プロジェクト 'nonexistent' が見つかりません"
        ):
            sync_service._validate_and_get_project("nonexistent", False, None, None)

    def test_sync_version_mode_success(self, sync_service, mock_client, temp_db):
        """バージョンモード同期の詳細テスト"""
        project_data = {
            "id": 1,
            "name": "テストプロジェクト",
            "identifier": "test-project",
        }

        target_id, target_type = sync_service._sync_version_mode(
            project_data, "Sprint-2025.01", False, None, None
        )

        assert target_id == 10
        assert target_type == "version"

        # バージョンがデータベースに保存されていることを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM versions WHERE id = ?", (10,))
            row = cursor.fetchone()
            assert row["name"] == "Sprint-2025.01"

    def test_sync_release_mode_success(self, sync_service, mock_client, temp_db):
        """期日指定モード同期の詳細テスト"""
        project_data = {"id": 1, "name": "テストプロジェクト"}

        target_id, target_type = sync_service._sync_release_mode(
            project_data, "2025-02-15", "Release v1.0", False, None, None
        )

        assert target_type == "release"
        assert isinstance(target_id, int)

        # リリースがデータベースに保存されていることを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM releases WHERE id = ?", (target_id,))
            row = cursor.fetchone()
            assert row["name"] == "Release v1.0"
            assert row["due_date"] == "2025-02-15"

    def test_perform_issues_sync_with_journals(
        self, sync_service, mock_client, temp_db
    ):
        """ジャーナル付き課題同期のテスト"""
        # より詳細なジャーナルデータを含む課題
        mock_client.get_issues.return_value = {
            "issues": [
                {
                    "id": 300,
                    "subject": "詳細テスト課題",
                    "project": {"id": 1, "name": "テストプロジェクト"},
                    "fixed_version": {"id": 10, "name": "Sprint-2025.01"},
                    "status": {"id": 2, "name": "進行中"},
                    "estimated_hours": 16.0,
                    "assigned_to": {"id": 7, "name": "山田次郎"},
                    "updated_on": "2025-01-02T10:00:00Z",
                    "journals": [
                        {
                            "id": 10,
                            "created_on": "2025-01-02T10:00:00Z",
                            "details": [
                                {
                                    "property": "attr",
                                    "name": "status_id",
                                    "old_value": "1",
                                    "new_value": "2",
                                },
                                {
                                    "property": "attr",
                                    "name": "estimated_hours",
                                    "old_value": "8.0",
                                    "new_value": "16.0",
                                },
                            ],
                        }
                    ],
                }
            ],
            "total_count": 1,
        }

        issues_synced, journals_synced = sync_service._perform_issues_sync_by_version(
            1, 10, None, False, None, None
        )

        assert issues_synced == 1
        assert journals_synced == 1

        # ジャーナルデータがデータベースに保存されていることを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM issue_journals WHERE issue_id = ? ORDER BY field", (300,)
            )
            rows = cursor.fetchall()
            assert len(rows) == 2
            assert any(row["field"] == "status_id" for row in rows)
            assert any(row["field"] == "estimated_hours" for row in rows)

    def test_save_issue_without_version(self, sync_service, temp_db):
        """バージョンなしの課題保存テスト（期日指定モード用）"""
        issue_data = {
            "id": 400,
            "subject": "期日指定課題",
            "project": {"id": 1, "name": "テストプロジェクト"},
            "status": {"id": 1, "name": "新規"},
            "estimated_hours": 5.0,
            "due_date": "2025-03-01",
            "updated_on": "2025-01-01T12:00:00Z",
        }

        sync_service._save_issue(issue_data, False)

        # データベースに保存されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM issues WHERE id = ?", (400,))
            row = cursor.fetchone()

            assert row["id"] == 400
            assert row["subject"] == "期日指定課題"
            assert row["version_id"] is None
            assert row["due_date"] == "2025-03-01"
            assert row["estimated_hours"] == 5.0

    def test_prepare_sync_settings_full_sync(self, sync_service):
        """完全同期設定のテスト"""
        result = sync_service._prepare_sync_settings(10, True, False)
        assert result is None  # 完全同期時は最終更新日時を使わない

    def test_prepare_sync_settings_incremental(self, sync_service, temp_db):
        """差分同期設定のテスト"""
        # テストデータを挿入
        with temp_db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO issues (id, project_id, version_id, subject, status_name,
                                   last_seen_at)
                VALUES (500, 1, 10, 'Test', 'New', '2025-01-03T15:00:00Z')
                """
            )
            conn.commit()

        result = sync_service._prepare_sync_settings(10, False, False)
        assert result == "2025-01-03T15:00:00Z"

    def test_sync_issues_by_due_date(self, sync_service, mock_client):
        """期日指定課題同期のテスト"""
        # 期日指定課題データをモック
        mock_client.get_issues.return_value = {
            "issues": [
                {
                    "id": 600,
                    "subject": "期日課題1",
                    "project": {"id": 1, "name": "テストプロジェクト"},
                    "status": {"id": 1, "name": "新規"},
                    "estimated_hours": 12.0,
                    "due_date": "2025-02-10",
                    "updated_on": "2025-01-01T12:00:00Z",
                    "journals": [],
                },
                {
                    "id": 601,
                    "subject": "期日課題2",
                    "project": {"id": 1, "name": "テストプロジェクト"},
                    "status": {"id": 2, "name": "進行中"},
                    "estimated_hours": 6.0,
                    "due_date": "2025-02-08",
                    "updated_on": "2025-01-01T14:00:00Z",
                    "journals": [],
                },
            ],
            "total_count": 2,
        }

        issues_count, journals_count = sync_service._sync_issues_by_due_date(
            1, 1, "2025-02-15", True, False
        )

        assert issues_count == 2
        assert journals_count == 0

        # API呼び出しの確認
        mock_client.get_issues.assert_called()
        call_args = mock_client.get_issues.call_args
        assert call_args[1]["due_date"] == "<=2025-02-15"

    def test_perform_issues_sync_by_due_date(self, sync_service, mock_client):
        """期日指定課題同期パフォーマンステスト"""
        # API コールの結果を設定
        mock_client.get_issues.return_value = {
            "issues": [
                {
                    "id": 700,
                    "subject": "パフォーマンステスト課題",
                    "project": {"id": 1, "name": "テストプロジェクト"},
                    "status": {"id": 1, "name": "新規"},
                    "estimated_hours": 8.0,
                    "due_date": "2025-02-20",
                    "updated_on": "2025-01-01T12:00:00Z",
                    "journals": [
                        {
                            "id": 20,
                            "created_on": "2025-01-01T12:00:00Z",
                            "details": [
                                {
                                    "property": "attr",
                                    "name": "due_date",
                                    "old_value": "2025-02-25",
                                    "new_value": "2025-02-20",
                                }
                            ],
                        }
                    ],
                }
            ],
            "total_count": 1,
        }

        issues_synced, journals_synced = sync_service._perform_issues_sync_by_due_date(
            1, 1, "2025-02-20", True, False, None, None
        )

        assert issues_synced == 1
        assert journals_synced == 1

    def test_get_last_sync_timestamp_by_due_date(self, sync_service, temp_db):
        """期日指定の最終同期タイムスタンプ取得テスト"""
        # テストデータを挿入
        with temp_db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO issues (id, project_id, version_id, subject, status_name,
                                   due_date, last_seen_at)
                VALUES (800, 1, NULL, 'Test', 'New', '2025-02-15',
                        '2025-01-05T10:00:00Z')
                """
            )
            conn.execute(
                """
                INSERT INTO issues (id, project_id, version_id, subject, status_name,
                                   due_date, last_seen_at)
                VALUES (801, 1, NULL, 'Test2', 'New', '2025-02-10',
                        '2025-01-04T09:00:00Z')
                """
            )
            conn.commit()

        # 最新のタイムスタンプを取得
        timestamp = sync_service._get_last_sync_timestamp_by_due_date(1, "2025-02-15")
        assert timestamp == "2025-01-05T10:00:00Z"

        # データがない場合
        timestamp = sync_service._get_last_sync_timestamp_by_due_date(999, "2025-02-15")
        assert timestamp is None

    def test_sync_with_api_error_handling(self, sync_service, mock_client):
        """API エラーハンドリングのテスト"""
        from rd_burndown.api import RedmineAPIError

        # API エラーを直接設定
        mock_client.get_issues.side_effect = RedmineAPIError("Network error")

        with pytest.raises(RedmineAPIError):
            sync_service._sync_issues_by_version(1, 10, None, False)

    def test_progress_reporting(self, sync_service, mock_client):
        """プログレス報告のテスト"""

        # 複数ページの結果をシミュレート
        mock_client.get_issues.side_effect = [
            {
                "issues": [
                    {
                        "id": 1001,
                        "subject": "課題1",
                        "project": {"id": 1, "name": "テストプロジェクト"},
                        "fixed_version": {"id": 10, "name": "Sprint-2025.01"},
                        "status": {"id": 1, "name": "新規"},
                        "estimated_hours": 2.0,
                        "updated_on": "2025-01-01T12:00:00Z",
                        "journals": [],
                    }
                ]
                * 100,  # 100件の課題
                "total_count": 150,
            },
            {
                "issues": [
                    {
                        "id": 1101,
                        "subject": "課題2",
                        "project": {"id": 1, "name": "テストプロジェクト"},
                        "fixed_version": {"id": 10, "name": "Sprint-2025.01"},
                        "status": {"id": 1, "name": "新規"},
                        "estimated_hours": 3.0,
                        "updated_on": "2025-01-01T12:00:00Z",
                        "journals": [],
                    }
                ]
                * 50,  # 50件の課題
                "total_count": 150,
            },
        ]

        issues_count, journals_count = sync_service._sync_issues_by_version(
            1, 10, None, True
        )

        assert issues_count == 150
        assert journals_count == 0

        # プログレス更新は呼ばれない（パラメータとして渡していないため）

    def test_save_issue_with_parent(self, sync_service, temp_db):
        """親課題を持つ課題の保存テスト"""
        # 親課題を先に保存
        parent_issue = {
            "id": 2000,
            "subject": "親課題",
            "project": {"id": 1, "name": "テストプロジェクト"},
            "status": {"id": 1, "name": "新規"},
            "estimated_hours": 20.0,
            "updated_on": "2025-01-01T12:00:00Z",
        }
        sync_service._save_issue(parent_issue, False)

        # 子課題を保存
        child_issue = {
            "id": 2001,
            "subject": "子課題",
            "project": {"id": 1, "name": "テストプロジェクト"},
            "status": {"id": 1, "name": "新規"},
            "estimated_hours": 5.0,
            "parent": {"id": 2000},
            "updated_on": "2025-01-01T13:00:00Z",
        }
        sync_service._save_issue(child_issue, False)

        # データベースに正しく保存されたことを確認
        with temp_db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM issues WHERE id = ?", (2001,))
            row = cursor.fetchone()

            assert row["id"] == 2001
            assert row["subject"] == "子課題"
            assert row["parent_id"] == 2000

    def test_journal_detail_variations(self, sync_service, temp_db):
        """様々なジャーナル詳細パターンのテスト"""
        # 複数種類の変更を含むジャーナル
        journal_data = {
            "id": 30,
            "created_on": "2025-01-01T15:00:00Z",
            "details": [
                {
                    "property": "attr",
                    "name": "status_id",
                    "old_value": "1",
                    "new_value": "3",
                },
                {
                    "property": "attr",
                    "name": "fixed_version_id",
                    "old_value": "5",
                    "new_value": "10",
                },
                {
                    "property": "attr",
                    "name": "due_date",
                    "old_value": "2025-01-30",
                    "new_value": "2025-02-15",
                },
                {
                    "property": "relation",  # 関連以外のプロパティ（保存されない）
                    "name": "relates",
                    "old_value": "",
                    "new_value": "1234",
                },
            ],
        }

        sync_service._save_journal(3000, journal_data)

        # データベースに正しく保存されたことを確認（attrプロパティのみ）
        with temp_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM issue_journals WHERE issue_id = ? ORDER BY field",
                (3000,),
            )
            rows = cursor.fetchall()

            # due_dateは追跡対象外、propertyがattrのフィールドのみ保存される
            assert len(rows) == 2
            fields = [row["field"] for row in rows]
            assert "status_id" in fields
            assert "fixed_version_id" in fields
            assert "due_date" not in fields  # 追跡対象外
            assert "relates" not in fields  # relationプロパティは除外される
