"""SnapshotService のテスト"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from rd_burndown.models import DatabaseManager
from rd_burndown.snapshot import SnapshotService


@pytest.fixture
def mock_db_manager():
    return MagicMock(spec=DatabaseManager)


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.sprint.done_statuses = ["完了", "解決"]
    return config


@pytest.fixture
def mock_console():
    return MagicMock()


@pytest.fixture
def snapshot_service(mock_db_manager, mock_config, mock_console):
    return SnapshotService(mock_db_manager, mock_config, mock_console)


class TestSnapshotService:
    """SnapshotService のテスト"""

    def test_calculate_effective_estimates_leaf_nodes(self, snapshot_service):
        """effective_estimate計算: 葉ノードのテスト"""
        issues = [
            # 親なし課題（葉ノード）
            {
                "id": 1,
                "parent_id": None,
                "estimated_hours": 10.0,
            },
            {
                "id": 2,
                "parent_id": None,
                "estimated_hours": 20.0,
            },
        ]

        warnings = []
        estimates = snapshot_service._calculate_effective_estimates(
            issues, warnings, False
        )

        assert estimates[1] == 10.0
        assert estimates[2] == 20.0
        assert len(warnings) == 0

    def test_calculate_effective_estimates_parent_child_all_filled(
        self, snapshot_service
    ):
        """effective_estimate計算: 子が全て埋まっている場合（子の合計）"""
        issues = [
            # 親課題
            {
                "id": 1,
                "parent_id": None,
                "estimated_hours": 100.0,  # この値は使われない
            },
            # 子課題（全て見積あり）
            {
                "id": 2,
                "parent_id": 1,
                "estimated_hours": 30.0,
            },
            {
                "id": 3,
                "parent_id": 1,
                "estimated_hours": 40.0,
            },
        ]

        warnings = []
        estimates = snapshot_service._calculate_effective_estimates(
            issues, warnings, False
        )

        # 親は子の合計
        assert estimates[1] == 70.0  # 30.0 + 40.0
        assert estimates[2] == 30.0
        assert estimates[3] == 40.0

    def test_calculate_effective_estimates_parent_child_some_empty(
        self, snapshot_service
    ):
        """effective_estimate計算: 子の一部が空の場合（親の値）"""
        issues = [
            # 親課題
            {
                "id": 1,
                "parent_id": None,
                "estimated_hours": 50.0,
            },
            # 子課題（一部に見積なし）
            {
                "id": 2,
                "parent_id": 1,
                "estimated_hours": 20.0,
            },
            {
                "id": 3,
                "parent_id": 1,
                "estimated_hours": None,  # 見積なし
            },
        ]

        warnings = []
        estimates = snapshot_service._calculate_effective_estimates(
            issues, warnings, False
        )

        # 親の値を使用
        assert estimates[1] == 50.0
        assert estimates[2] == 20.0
        assert estimates[3] == 0.0

    def test_calculate_effective_estimates_parent_child_both_filled_warning(
        self, snapshot_service
    ):
        """effective_estimate計算: 親子両方に値がある場合の警告"""
        issues = [
            # 親課題（見積あり）
            {
                "id": 1,
                "parent_id": None,
                "estimated_hours": 50.0,
            },
            # 子課題（見積あり）
            {
                "id": 2,
                "parent_id": 1,
                "estimated_hours": 20.0,
            },
            # 子課題（見積なし）
            {
                "id": 3,
                "parent_id": 1,
                "estimated_hours": None,
            },
        ]

        warnings = []
        estimates = snapshot_service._calculate_effective_estimates(
            issues, warnings, False
        )

        # 親の値を使用
        assert estimates[1] == 50.0
        # 警告が出ることを確認
        assert len(warnings) == 1
        assert "課題#1: 親子両方に見積もりがあります" in warnings[0]

    def test_calculate_effective_estimates_nested_hierarchy(self, snapshot_service):
        """effective_estimate計算: 多階層の親子関係"""
        issues = [
            # ルート親課題
            {
                "id": 1,
                "parent_id": None,
                "estimated_hours": None,
            },
            # 中間親課題
            {
                "id": 2,
                "parent_id": 1,
                "estimated_hours": None,
            },
            # 葉課題
            {
                "id": 3,
                "parent_id": 2,
                "estimated_hours": 15.0,
            },
            {
                "id": 4,
                "parent_id": 2,
                "estimated_hours": 25.0,
            },
            # 別の葉課題
            {
                "id": 5,
                "parent_id": 1,
                "estimated_hours": 30.0,
            },
        ]

        warnings = []
        estimates = snapshot_service._calculate_effective_estimates(
            issues, warnings, False
        )

        # 葉から積み上がる
        assert estimates[3] == 15.0
        assert estimates[4] == 25.0
        assert estimates[5] == 30.0
        assert estimates[2] == 40.0  # 15.0 + 25.0
        assert estimates[1] == 70.0  # 40.0 + 30.0

    def test_count_business_days(self, snapshot_service):
        """営業日計算のテスト"""
        # 平日のみの期間
        start = date(2025, 8, 4)  # 月曜日
        end = date(2025, 8, 8)  # 金曜日

        with patch("rd_burndown.snapshot.jpholiday.is_holiday", return_value=False):
            business_days = snapshot_service._count_business_days(start, end)
            assert business_days == 4  # 月火水木の4日間

    def test_count_business_days_with_weekend(self, snapshot_service):
        """週末を含む営業日計算"""
        start = date(2025, 8, 4)  # 月曜日
        end = date(2025, 8, 11)  # 翌週月曜日

        with patch("rd_burndown.snapshot.jpholiday.is_holiday", return_value=False):
            business_days = snapshot_service._count_business_days(start, end)
            assert business_days == 5  # 月火水木金の5日間（土日除く）

    def test_count_business_days_with_holiday(self, snapshot_service):
        """祝日を含む営業日計算"""
        start = date(2025, 8, 4)  # 月曜日
        end = date(2025, 8, 8)  # 金曜日

        # 8/6（水）が祝日の場合
        def mock_is_holiday(d):
            return d == date(2025, 8, 6)

        with patch(
            "rd_burndown.snapshot.jpholiday.is_holiday", side_effect=mock_is_holiday
        ):
            business_days = snapshot_service._count_business_days(start, end)
            assert business_days == 3  # 月火木の3日間（水は祝日で除く）

    def test_calculate_ideal_remaining(self, snapshot_service):
        """理想線計算のテスト"""
        version_info = {
            "start_date": "2025-08-01",
            "due_date": "2025-08-08",
        }

        initial_scope = 100.0
        target_date = date(2025, 8, 5)  # 開始から4日後

        with patch.object(snapshot_service, "_count_business_days") as mock_count:
            # 総営業日数: 5日、経過営業日数: 3日
            mock_count.side_effect = [5, 3]

            ideal_remaining = snapshot_service._calculate_ideal_remaining(
                version_info, target_date, initial_scope
            )

            # 理想線: 100.0 * (5 - 3) / 5 = 40.0
            assert ideal_remaining == 40.0

    def test_calculate_ideal_remaining_no_dates(self, snapshot_service):
        """理想線計算: 日付情報がない場合"""
        version_info = {
            "start_date": None,
            "due_date": None,
        }

        ideal_remaining = snapshot_service._calculate_ideal_remaining(
            version_info, date.today(), 100.0
        )

        assert ideal_remaining == 0.0

    def test_calculate_assignee_snapshots(self, snapshot_service):
        """担当者別スナップショット計算のテスト"""
        version_id = 1
        target_date = date(2025, 8, 5)

        issues = [
            # ルート課題（担当者A）
            {
                "id": 1,
                "parent_id": None,
                "assigned_to_id": 10,
                "assigned_to_name": "担当者A",
                "status_name": "進行中",
            },
            # ルート課題（担当者B）
            {
                "id": 2,
                "parent_id": None,
                "assigned_to_id": 20,
                "assigned_to_name": "担当者B",
                "status_name": "完了",
            },
            # ルート課題（未アサイン）
            {
                "id": 3,
                "parent_id": None,
                "assigned_to_id": None,
                "assigned_to_name": None,
                "status_name": "進行中",
            },
            # 子課題（除外される）
            {
                "id": 4,
                "parent_id": 1,
                "assigned_to_id": 30,
                "assigned_to_name": "担当者C",
                "status_name": "進行中",
            },
        ]

        issue_estimates = {
            1: 30.0,
            2: 40.0,
            3: 20.0,
            4: 10.0,  # 子課題なので集計対象外
        }

        snapshots = snapshot_service._calculate_assignee_snapshots(
            version_id, "version", target_date, issues, issue_estimates, False
        )

        # ルート課題のみが対象
        assert len(snapshots) == 3

        # 担当者A（進行中）
        snapshot_a = next(s for s in snapshots if s["assigned_to_id"] == 10)
        assert snapshot_a["assigned_to_name"] == "担当者A"
        assert snapshot_a["scope_hours"] == 30.0
        assert snapshot_a["remaining_hours"] == 30.0  # 進行中
        assert snapshot_a["completed_hours"] == 0.0

        # 担当者B（完了）
        snapshot_b = next(s for s in snapshots if s["assigned_to_id"] == 20)
        assert snapshot_b["assigned_to_name"] == "担当者B"
        assert snapshot_b["scope_hours"] == 40.0
        assert snapshot_b["remaining_hours"] == 0.0  # 完了
        assert snapshot_b["completed_hours"] == 40.0

        # 未アサイン（進行中）
        snapshot_unassigned = next(s for s in snapshots if s["assigned_to_id"] is None)
        assert snapshot_unassigned["assigned_to_name"] is None
        assert snapshot_unassigned["scope_hours"] == 20.0
        assert snapshot_unassigned["remaining_hours"] == 20.0  # 進行中
        assert snapshot_unassigned["completed_hours"] == 0.0

    @patch("rd_burndown.snapshot.time.time")
    def test_create_snapshot_integration(self, mock_time, snapshot_service):
        """create_snapshot の統合テスト"""
        # time.time() のモック
        mock_time.side_effect = [1000.0, 1002.5]  # 開始時刻、終了時刻

        # データベースモックの設定
        mock_conn = MagicMock()
        context_manager = snapshot_service.db_manager.get_connection.return_value
        context_manager.__enter__.return_value = mock_conn

        # バージョン情報のモック
        mock_conn.execute.side_effect = [
            # バージョンID取得
            MagicMock(fetchone=lambda: {"id": 1}),
            # バージョン情報取得
            MagicMock(
                fetchone=lambda: {
                    "id": 1,
                    "start_date": "2025-08-01",
                    "due_date": "2025-08-08",
                }
            ),
            # メタデータ取得（初期スコープ）
            MagicMock(fetchone=lambda: None),
            # メタデータ更新（初期スコープ保存）
            MagicMock(),
            # メタデータ更新（最終スナップショット日保存）
            MagicMock(),
        ]
        mock_conn.commit = MagicMock()

        # IssueModel のモック
        mock_issues = [
            {
                "id": 1,
                "parent_id": None,
                "estimated_hours": 50.0,
                "status_name": "進行中",
                "assigned_to_id": 10,
                "assigned_to_name": "担当者A",
            },
        ]

        with patch.object(
            snapshot_service.issue_model,
            "get_issues_by_version",
            return_value=mock_issues,
        ):
            # SnapshotModel のモック
            snapshot_service.snapshot_model.save_snapshot = MagicMock()
            snapshot_service.snapshot_model.save_assignee_snapshot = MagicMock()

            # メソッドのモック
            snapshot_service._calculate_ideal_remaining = MagicMock(return_value=25.0)
            snapshot_service._calculate_velocities = MagicMock(
                return_value={"avg": 5.0, "max": 10.0, "min": 2.0}
            )

            # テスト実行
            result = snapshot_service.create_snapshot(
                project_identifier="test-project",
                version_name="test-version",
                target_date=date(2025, 8, 5),
                verbose=False,
            )

            # 結果検証
            assert result["target_id"] == 1
            assert result["target_type"] == "version"
            assert result["target_date"] == "2025-08-05"
            assert result["scope_hours"] == 50.0
            assert result["remaining_hours"] == 50.0  # 進行中
            assert result["completed_hours"] == 0.0
            assert result["ideal_remaining_hours"] == 25.0
            assert result["assignee_count"] == 1
            assert result["duration"] == 2.5

            # 保存メソッドが呼ばれたことを確認
            snapshot_service.snapshot_model.save_snapshot.assert_called_once()
            snapshot_service.snapshot_model.save_assignee_snapshot.assert_called_once()
