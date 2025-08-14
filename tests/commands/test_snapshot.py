"""snapshot コマンドのテスト"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from rd_burndown.commands.snapshot import snapshot_command
from rd_burndown.models import DatabaseManager


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_db_manager():
    return MagicMock(spec=DatabaseManager)


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.redmine.project_identifier = "test-project"
    config.redmine.version_name = "test-version"
    config.redmine.release_due_date = None
    config.redmine.release_name = None
    config.sprint.done_statuses = ["完了", "解決"]
    return config


class TestSnapshotCreateCommand:
    """snapshot create コマンドのテスト"""

    @patch("rd_burndown.commands.snapshot.load_config")
    @patch("rd_burndown.commands.snapshot.DatabaseManager")
    @patch("rd_burndown.commands.snapshot.SnapshotService")
    def test_create_snapshot_success(
        self,
        mock_snapshot_service_class,
        mock_db_manager_class,
        mock_load_config,
        runner,
        mock_config,
    ):
        """正常系: スナップショット作成成功"""
        # モックの設定
        mock_load_config.return_value = mock_config
        mock_db_manager = MagicMock()
        mock_db_manager_class.return_value = mock_db_manager

        mock_snapshot_service = MagicMock()
        mock_snapshot_service_class.return_value = mock_snapshot_service
        mock_snapshot_service.create_snapshot.return_value = {
            "target_id": 1,
            "target_type": "version",
            "target_date": "2025-08-05",
            "scope_hours": 100.0,
            "remaining_hours": 60.0,
            "completed_hours": 40.0,
            "ideal_remaining_hours": 50.0,
            "assignee_count": 3,
            "duration": 1.5,
            "warnings": [],
        }

        # コマンド実行
        result = runner.invoke(
            snapshot_command,
            ["create", "--project", "test-project", "--version", "test-version"],
        )

        # 検証
        assert result.exit_code == 0
        assert "スナップショット生成完了" in result.stdout
        assert "対象ID: 1 (version)" in result.stdout
        assert "スコープ総量: 100.0h" in result.stdout
        assert "残工数: 60.0h" in result.stdout
        assert "完了工数: 40.0h" in result.stdout
        assert "理想残工数: 50.0h" in result.stdout
        assert "担当者数: 3" in result.stdout

        # SnapshotService.create_snapshot が正しく呼ばれたことを確認
        mock_snapshot_service.create_snapshot.assert_called_once()
        call_args = mock_snapshot_service.create_snapshot.call_args[1]
        assert call_args["project_identifier"] == "test-project"
        assert call_args["version_name"] == "test-version"
        assert call_args["release_due_date"] is None
        assert call_args["release_name"] is None
        assert call_args["target_date"] == date.today()

    @patch("rd_burndown.commands.snapshot.load_config")
    @patch("rd_burndown.commands.snapshot.DatabaseManager")
    @patch("rd_burndown.commands.snapshot.SnapshotService")
    def test_create_snapshot_with_date(
        self,
        mock_snapshot_service_class,
        mock_db_manager_class,
        mock_load_config,
        runner,
        mock_config,
    ):
        """指定日でのスナップショット作成"""
        # モックの設定
        mock_load_config.return_value = mock_config
        mock_db_manager = MagicMock()
        mock_db_manager_class.return_value = mock_db_manager

        mock_snapshot_service = MagicMock()
        mock_snapshot_service_class.return_value = mock_snapshot_service
        mock_snapshot_service.create_snapshot.return_value = {
            "target_id": 1,
            "target_type": "version",
            "target_date": "2025-08-01",
            "scope_hours": 100.0,
            "remaining_hours": 80.0,
            "completed_hours": 20.0,
            "ideal_remaining_hours": 75.0,
            "assignee_count": 2,
            "duration": 1.2,
            "warnings": [],
        }

        # コマンド実行
        result = runner.invoke(
            snapshot_command,
            [
                "create",
                "--project",
                "test-project",
                "--version",
                "test-version",
                "--at",
                "2025-08-01",
            ],
        )

        # 検証
        assert result.exit_code == 0
        assert "対象日: 2025-08-01" in result.stdout

        # 指定した日付で呼ばれたことを確認
        call_args = mock_snapshot_service.create_snapshot.call_args[1]
        assert call_args["target_date"] == date(2025, 8, 1)

    @patch("rd_burndown.commands.snapshot.load_config")
    def test_create_snapshot_invalid_date_format(self, mock_load_config, runner):
        """異常系: 不正な日付フォーマット"""
        # 設定ファイルをモック（version のみ指定）
        config = MagicMock()
        config.redmine.project_identifier = "test-project"
        config.redmine.version_name = "test-version"
        config.redmine.release_due_date = None  # due_date は指定しない
        config.redmine.release_name = None
        mock_load_config.return_value = config

        result = runner.invoke(
            snapshot_command,
            [
                "create",
                "--at",
                "invalid-date",
            ],
        )

        assert result.exit_code == 1
        assert "日付は YYYY-MM-DD 形式で指定してください" in result.stdout

    @patch("rd_burndown.commands.snapshot.load_config")
    def test_create_snapshot_missing_project(self, mock_load_config, runner):
        """異常系: プロジェクトが指定されていない"""
        config = MagicMock()
        config.redmine.project_identifier = None
        config.redmine.version_name = "test-version"
        mock_load_config.return_value = config

        result = runner.invoke(snapshot_command, ["create"])

        assert result.exit_code == 1
        assert "プロジェクトが指定されていません" in result.stdout

    @patch("rd_burndown.commands.snapshot.load_config")
    def test_create_snapshot_missing_version(self, mock_load_config, runner):
        """異常系: バージョンと期日の両方が指定されていない"""
        config = MagicMock()
        config.redmine.project_identifier = "test-project"
        config.redmine.version_name = None
        config.redmine.release_due_date = None
        config.redmine.release_name = None
        mock_load_config.return_value = config

        result = runner.invoke(snapshot_command, ["create"])

        assert result.exit_code == 1
        assert (
            "--version または --due-date のいずれかを指定してください" in result.stdout
        )

    @patch("rd_burndown.commands.snapshot.load_config")
    @patch("rd_burndown.commands.snapshot.DatabaseManager")
    @patch("rd_burndown.commands.snapshot.SnapshotService")
    def test_create_snapshot_with_warnings(
        self,
        mock_snapshot_service_class,
        mock_db_manager_class,
        mock_load_config,
        runner,
        mock_config,
    ):
        """警告がある場合のスナップショット作成"""
        # モックの設定
        mock_load_config.return_value = mock_config
        mock_db_manager = MagicMock()
        mock_db_manager_class.return_value = mock_db_manager

        mock_snapshot_service = MagicMock()
        mock_snapshot_service_class.return_value = mock_snapshot_service
        mock_snapshot_service.create_snapshot.return_value = {
            "target_id": 1,
            "target_type": "version",
            "target_date": "2025-08-05",
            "scope_hours": 100.0,
            "remaining_hours": 60.0,
            "completed_hours": 40.0,
            "ideal_remaining_hours": 50.0,
            "assignee_count": 3,
            "duration": 1.5,
            "warnings": ["課題#123: 親子両方に見積もりがあります"],
        }

        # コマンド実行（verbose モード）
        result = runner.invoke(
            snapshot_command,
            [
                "create",
                "--project",
                "test-project",
                "--version",
                "test-version",
                "--verbose",
            ],
        )

        # 検証
        assert result.exit_code == 0
        assert "警告:" in result.stdout
        assert "課題#123: 親子両方に見積もりがあります" in result.stdout


class TestSnapshotListCommand:
    """snapshot list コマンドのテスト"""

    @patch("rd_burndown.commands.snapshot.load_config")
    @patch("rd_burndown.commands.snapshot.DatabaseManager")
    def test_list_snapshots_success(
        self, mock_db_manager_class, mock_load_config, runner, mock_config
    ):
        """正常系: スナップショット一覧表示成功"""
        # モックの設定
        mock_load_config.return_value = mock_config

        mock_db_manager = MagicMock()
        mock_db_manager_class.return_value = mock_db_manager

        # データベースのモック
        mock_conn = MagicMock()
        mock_db_manager.get_connection.return_value.__enter__.return_value = mock_conn

        # バージョン情報のモック
        mock_conn.execute.side_effect = [
            # バージョンID取得
            MagicMock(fetchone=lambda: {"id": 1}),
            # スナップショット一覧取得
            MagicMock(
                fetchall=lambda: [
                    {
                        "date": "2025-08-05",
                        "scope_hours": 100.0,
                        "remaining_hours": 60.0,
                        "completed_hours": 40.0,
                        "ideal_remaining_hours": 50.0,
                        "v_avg": 5.0,
                        "v_max": 10.0,
                        "v_min": 2.0,
                    },
                    {
                        "date": "2025-08-04",
                        "scope_hours": 100.0,
                        "remaining_hours": 70.0,
                        "completed_hours": 30.0,
                        "ideal_remaining_hours": 60.0,
                        "v_avg": 4.0,
                        "v_max": 8.0,
                        "v_min": 1.0,
                    },
                ]
            ),
        ]

        # コマンド実行
        result = runner.invoke(
            snapshot_command,
            ["list", "--project", "test-project", "--version", "test-version"],
        )

        # 検証
        assert result.exit_code == 0
        assert "スナップショット一覧" in result.stdout
        assert "2025-08-05" in result.stdout
        assert "2025-08-04" in result.stdout
        assert "スコープ: 100.0h" in result.stdout
        assert "残工数: 60.0h" in result.stdout
        assert "ベロシティ(平均): 5.0h/日" in result.stdout

    @patch("rd_burndown.commands.snapshot.load_config")
    @patch("rd_burndown.commands.snapshot.DatabaseManager")
    def test_list_snapshots_version_not_found(
        self, mock_db_manager_class, mock_load_config, runner, mock_config
    ):
        """異常系: バージョンが見つからない"""
        # モックの設定
        mock_load_config.return_value = mock_config

        mock_db_manager = MagicMock()
        mock_db_manager_class.return_value = mock_db_manager

        # データベースのモック
        mock_conn = MagicMock()
        mock_db_manager.get_connection.return_value.__enter__.return_value = mock_conn

        # バージョンが見つからない場合
        mock_conn.execute.return_value.fetchone.return_value = None

        # コマンド実行
        result = runner.invoke(
            snapshot_command,
            ["list", "--project", "test-project", "--version", "nonexistent-version"],
        )

        # 検証
        assert result.exit_code == 0
        assert "指定されたバージョンのデータが見つかりません" in result.stdout
        assert "まず `rd-burndown sync data` を実行してください" in result.stdout

    @patch("rd_burndown.commands.snapshot.load_config")
    @patch("rd_burndown.commands.snapshot.DatabaseManager")
    def test_list_snapshots_no_snapshots(
        self, mock_db_manager_class, mock_load_config, runner, mock_config
    ):
        """スナップショットが存在しない場合"""
        # モックの設定
        mock_load_config.return_value = mock_config

        mock_db_manager = MagicMock()
        mock_db_manager_class.return_value = mock_db_manager

        # データベースのモック
        mock_conn = MagicMock()
        mock_db_manager.get_connection.return_value.__enter__.return_value = mock_conn

        mock_conn.execute.side_effect = [
            # バージョンID取得（存在する）
            MagicMock(fetchone=lambda: {"id": 1}),
            # スナップショット一覧取得（空）
            MagicMock(fetchall=lambda: []),
        ]

        # コマンド実行
        result = runner.invoke(
            snapshot_command,
            ["list", "--project", "test-project", "--version", "test-version"],
        )

        # 検証
        assert result.exit_code == 0
        assert "スナップショットが見つかりません" in result.stdout
        assert "まず `rd-burndown snapshot create` を実行してください" in result.stdout

    @patch("rd_burndown.commands.snapshot.load_config")
    @patch("rd_burndown.commands.snapshot.DatabaseManager")
    @patch("rd_burndown.commands.snapshot.SnapshotService")
    def test_create_snapshot_due_date_mode(
        self,
        mock_snapshot_service_class,
        mock_db_manager_class,
        mock_load_config,
        runner,
    ):
        """期日指定モードでのスナップショット作成テスト"""
        # 設定ファイルをモック（期日指定）
        config = MagicMock()
        config.redmine.project_identifier = "test-project"
        config.redmine.version_name = None
        config.redmine.release_due_date = "2025-12-31"
        config.redmine.release_name = "Release v2.0"
        mock_load_config.return_value = config

        # データベースのモック
        mock_db_manager = MagicMock()
        mock_db_manager_class.return_value = mock_db_manager

        # スナップショットサービスのモック
        mock_snapshot_service = MagicMock()
        mock_snapshot_service.create_snapshot.return_value = {
            "target_id": 1,
            "target_type": "release",
            "scope_hours": 200.0,
            "remaining_hours": 150.0,
            "completed_hours": 50.0,
            "ideal_remaining_hours": 120.0,
            "assignee_count": 5,
            "duration": 0.15,
        }
        mock_snapshot_service_class.return_value = mock_snapshot_service

        result = runner.invoke(
            snapshot_command,
            [
                "create",
                "--project",
                "test-project", 
                "--due-date",
                "2025-12-31",
                "--name",
                "Release v2.0",
                "--at",
                "2025-08-15",
            ],
        )

        # 検証
        assert result.exit_code == 0
        assert "スナップショット生成開始" in result.stdout
        assert "モード: 期日指定" in result.stdout
        assert "期日: 2025-12-31" in result.stdout
        assert "対象日: 2025-08-15" in result.stdout
        assert "対象ID: 1 (release)" in result.stdout
        assert "スコープ総量: 200.0h" in result.stdout
        assert "残工数: 150.0h" in result.stdout

    @patch("rd_burndown.commands.snapshot.load_config")
    @patch("rd_burndown.commands.snapshot.DatabaseManager")
    def test_list_snapshots_due_date_mode(
        self, mock_db_manager_class, mock_load_config, runner
    ):
        """期日指定モードでのスナップショット一覧テスト"""
        # 設定ファイルをモック（期日指定）
        config = MagicMock()
        config.redmine.project_identifier = "test-project"
        config.redmine.version_name = None
        config.redmine.release_due_date = "2025-12-31"
        config.redmine.release_name = "Release v2.0"
        mock_load_config.return_value = config

        mock_db_manager = MagicMock()
        mock_db_manager_class.return_value = mock_db_manager

        # データベースのモック
        mock_conn = MagicMock()
        mock_db_manager.get_connection.return_value.__enter__.return_value = mock_conn

        mock_conn.execute.side_effect = [
            # リリースID取得
            MagicMock(fetchone=lambda: {"id": 1}),
            # スナップショット一覧取得
            MagicMock(
                fetchall=lambda: [
                    {
                        "date": "2025-08-15",
                        "target_type": "release",
                        "target_id": 1,
                        "scope_hours": 200.0,
                        "remaining_hours": 150.0,
                        "completed_hours": 50.0,
                        "ideal_remaining_hours": 120.0,
                        "v_avg": 5.0,
                        "v_max": 12.0,
                        "v_min": 2.0,
                    },
                    {
                        "date": "2025-08-14",
                        "target_type": "release", 
                        "target_id": 1,
                        "scope_hours": 200.0,
                        "remaining_hours": 160.0,
                        "completed_hours": 40.0,
                        "ideal_remaining_hours": 130.0,
                        "v_avg": 4.5,
                        "v_max": 10.0,
                        "v_min": 1.5,
                    },
                ]
            ),
        ]

        # コマンド実行
        result = runner.invoke(
            snapshot_command,
            [
                "list",
                "--project",
                "test-project",
                "--due-date", 
                "2025-12-31",
                "--name",
                "Release v2.0",
            ],
        )

        # 検証
        assert result.exit_code == 0
        assert "スナップショット一覧" in result.stdout
        assert "モード: 期日指定" in result.stdout
        assert "期日: 2025-12-31" in result.stdout
        assert "2025-08-15" in result.stdout
        assert "2025-08-14" in result.stdout
        assert "スコープ: 200.0h" in result.stdout
        assert "残工数: 150.0h" in result.stdout
        assert "ベロシティ(平均): 5.0h/日" in result.stdout

    @patch("rd_burndown.commands.snapshot.load_config")
    def test_create_snapshot_both_version_and_due_date_error(
        self, mock_load_config, runner
    ):
        """バージョンと期日の同時指定エラーのテスト"""
        # 設定ファイルをモック（両方指定）
        config = MagicMock()
        config.redmine.project_identifier = "test-project"
        config.redmine.version_name = "Sprint-2025.01"
        config.redmine.release_due_date = "2025-12-31"
        config.redmine.release_name = "Release v2.0"
        mock_load_config.return_value = config

        result = runner.invoke(snapshot_command, ["create"])

        assert result.exit_code == 1
        assert "--version と --due-date は同時に指定できません" in result.stdout

