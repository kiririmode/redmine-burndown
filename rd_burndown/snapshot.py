"""スナップショット生成・計算サービス"""

import sqlite3
import time
from datetime import date, datetime, timedelta
from typing import Any

import jpholiday
from rich.console import Console
from rich.progress import Progress

from .config import Config
from .models import DatabaseManager, IssueModel, SnapshotModel


class SnapshotService:
    """スナップショット生成・計算サービス"""

    def __init__(self, db_manager: DatabaseManager, config: Config, console: Console):
        self.db_manager = db_manager
        self.config = config
        self.console = console
        self.issue_model = IssueModel(db_manager)
        self.snapshot_model = SnapshotModel(db_manager)

    def create_snapshot(
        self,
        project_identifier: str,
        version_name: str,
        target_date: date,
        verbose: bool = False,
        progress: Progress | None = None,
        task_id: Any = None,
    ) -> dict[str, Any]:
        """指定日時点のスナップショットを生成・保存"""
        start_time = time.time()
        warnings = []

        # バージョン情報の取得
        if progress and task_id:
            progress.update(task_id, description="バージョン情報を取得中...")

        version_id = self._get_version_id(version_name)
        if not version_id:
            raise ValueError(f"バージョン '{version_name}' が見つかりません")

        version_info = self._get_version_info(version_id)
        if verbose:
            self.console.print(f"バージョンID: {version_id}")
            self.console.print(
                f"期間: {version_info['start_date']} - {version_info['due_date']}"
            )

        # 課題データの取得（指定日時点）
        if progress and task_id:
            progress.update(task_id, description="課題データを取得中...")

        issues = self._get_issues_at_date(version_id, target_date)
        if verbose:
            self.console.print(f"対象課題数: {len(issues)}")

        # 親子関係の解決とeffective_estimateの計算
        if progress and task_id:
            progress.update(task_id, description="工数計算中...")

        issue_estimates = self._calculate_effective_estimates(issues, warnings, verbose)

        # 全体スナップショットの計算
        if progress and task_id:
            progress.update(task_id, description="全体指標を計算中...")

        snapshot_data = self._calculate_snapshot_metrics(
            version_id, version_info, target_date, issue_estimates, warnings, verbose
        )

        # 担当者別スナップショットの計算
        if progress and task_id:
            progress.update(task_id, description="担当者別指標を計算中...")

        assignee_snapshots = self._calculate_assignee_snapshots(
            version_id, target_date, issues, issue_estimates, verbose
        )

        # データベースに保存
        if progress and task_id:
            progress.update(task_id, description="データベースに保存中...")

        self.snapshot_model.save_snapshot(snapshot_data)

        for assignee_snapshot in assignee_snapshots:
            self.snapshot_model.save_assignee_snapshot(assignee_snapshot)

        # メタデータの更新（初回スナップショット日の記録など）
        self._update_metadata(version_id, target_date, snapshot_data["scope_hours"])

        duration = time.time() - start_time

        return {
            "version_id": version_id,
            "target_date": target_date.isoformat(),
            "scope_hours": snapshot_data["scope_hours"],
            "remaining_hours": snapshot_data["remaining_hours"],
            "completed_hours": snapshot_data["completed_hours"],
            "ideal_remaining_hours": snapshot_data["ideal_remaining_hours"],
            "assignee_count": len(assignee_snapshots),
            "duration": duration,
            "warnings": warnings,
        }

    def _get_version_id(self, version_name: str) -> int | None:
        """バージョン名からIDを取得"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.execute(
                "SELECT id FROM versions WHERE name = ?", (version_name,)
            )
            row = cursor.fetchone()
            return row["id"] if row else None

    def _get_version_info(self, version_id: int) -> dict[str, Any]:
        """バージョン情報を取得"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,))
            row = cursor.fetchone()
            return dict(row) if row else {}

    def _get_issues_at_date(
        self, version_id: int, target_date: date
    ) -> list[sqlite3.Row]:
        """指定日時点での課題状態を取得（ジャーナル履歴を考慮）"""
        # まず現在の課題を取得
        issues = self.issue_model.get_issues_by_version(version_id)

        # TODO: 指定日以降の変更履歴を巻き戻す処理
        # 現在は簡易実装として現在の状態をそのまま返す
        # 本格実装時は issue_journals テーブルから履歴を取得して巻き戻し処理を行う

        return issues

    def _calculate_effective_estimates(
        self, issues: list[sqlite3.Row], warnings: list[str], verbose: bool
    ) -> dict[int, float]:
        """各課題のeffective_estimateを計算（親子ルール適用）"""
        issue_dict = {issue["id"]: issue for issue in issues}
        estimates = {}

        def calc_effective_estimate(issue_id: int) -> float:
            """再帰的にeffective_estimateを計算"""
            if issue_id in estimates:
                return estimates[issue_id]

            issue = issue_dict.get(issue_id)
            if not issue:
                return 0.0

            # 子課題を取得
            children = [i for i in issues if i["parent_id"] == issue_id]

            if not children:
                # 葉ノード：自身のestimated_hoursを使用
                estimate = issue["estimated_hours"] or 0.0
            else:
                # 親ノード：子が全て埋まっていれば子の合計、そうでなければ親の値
                child_estimates = []
                all_children_have_estimates = True

                for child in children:
                    child_estimate = calc_effective_estimate(child["id"])
                    child_estimates.append(child_estimate)

                    # 子の estimated_hours が NULL の場合（再帰的にチェック）
                    if not self._has_all_leaf_estimates(child["id"], issue_dict):
                        all_children_have_estimates = False

                if all_children_have_estimates:
                    estimate = sum(child_estimates)
                    if verbose:
                        self.console.print(
                            f"課題#{issue_id}: 子の合計 {estimate}h "
                            f"(子課題: {[c['id'] for c in children]})"
                        )
                else:
                    estimate = issue["estimated_hours"] or 0.0
                    if verbose:
                        self.console.print(
                            f"課題#{issue_id}: 親の値 {estimate}h "
                            f"(一部の子課題に見積なし)"
                        )

                    # 親子両方に値がある場合は警告
                    if issue["estimated_hours"] and any(
                        c["estimated_hours"] for c in children
                    ):
                        warnings.append(
                            f"課題#{issue_id}: 親子両方に見積もりがあります "
                            f"(親: {issue['estimated_hours']}h)"
                        )

            estimates[issue_id] = estimate
            return estimate

        # ルート課題（parent_id が NULL）から計算開始
        root_issues = [i for i in issues if i["parent_id"] is None]
        for root_issue in root_issues:
            calc_effective_estimate(root_issue["id"])

        return estimates

    def _has_all_leaf_estimates(
        self, issue_id: int, issue_dict: dict[int, Any]
    ) -> bool:
        """指定課題の全ての葉ノードに見積もりがあるかチェック"""
        issue = issue_dict.get(issue_id)
        if not issue:
            return False

        # 子課題を取得
        children = [i for i in issue_dict.values() if i["parent_id"] == issue_id]

        if not children:
            # 葉ノード：自身に見積もりがあるかチェック
            return issue["estimated_hours"] is not None
        else:
            # 親ノード：全ての子が再帰的に見積もりを持つかチェック
            return all(
                self._has_all_leaf_estimates(child["id"], issue_dict)
                for child in children
            )

    def _calculate_snapshot_metrics(
        self,
        version_id: int,
        version_info: dict[str, Any],
        target_date: date,
        issue_estimates: dict[int, float],
        warnings: list[str],
        verbose: bool,
    ) -> dict[str, Any]:
        """全体スナップショット指標を計算"""

        # 完了ステータスのセット
        done_statuses = set(self.config.sprint.done_statuses)

        # 課題を取得
        issues = self.issue_model.get_issues_by_version(version_id)

        # ルート課題のみを対象に集計
        scope_hours = 0.0
        remaining_hours = 0.0

        for issue in issues:
            if issue["parent_id"] is None:  # ルート課題のみ
                estimate = issue_estimates.get(issue["id"], 0.0)
                scope_hours += estimate

                if issue["status_name"] not in done_statuses:
                    remaining_hours += estimate

        completed_hours = scope_hours - remaining_hours

        # 理想線の計算
        ideal_remaining_hours = self._calculate_ideal_remaining(
            version_info, target_date, scope_hours
        )

        # ベロシティの計算（簡易実装）
        velocities = self._calculate_velocities(version_id, target_date)

        if verbose:
            self.console.print(f"スコープ総量: {scope_hours:.1f}h")
            self.console.print(f"残工数: {remaining_hours:.1f}h")
            self.console.print(f"完了工数: {completed_hours:.1f}h")
            self.console.print(f"理想残工数: {ideal_remaining_hours:.1f}h")

        return {
            "date": target_date.isoformat(),
            "version_id": version_id,
            "scope_hours": scope_hours,
            "remaining_hours": remaining_hours,
            "completed_hours": completed_hours,
            "ideal_remaining_hours": ideal_remaining_hours,
            "v_avg": velocities["avg"],
            "v_max": velocities["max"],
            "v_min": velocities["min"],
        }

    def _calculate_assignee_snapshots(
        self,
        version_id: int,
        target_date: date,
        issues: list[sqlite3.Row],
        issue_estimates: dict[int, float],
        verbose: bool,
    ) -> list[dict[str, Any]]:
        """担当者別スナップショットを計算"""

        done_statuses = set(self.config.sprint.done_statuses)
        assignee_stats: dict[int | None, dict[str, float]] = {}
        assignee_names: dict[int | None, str | None] = {}

        # ルート課題のみを対象に担当者別に集計
        for issue in issues:
            if issue["parent_id"] is not None:  # 子課題はスキップ
                continue

            assignee_id = issue["assigned_to_id"]
            assignee_name = issue["assigned_to_name"]
            estimate = issue_estimates.get(issue["id"], 0.0)

            if assignee_id not in assignee_stats:
                assignee_stats[assignee_id] = {
                    "scope_hours": 0.0,
                    "remaining_hours": 0.0,
                    "completed_hours": 0.0,
                }
                assignee_names[assignee_id] = assignee_name

            assignee_stats[assignee_id]["scope_hours"] += estimate

            if issue["status_name"] not in done_statuses:
                assignee_stats[assignee_id]["remaining_hours"] += estimate

        # completed_hours の計算
        for stats in assignee_stats.values():
            stats["completed_hours"] = stats["scope_hours"] - stats["remaining_hours"]

        # 結果の構築
        snapshots = []
        for assignee_id, stats in assignee_stats.items():
            if stats["scope_hours"] > 0:  # 工数がある担当者のみ
                snapshots.append(
                    {
                        "date": target_date.isoformat(),
                        "version_id": version_id,
                        "assigned_to_id": assignee_id,
                        "assigned_to_name": assignee_names[assignee_id],
                        "scope_hours": stats["scope_hours"],
                        "remaining_hours": stats["remaining_hours"],
                        "completed_hours": stats["completed_hours"],
                    }
                )

        if verbose:
            self.console.print(f"担当者別統計: {len(snapshots)}人")
            for snapshot in snapshots:
                name = snapshot["assigned_to_name"] or "未アサイン"
                self.console.print(
                    f"  {name}: スコープ{snapshot['scope_hours']:.1f}h, "
                    f"残{snapshot['remaining_hours']:.1f}h"
                )

        return snapshots

    def _calculate_ideal_remaining(
        self, version_info: dict[str, Any], target_date: date, initial_scope: float
    ) -> float:
        """理想線（理想残工数）を計算"""

        start_date_str = version_info.get("start_date")
        due_date_str = version_info.get("due_date")

        if not start_date_str or not due_date_str:
            return 0.0

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
        except ValueError:
            return 0.0

        # 営業日数を計算
        total_business_days = self._count_business_days(start_date, due_date)
        elapsed_business_days = self._count_business_days(start_date, target_date)

        if total_business_days <= 0:
            return 0.0

        # 理想線: S0 * (D - d) / D
        remaining_business_days = max(0, total_business_days - elapsed_business_days)
        ideal_remaining = initial_scope * remaining_business_days / total_business_days

        return max(0.0, ideal_remaining)

    def _count_business_days(self, start_date: date, end_date: date) -> int:
        """営業日数をカウント（土日祝日を除く）"""
        if start_date >= end_date:
            return 0

        business_days = 0
        current_date = start_date

        while current_date < end_date:
            # 土日をチェック
            if current_date.weekday() < 5:  # 0=月曜, 4=金曜
                # 日本の祝日をチェック
                if not jpholiday.is_holiday(current_date):
                    business_days += 1

            current_date += timedelta(days=1)

        return business_days

    def _calculate_velocities(
        self, version_id: int, target_date: date
    ) -> dict[str, float]:
        """ベロシティを計算（簡易実装）"""

        # TODO: 本格実装
        # 過去のスナップショットから burn(d) を計算してベロシティを算出
        # 現在は仮の値を返す

        return {
            "avg": 0.0,
            "max": 0.0,
            "min": 0.0,
        }

    def _update_metadata(
        self, version_id: int, target_date: date, scope_hours: float
    ) -> None:
        """メタデータを更新"""

        with self.db_manager.get_connection() as conn:
            # 初期スコープ S0 の記録（初回のみ）
            cursor = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (f"initial_scope_{version_id}",)
            )
            if not cursor.fetchone():
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (f"initial_scope_{version_id}", str(scope_hours)),
                )

            # 最終スナップショット日の更新
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (f"last_snapshot_{version_id}", target_date.isoformat()),
            )

            conn.commit()
