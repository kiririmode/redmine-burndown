"""sync コマンドのテスト"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from rd_burndown.commands.sync import sync_command
from rd_burndown.models import DatabaseManager


@pytest.fixture
def temp_db():
    """テスト用の一時データベースを作成"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db_manager = DatabaseManager(db_path)
    db_manager.initialize_schema()

    yield db_path

    # クリーンアップ
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def runner():
    """CLI テストランナー"""
    return CliRunner()


@pytest.fixture
def mock_sync_service():
    """モック同期サービス"""
    mock_service = MagicMock()
    mock_service.sync_project_data.return_value = {
        "target_id": 10,
        "target_type": "version",
        "issues_synced": 5,
        "journals_synced": 3,
        "duration": 1.23,
        "warnings": [],
    }
    return mock_service


class TestSyncCommand:
    """sync コマンドのテスト"""

    @patch("rd_burndown.commands.sync.DataSyncService")
    @patch("rd_burndown.commands.sync.RedmineClient")
    @patch("rd_burndown.commands.sync.load_config")
    def test_sync_data_success(
        self,
        mock_load_config,
        mock_client_class,
        mock_service_class,
        runner,
        temp_db,
        mock_sync_service,
    ):
        """データ同期成功のテスト"""
        # モック設定
        mock_config = MagicMock()
        mock_config.redmine.project_identifier = "test-project"
        mock_config.redmine.version_name = "Sprint-2025.01"
        mock_config.redmine.release_due_date = None
        mock_config.redmine.release_name = None
        mock_load_config.return_value = mock_config

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client_class.return_value = mock_client

        mock_service_class.return_value = mock_sync_service

        # コマンド実行
        result = runner.invoke(
            sync_command,
            [
                "data",
                "--project",
                "test-project",
                "--version",
                "Sprint-2025.01",
                "--db",
                temp_db,
            ],
        )

        # 結果確認
        assert result.exit_code == 0
        assert "データ同期開始" in result.stdout
        assert "同期完了" in result.stdout
        assert "対象ID: 10 (version)" in result.stdout
        assert "課題数: 5" in result.stdout

        # サービスが正しく呼ばれたことを確認
        mock_sync_service.sync_project_data.assert_called_once()

    @patch("rd_burndown.commands.sync.load_config")
    def test_sync_data_missing_project(self, mock_load_config, runner):
        """プロジェクト未指定エラーのテスト"""
        mock_config = MagicMock()
        mock_config.redmine.project_identifier = None
        mock_config.redmine.version_name = "Sprint-2025.01"
        mock_config.redmine.release_due_date = None
        mock_config.redmine.release_name = None
        mock_load_config.return_value = mock_config

        result = runner.invoke(sync_command, ["data"])

        assert result.exit_code == 1
        assert "プロジェクトが指定されていません" in result.stdout

    @patch("rd_burndown.commands.sync.load_config")
    def test_sync_data_missing_version(self, mock_load_config, runner):
        """バージョン未指定エラーのテスト"""
        mock_config = MagicMock()
        mock_config.redmine.project_identifier = "test-project"
        mock_config.redmine.version_name = None
        mock_config.redmine.release_due_date = None
        mock_config.redmine.release_name = None
        mock_load_config.return_value = mock_config

        result = runner.invoke(sync_command, ["data"])

        assert result.exit_code == 1
        assert (
            "--version または --due-date のいずれかを指定してください" in result.stdout
        )

    @patch("rd_burndown.commands.sync.DataSyncService")
    @patch("rd_burndown.commands.sync.RedmineClient")
    @patch("rd_burndown.commands.sync.load_config")
    def test_sync_data_api_error(
        self, mock_load_config, mock_client_class, mock_service_class, runner, temp_db
    ):
        """API エラーのテスト"""
        from rd_burndown.api import RedmineAPIError

        mock_config = MagicMock()
        mock_config.redmine.project_identifier = "test-project"
        mock_config.redmine.version_name = "Sprint-2025.01"
        mock_config.redmine.release_due_date = None
        mock_config.redmine.release_name = None
        mock_load_config.return_value = mock_config

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client_class.return_value = mock_client

        mock_service = MagicMock()
        mock_service.sync_project_data.side_effect = RedmineAPIError(
            "Connection failed"
        )
        mock_service_class.return_value = mock_service

        result = runner.invoke(
            sync_command,
            [
                "data",
                "--project",
                "test-project",
                "--version",
                "Sprint-2025.01",
                "--db",
                temp_db,
            ],
        )

        assert result.exit_code == 1
        assert "API エラー" in result.stdout
        assert "Connection failed" in result.stdout

    @patch("rd_burndown.commands.sync.load_config")
    def test_sync_status_with_data(self, mock_load_config, runner, temp_db):
        """同期状況確認（データあり）のテスト"""
        mock_config = MagicMock()
        mock_config.redmine.project_identifier = "test-project"
        mock_config.redmine.version_name = "Sprint-2025.01"
        mock_config.redmine.release_due_date = None
        mock_config.redmine.release_name = None
        mock_load_config.return_value = mock_config

        # テストデータをDBに挿入
        db_manager = DatabaseManager(temp_db)
        with db_manager.get_connection() as conn:
            # バージョンを挿入
            conn.execute(
                """
                INSERT INTO versions (id, project_id, name, start_date, due_date)
                VALUES (10, 1, 'Sprint-2025.01', '2025-01-01', '2025-01-31')
                """
            )
            # 課題を挿入
            conn.execute(
                """
                INSERT INTO issues (id, project_id, version_id, subject, status_name,
                                  estimated_hours, assigned_to_name, last_seen_at)
                VALUES (100, 1, 10, 'テスト課題', '新規', 8.0, '田中太郎',
                        '2025-01-01T12:00:00Z')
                """
            )
            conn.commit()

        result = runner.invoke(
            sync_command,
            [
                "status",
                "--project",
                "test-project",
                "--version",
                "Sprint-2025.01",
                "--db",
                temp_db,
            ],
        )

        assert result.exit_code == 0
        assert "同期状況確認" in result.stdout
        assert "バージョンID: 10" in result.stdout
        assert "課題数: 1" in result.stdout
        assert "担当者別統計:" in result.stdout
        assert "田中太郎: 1件 (8.0h)" in result.stdout

    @patch("rd_burndown.commands.sync.load_config")
    def test_sync_status_no_data(self, mock_load_config, runner, temp_db):
        """同期状況確認（データなし）のテスト"""
        mock_config = MagicMock()
        mock_config.redmine.project_identifier = "test-project"
        mock_config.redmine.version_name = "Sprint-2025.01"
        mock_config.redmine.release_due_date = None
        mock_config.redmine.release_name = None
        mock_load_config.return_value = mock_config

        result = runner.invoke(
            sync_command,
            [
                "status",
                "--project",
                "test-project",
                "--version",
                "Sprint-2025.01",
                "--db",
                temp_db,
            ],
        )

        assert result.exit_code == 0
        assert "指定されたバージョンのデータが見つかりません" in result.stdout
        assert "rd-burndown sync data" in result.stdout
