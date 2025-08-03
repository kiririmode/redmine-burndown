"""疎通確認コマンドのテスト"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typer.testing import CliRunner
from io import StringIO

from rd_burndown.commands.check import check_command
from rd_burndown.api.client import RedmineAPIError


class TestCheckCommand:
    """疎通確認コマンドのテストクラス"""

    def setup_method(self):
        """各テストメソッドの前に実行"""
        self.runner = CliRunner()

    @patch("rd_burndown.commands.check.load_config")
    @patch("rd_burndown.commands.check.RedmineClient")
    def test_check_connection_success(
        self, mock_client_class, mock_load_config, mock_config
    ):
        """接続確認成功のテスト"""
        # モック設定
        mock_load_config.return_value = mock_config
        mock_client_instance = Mock()
        mock_client_instance.test_connection.return_value = {
            "success": True,
            "message": "接続成功",
            "projects_count": 2,
            "projects": [
                {
                    "id": 1,
                    "identifier": "proj1",
                    "name": "Project 1",
                    "description": "Desc 1",
                },
            ],
            "statuses": [
                {"id": 1, "name": "新規", "is_closed": False},
                {"id": 5, "name": "完了", "is_closed": True},
            ],
        }
        mock_client_class.return_value.__enter__.return_value = mock_client_instance

        # コマンド実行
        result = self.runner.invoke(check_command, ["connection"])

        # 検証
        assert result.exit_code == 0
        assert "接続成功" in result.stdout
        assert "プロジェクト数: 2" in result.stdout
        assert "課題ステータス数: 2" in result.stdout
        mock_load_config.assert_called_once_with(None)
        mock_client_instance.test_connection.assert_called_once()

    @patch("rd_burndown.commands.check.load_config")
    @patch("rd_burndown.commands.check.RedmineClient")
    def test_check_connection_verbose(
        self, mock_client_class, mock_load_config, mock_config
    ):
        """詳細表示オプションのテスト"""
        # モック設定
        mock_load_config.return_value = mock_config
        mock_client_instance = Mock()
        mock_client_instance.test_connection.return_value = {
            "success": True,
            "message": "接続成功",
            "projects_count": 1,
            "projects": [
                {
                    "id": 1,
                    "identifier": "test-proj",
                    "name": "Test Project",
                    "description": "Test Description",
                }
            ],
            "statuses": [
                {"id": 1, "name": "新規", "is_closed": False},
                {"id": 5, "name": "完了", "is_closed": True},
            ],
        }
        mock_client_class.return_value.__enter__.return_value = mock_client_instance

        # コマンド実行（詳細表示オプション付き）
        result = self.runner.invoke(check_command, ["connection", "--verbose"])

        # 検証
        assert result.exit_code == 0
        assert "接続成功" in result.stdout
        assert "Test Project" in result.stdout
        assert "新規" in result.stdout
        assert "完了" in result.stdout

    @patch("rd_burndown.commands.check.load_config")
    @patch("rd_burndown.commands.check.RedmineClient")
    def test_check_connection_failure(
        self, mock_client_class, mock_load_config, mock_config
    ):
        """接続確認失敗のテスト"""
        # モック設定
        mock_load_config.return_value = mock_config
        mock_client_instance = Mock()
        mock_client_instance.test_connection.return_value = {
            "success": False,
            "message": "接続失敗: Connection refused",
            "projects_count": 0,
            "projects": [],
            "statuses": [],
        }
        mock_client_class.return_value.__enter__.return_value = mock_client_instance

        # コマンド実行
        result = self.runner.invoke(check_command, ["connection"])

        # 検証
        assert result.exit_code == 1
        assert "接続失敗" in result.stdout

    @patch("rd_burndown.commands.check.load_config")
    @patch("rd_burndown.commands.check.RedmineClient")
    def test_check_connection_with_custom_url(
        self, mock_client_class, mock_load_config, mock_config
    ):
        """カスタムURLでの接続確認テスト"""
        # モック設定
        mock_load_config.return_value = mock_config
        mock_client_instance = Mock()
        mock_client_instance.test_connection.return_value = {
            "success": True,
            "message": "接続成功",
            "projects_count": 0,
            "projects": [],
            "statuses": [],
        }
        mock_client_class.return_value.__enter__.return_value = mock_client_instance

        # コマンド実行
        result = self.runner.invoke(
            check_command, ["connection", "--url", "http://custom:3000"]
        )

        # 検証
        assert result.exit_code == 0
        assert "URL: http://custom:3000" in result.stdout

        # 設定が上書きされているか確認
        config_used = mock_client_class.call_args[0][0]
        assert config_used.redmine.base_url == "http://custom:3000"

    @patch("rd_burndown.commands.check.load_config")
    @patch("rd_burndown.commands.check.RedmineClient")
    def test_check_connection_with_api_key(
        self, mock_client_class, mock_load_config, mock_config
    ):
        """API Keyを指定した接続確認テスト"""
        # モック設定
        mock_load_config.return_value = mock_config
        mock_client_instance = Mock()
        mock_client_instance.test_connection.return_value = {
            "success": True,
            "message": "接続成功",
            "projects_count": 0,
            "projects": [],
            "statuses": [],
        }
        mock_client_class.return_value.__enter__.return_value = mock_client_instance

        # コマンド実行
        result = self.runner.invoke(
            check_command, ["connection", "--api-key", "custom-key"]
        )

        # 検証
        assert result.exit_code == 0
        assert "API Key: 設定済み" in result.stdout

        # 設定が上書きされているか確認
        config_used = mock_client_class.call_args[0][0]
        assert config_used.redmine.api_key == "custom-key"

    @patch("rd_burndown.commands.check.load_config")
    @patch("rd_burndown.commands.check.RedmineClient")
    def test_check_connection_api_error(
        self, mock_client_class, mock_load_config, mock_config
    ):
        """API エラーのテスト"""
        # モック設定
        mock_load_config.return_value = mock_config
        mock_client_instance = Mock()
        mock_client_instance.test_connection.side_effect = RedmineAPIError(
            "API Error occurred"
        )
        mock_client_class.return_value.__enter__.return_value = mock_client_instance

        # コマンド実行
        result = self.runner.invoke(check_command, ["connection"])

        # 検証
        assert result.exit_code == 1
        assert "API Error: API Error occurred" in result.stdout

    @patch("rd_burndown.commands.check.load_config")
    @patch("rd_burndown.commands.check.RedmineClient")
    def test_check_connection_unexpected_error(
        self, mock_client_class, mock_load_config, mock_config
    ):
        """予期しないエラーのテスト"""
        # モック設定
        mock_load_config.return_value = mock_config
        mock_client_instance = Mock()
        mock_client_instance.test_connection.side_effect = Exception("Unexpected error")
        mock_client_class.return_value.__enter__.return_value = mock_client_instance

        # コマンド実行
        result = self.runner.invoke(check_command, ["connection"])

        # 検証
        assert result.exit_code == 1
        assert "Unexpected Error: Unexpected error" in result.stdout

    @patch("rd_burndown.commands.check.load_config")
    def test_check_config(self, mock_load_config, mock_config):
        """設定確認コマンドのテスト"""
        # モック設定
        mock_load_config.return_value = mock_config

        # コマンド実行
        result = self.runner.invoke(check_command, ["config"])

        # 検証
        assert result.exit_code == 0
        assert "設定確認" in result.stdout
        assert "http://test-redmine:3000" in result.stdout
        assert "設定済み" in result.stdout  # API Key
        assert "10秒" in result.stdout  # Timeout
        assert "test-project" in result.stdout
        assert "test-version" in result.stdout
        assert "Asia/Tokyo" in result.stdout
        assert "完了, 解決" in result.stdout
        mock_load_config.assert_called_once_with(None)

    @patch("rd_burndown.commands.check.load_config")
    def test_check_config_with_custom_config_file(self, mock_load_config, mock_config):
        """カスタム設定ファイルでの設定確認テスト"""
        # モック設定
        mock_load_config.return_value = mock_config

        # コマンド実行
        result = self.runner.invoke(
            check_command, ["config", "--config", "/custom/config.yaml"]
        )

        # 検証
        assert result.exit_code == 0
        mock_load_config.assert_called_once_with("/custom/config.yaml")
