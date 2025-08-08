"""スナップショット生成・計算サービス"""

import sqlite3
import time
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

import jpholiday
from rich.console import Console
from rich.progress import Progress

from .config import Config
from .models import DatabaseManager, IssueModel, ReleaseModel, SnapshotModel


class SnapshotService:
    """スナップショット生成・計算サービス"""

    def __init__(self, db_manager: DatabaseManager, config: Config, console: Console):
        self.db_manager = db_manager
        self.config = config
        self.console = console
        self.issue_model = IssueModel(db_manager)
        self.snapshot_model = SnapshotModel(db_manager)
        self.release_model = ReleaseModel(db_manager)

    def create_snapshot(
        self,
        project_identifier: str,
        version_name: str | None = None,
        release_due_date: str | None = None,
        release_name: str | None = None,
        target_date: date | None = None,
        verbose: bool = False,
        progress: Progress | None = None,
        task_id: Any = None,
    ) -> dict[str, Any]:
        """指定日時点のスナップショットを生成・保存"""
        start_time = time.time()
        warnings = []

        target_date = target_date or date.today()
        target_id, target_type = self._determine_target(
            project_identifier,
            version_name,
            release_due_date,
            release_name,
            verbose,
            progress,
            task_id,
        )

        issues = self._get_target_issues(
            target_id,
            target_type,
            project_identifier,
            release_due_date,
            target_date,
            verbose,
            progress,
            task_id,
        )

        # 親子関係の解決とeffective_estimateの計算
        if progress and task_id:
            progress.update(task_id, description="工数計算中...")
        issue_estimates = self._calculate_effective_estimates(issues, warnings, verbose)

        # スナップショット計算と保存
        snapshot_data, assignee_snapshots = self._calculate_and_save_snapshots(
            target_id,
            target_type,
            target_date,
            issues,
            issue_estimates,
            warnings,
            verbose,
            progress,
            task_id,
        )

        duration = time.time() - start_time
        return self._build_result(
            target_id,
            target_type,
            target_date,
            snapshot_data,
            assignee_snapshots,
            duration,
            warnings,
        )

    def _determine_target(
        self,
        project_identifier: str,
        version_name: str | None,
        release_due_date: str | None,
        release_name: str | None,
        verbose: bool,
        progress: Progress | None,
        task_id: Any,
    ) -> tuple[int, str]:
        """対象（VersionまたはRelease）を決定"""
        if version_name:
            return self._prepare_version_mode(version_name, verbose, progress, task_id)
        elif release_due_date:
            return self._prepare_release_mode(
                project_identifier,
                release_due_date,
                release_name,
                verbose,
                progress,
                task_id,
            )
        else:
            raise ValueError(
                "version_name または release_due_date のいずれかを指定してください"
            )

    def _get_target_issues(
        self,
        target_id: int,
        target_type: str,
        project_identifier: str,
        release_due_date: str | None,
        target_date: date,
        verbose: bool,
        progress: Progress | None,
        task_id: Any,
    ) -> list:
        """対象課題を取得"""
        if progress and task_id:
            progress.update(task_id, description="課題データを取得中...")

        if target_type == "version":
            issues = self._get_issues_at_date(target_id, target_date)
        else:  # target_type == "release"
            if not release_due_date:
                raise ValueError("release_due_date is required for release mode")
            issues = self._get_issues_by_due_date(
                project_identifier, release_due_date, target_date
            )

        if verbose:
            self.console.print(f"対象課題数: {len(issues)}")
        return issues

    def _calculate_and_save_snapshots(
        self,
        target_id: int,
        target_type: str,
        target_date: date,
        issues: list,
        issue_estimates: dict,
        warnings: list,
        verbose: bool,
        progress: Progress | None,
        task_id: Any,
    ) -> tuple[dict, list]:
        """スナップショット計算と保存"""
        # 全体スナップショットの計算
        if progress and task_id:
            progress.update(task_id, description="全体指標を計算中...")
        snapshot_data = self._calculate_snapshot_metrics(
            target_id, target_type, target_date, issue_estimates, warnings, verbose
        )

        # 担当者別スナップショットの計算
        if progress and task_id:
            progress.update(task_id, description="担当者別指標を計算中...")
        assignee_snapshots = self._calculate_assignee_snapshots(
            target_id, target_type, target_date, issues, issue_estimates, verbose
        )

        # データベースに保存
        if progress and task_id:
            progress.update(task_id, description="データベースに保存中...")
        self.snapshot_model.save_snapshot(snapshot_data)
        for assignee_snapshot in assignee_snapshots:
            self.snapshot_model.save_assignee_snapshot(assignee_snapshot)

        # メタデータの更新
        self._update_metadata(
            target_id, target_type, target_date, snapshot_data["scope_hours"]
        )

        return snapshot_data, assignee_snapshots

    def _build_result(
        self,
        target_id: int,
        target_type: str,
        target_date: date,
        snapshot_data: dict,
        assignee_snapshots: list,
        duration: float,
        warnings: list,
    ) -> dict[str, Any]:
        """結果データを構築"""
        return {
            "target_id": target_id,
            "target_type": target_type,
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

    def _prepare_version_mode(
        self, version_name: str, verbose: bool, progress: Progress | None, task_id: Any
    ) -> tuple[int, str]:
        """バージョン指定モードの準備"""
        if progress and task_id:
            progress.update(task_id, description="バージョン情報を取得中...")

        version_id = self._get_version_id(version_name)
        if not version_id:
            raise ValueError(f"バージョン '{version_name}' が見つかりません")

        if verbose:
            version_info = self._get_version_info(version_id)
            self.console.print(f"バージョン: {version_info.get('name')}")
            self.console.print(
                f"期間: {version_info.get('start_date')} - "
                f"{version_info.get('due_date')}"
            )

        return version_id, "version"

    def _prepare_release_mode(
        self,
        project_identifier: str,
        release_due_date: str,
        release_name: str | None,
        verbose: bool,
        progress: Progress | None,
        task_id: Any,
    ) -> tuple[int, str]:
        """期日指定モードの準備"""
        if progress and task_id:
            progress.update(task_id, description="リリース情報を取得中...")

        # リリース名のデフォルト生成
        final_release_name = release_name or f"Release-{release_due_date}"

        # プロジェクトIDを取得（project_identifierから）
        project_id = self._get_project_id(project_identifier)
        if not project_id:
            raise ValueError(f"プロジェクト '{project_identifier}' が見つかりません")

        # リリース情報をDBから取得
        release_info = self.release_model.get_release_by_criteria(
            project_id, release_due_date, final_release_name
        )
        if not release_info:
            raise ValueError(
                f"リリース '{final_release_name}' "
                f"(期日: {release_due_date}) が見つかりません"
            )

        if verbose:
            self.console.print(f"リリース: {final_release_name}")
            self.console.print(f"期日: {release_due_date}")

        return release_info["id"], "release"

    def _get_project_id(self, project_identifier: str) -> int | None:
        """プロジェクト識別子からIDを取得"""
        # project_identifierが数字の場合はIDとして扱う
        if project_identifier.isdigit():
            return int(project_identifier)

        # プロジェクト名から検索する場合は、issuesテーブルから推定
        with self.db_manager.get_connection() as conn:
            cursor = conn.execute("SELECT DISTINCT project_id FROM issues LIMIT 1")
            row = cursor.fetchone()
            return row["project_id"] if row else None

    def _get_issues_by_due_date(
        self, project_identifier: str, due_date: str, target_date: date
    ) -> list[sqlite3.Row]:
        """期日指定で課題を取得（指定日時点）"""
        project_id = self._get_project_id(project_identifier)
        if not project_id:
            return []

        return self.issue_model.get_root_issues_by_due_date(project_id, due_date)

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
                estimate = self._calculate_leaf_estimate(issue)
            else:
                estimate = self._calculate_parent_estimate(
                    issue,
                    children,
                    issue_dict,
                    warnings,
                    verbose,
                    calc_effective_estimate,
                )

            estimates[issue_id] = estimate
            return estimate

        # ルート課題（parent_id が NULL）から計算開始
        root_issues = [i for i in issues if i["parent_id"] is None]
        for root_issue in root_issues:
            calc_effective_estimate(root_issue["id"])

        return estimates

    def _calculate_leaf_estimate(self, issue: sqlite3.Row | dict[str, Any]) -> float:
        """葉ノードの見積もりを計算"""
        return issue["estimated_hours"] or 0.0

    def _calculate_parent_estimate(
        self,
        issue: sqlite3.Row | dict[str, Any],
        children: Sequence[sqlite3.Row | dict[str, Any]],
        issue_dict: dict[int, Any],
        warnings: list[str],
        verbose: bool,
        calc_func,
    ) -> float:
        """親ノードの見積もりを計算"""
        child_estimates = [calc_func(child["id"]) for child in children]
        all_children_have_estimates = all(
            self._has_all_leaf_estimates(child["id"], issue_dict) for child in children
        )

        if all_children_have_estimates:
            return self._handle_children_estimates(
                issue, children, child_estimates, verbose
            )
        else:
            return self._handle_parent_estimate(issue, children, warnings, verbose)

    def _handle_children_estimates(
        self,
        issue: sqlite3.Row | dict[str, Any],
        children: Sequence[sqlite3.Row | dict[str, Any]],
        child_estimates: list[float],
        verbose: bool,
    ) -> float:
        """子の見積もりを合計する場合の処理"""
        estimate = sum(child_estimates)
        if verbose:
            self.console.print(
                f"課題#{issue['id']}: 子の合計 {estimate}h "
                f"(子課題: {[c['id'] for c in children]})"
            )
        return estimate

    def _handle_parent_estimate(
        self,
        issue: sqlite3.Row | dict[str, Any],
        children: Sequence[sqlite3.Row | dict[str, Any]],
        warnings: list[str],
        verbose: bool,
    ) -> float:
        """親の見積もりを使用する場合の処理"""
        estimate = issue["estimated_hours"] or 0.0
        if verbose:
            self.console.print(
                f"課題#{issue['id']}: 親の値 {estimate}h (一部の子課題に見積なし)"
            )

        # 親子両方に値がある場合は警告
        if issue["estimated_hours"] and any(c["estimated_hours"] for c in children):
            warnings.append(
                f"課題#{issue['id']}: 親子両方に見積もりがあります "
                f"(親: {issue['estimated_hours']}h)"
            )
        return estimate

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
        target_id: int,
        target_type: str,
        target_date: date,
        issue_estimates: dict[int, float],
        warnings: list[str],
        verbose: bool,
    ) -> dict[str, Any]:
        """全体スナップショット指標を計算"""

        # 完了ステータスのセット
        done_statuses = set(self.config.sprint.done_statuses)

        # 課題を取得
        if target_type == "version":
            issues = self.issue_model.get_issues_by_version(target_id)
        else:  # target_type == "release"
            # 期日指定の場合は事前に取得済みの課題を使用するため、
            # ここではissue_estimatesから課題IDを取得してDBから詳細を取得
            issues = []
            with self.db_manager.get_connection() as conn:
                for issue_id in issue_estimates.keys():
                    cursor = conn.execute(
                        "SELECT * FROM issues WHERE id = ?", (issue_id,)
                    )
                    issue = cursor.fetchone()
                    if issue:
                        issues.append(issue)

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
        # 理想線の計算（期日指定モードでは初期スコープから均等減少）
        if target_type == "version":
            version_info = self._get_version_info(target_id)
            ideal_remaining_hours = self._calculate_ideal_remaining(
                version_info, target_date, scope_hours
            )
        else:  # target_type == "release"
            ideal_remaining_hours = self._calculate_ideal_remaining_by_due_date(
                target_date, scope_hours
            )

        # ベロシティの計算
        velocities = self._calculate_velocities(target_id, target_type, target_date)

        if verbose:
            self.console.print(f"スコープ総量: {scope_hours:.1f}h")
            self.console.print(f"残工数: {remaining_hours:.1f}h")
            self.console.print(f"完了工数: {completed_hours:.1f}h")
            self.console.print(f"理想残工数: {ideal_remaining_hours:.1f}h")

        return {
            "date": target_date.isoformat(),
            "target_type": target_type,
            "target_id": target_id,
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
        target_id: int,
        target_type: str,
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
                        "target_type": target_type,
                        "target_id": target_id,
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
        self, target_id: int, target_type: str, target_date: date
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
        self, target_id: int, target_type: str, target_date: date, scope_hours: float
    ) -> None:
        """メタデータを更新"""

        with self.db_manager.get_connection() as conn:
            # 初期スコープ S0 の記録（初回のみ）
            meta_key_prefix = f"initial_scope_{target_type}_{target_id}"
            cursor = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (meta_key_prefix,)
            )
            if not cursor.fetchone():
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (meta_key_prefix, str(scope_hours)),
                )

            # 最終スナップショット日の更新
            last_snapshot_key = f"last_snapshot_{target_type}_{target_id}"
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (last_snapshot_key, target_date.isoformat()),
            )

            conn.commit()

    def _calculate_ideal_remaining_by_due_date(
        self, target_date: date, scope_hours: float
    ) -> float:
        """期日指定モードでの理想残工数を計算"""
        # 期日指定モードでは、初回スナップショット日から期日まで均等減少
        # 簡易実装として、現在は初期スコープを返す
        # TODO: 実際の期日と初回日付を考慮した計算を実装
        return scope_hours
