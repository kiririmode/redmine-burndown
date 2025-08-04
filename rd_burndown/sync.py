"""データ同期サービス"""

import time
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.progress import Progress

from .api import RedmineAPIError, RedmineClient
from .models import DatabaseManager, IssueModel


class DataSyncService:
    """Redmine データ同期サービス"""

    def __init__(
        self, client: RedmineClient, db_manager: DatabaseManager, console: Console
    ):
        self.client = client
        self.db_manager = db_manager
        self.console = console
        self.issue_model = IssueModel(db_manager)

    def sync_project_data(
        self,
        project_id: str,
        version_name: str,
        full_sync: bool = False,
        verbose: bool = False,
        progress: Progress | None = None,
        task_id: Any = None,
    ) -> dict[str, Any]:
        """プロジェクトデータを同期"""
        start_time = time.time()
        warnings = []

        # プロジェクト確認
        project_data = self._validate_and_get_project(
            project_id, verbose, progress, task_id
        )

        # バージョン確認
        target_version = self._validate_and_get_version(
            project_id, version_name, verbose, progress, task_id
        )
        version_id = target_version["id"]

        # バージョン情報をDBに保存
        self._save_version(target_version, project_data["id"])

        # 同期設定準備
        last_updated = self._prepare_sync_settings(version_id, full_sync, verbose)

        # 課題データ同期
        issues_synced, journals_synced = self._perform_issues_sync(
            project_data["id"], version_id, last_updated, verbose, progress, task_id
        )

        duration = time.time() - start_time
        return {
            "version_id": version_id,
            "issues_synced": issues_synced,
            "journals_synced": journals_synced,
            "duration": duration,
            "warnings": warnings,
        }

    def _validate_and_get_project(
        self, project_id: str, verbose: bool, progress: Progress | None, task_id: Any
    ) -> dict[str, Any]:
        """プロジェクトの存在確認と取得"""
        if progress and task_id:
            progress.update(task_id, description="プロジェクト確認中...")

        try:
            project_response = self.client.get_project(project_id)
            project_data = project_response["project"]
            if verbose:
                self.console.print(f"プロジェクト: {project_data['name']}")
            return project_data
        except RedmineAPIError as e:
            raise RedmineAPIError(
                f"プロジェクト '{project_id}' が見つかりません"
            ) from e

    def _validate_and_get_version(
        self,
        project_id: str,
        version_name: str,
        verbose: bool,
        progress: Progress | None,
        task_id: Any,
    ) -> dict[str, Any]:
        """バージョンの存在確認と取得"""
        if progress and task_id:
            progress.update(task_id, description="バージョン確認中...")

        versions_response = self.client.get_versions(project_id)
        versions = versions_response.get("versions", [])

        for version in versions:
            if version["name"] == version_name or str(version["id"]) == version_name:
                if verbose:
                    self.console.print(
                        f"バージョン: {version['name']} (ID: {version['id']})"
                    )
                return version

        raise RedmineAPIError(f"バージョン '{version_name}' が見つかりません")

    def _prepare_sync_settings(
        self, version_id: int, full_sync: bool, verbose: bool
    ) -> str | None:
        """同期設定の準備"""
        if full_sync:
            return None

        last_updated = self._get_last_sync_timestamp(version_id)
        if verbose and last_updated:
            self.console.print(f"差分同期: {last_updated} 以降の更新を取得")
        return last_updated

    def _perform_issues_sync(
        self,
        project_id: int,
        version_id: int,
        last_updated: str | None,
        verbose: bool,
        progress: Progress | None,
        task_id: Any,
    ) -> tuple[int, int]:
        """課題データの同期実行"""
        if progress and task_id:
            progress.update(task_id, description="課題データ同期中...")

        return self._sync_issues(project_id, version_id, last_updated, verbose)

    def _save_version(self, version_data: dict[str, Any], project_id: int) -> None:
        """バージョン情報をデータベースに保存"""
        with self.db_manager.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO versions (
                    id, project_id, name, start_date, due_date,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_data["id"],
                    project_id,
                    version_data["name"],
                    version_data.get("created_on"),
                    version_data.get("due_date"),
                    version_data.get("created_on"),
                    version_data.get("updated_on"),
                ),
            )
            conn.commit()

    def _get_last_sync_timestamp(self, version_id: int) -> str | None:
        """最終同期タイムスタンプを取得"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.execute(
                "SELECT MAX(last_seen_at) FROM issues WHERE version_id = ?",
                (version_id,),
            )
            result = cursor.fetchone()
            return result[0] if result and result[0] else None

    def _sync_issues(
        self, project_id: int, version_id: int, last_updated: str | None, verbose: bool
    ) -> tuple[int, int]:
        """課題データを同期"""
        issues_count = 0
        journals_count = 0
        offset = 0
        limit = 100

        while True:
            # 課題データを取得
            response = self.client.get_issues(
                project_id=str(project_id),
                version_id=str(version_id),
                limit=limit,
                offset=offset,
                include_journals=True,
                include_children=True,
                updated_on=last_updated,
            )

            issues = response.get("issues", [])
            if not issues:
                break

            # 各課題を処理
            for issue in issues:
                self._save_issue(issue, verbose)
                issues_count += 1

                # ジャーナル（変更履歴）を処理
                journals = issue.get("journals", [])
                for journal in journals:
                    self._save_journal(issue["id"], journal)
                    journals_count += 1

            # ページング処理
            total_count = response.get("total_count", 0)
            offset += limit

            if verbose:
                self.console.print(
                    f"  処理済み: {min(offset, total_count)}/{total_count} 課題"
                )

            if offset >= total_count:
                break

        return issues_count, journals_count

    def _save_issue(self, issue_data: dict[str, Any], verbose: bool) -> None:
        """課題データをデータベースに保存"""
        # 担当者情報を抽出
        assigned_to = issue_data.get("assigned_to")
        assigned_to_id = assigned_to.get("id") if assigned_to else None
        assigned_to_name = assigned_to.get("name") if assigned_to else None

        # 子課題の有無を判定
        has_children = bool(issue_data.get("children"))
        is_leaf = 0 if has_children else 1

        issue_record = {
            "id": issue_data["id"],
            "project_id": issue_data["project"]["id"],
            "version_id": issue_data.get("fixed_version", {}).get("id"),
            "parent_id": issue_data.get("parent", {}).get("id"),
            "subject": issue_data["subject"],
            "status_name": issue_data["status"]["name"],
            "estimated_hours": issue_data.get("estimated_hours"),
            "closed_on": issue_data.get("closed_on"),
            "updated_on": issue_data.get("updated_on"),
            "is_leaf": is_leaf,
            "assigned_to_id": assigned_to_id,
            "assigned_to_name": assigned_to_name,
            "last_seen_at": datetime.now().isoformat(),
        }

        self.issue_model.upsert_issue(issue_record)

        if verbose:
            assignee_info = f" ({assigned_to_name})" if assigned_to_name else ""
            self.console.print(
                f"  課題 #{issue_data['id']}: {issue_data['subject']}{assignee_info}"
            )

    def _save_journal(self, issue_id: int, journal_data: dict[str, Any]) -> None:
        """ジャーナル（変更履歴）をデータベースに保存"""
        details = journal_data.get("details", [])
        created_on = journal_data.get("created_on")

        for detail in details:
            property_name = detail.get("property")
            name = detail.get("name")
            old_value = detail.get("old_value")
            new_value = detail.get("new_value")

            # 追跡対象のフィールドのみ保存
            trackable_fields = {
                "attr": [
                    "estimated_hours",
                    "status_id",
                    "fixed_version_id",
                    "assigned_to_id",
                ],
            }

            if (
                property_name in trackable_fields
                and name in trackable_fields[property_name]
            ):
                with self.db_manager.get_connection() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO issue_journals (
                            issue_id, at, field, old_value, new_value
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (issue_id, created_on, name, old_value, new_value),
                    )
                    conn.commit()
