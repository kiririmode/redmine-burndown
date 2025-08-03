"""Redmine API クライアント"""

import json
from typing import Any

import httpx

from ..config import Config


class RedmineAPIError(Exception):
    """Redmine API エラー"""

    pass


class RedmineClient:
    """Redmine API Client"""

    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.redmine.base_url
        self.api_key = config.redmine.api_key
        self.timeout = config.redmine.timeout_sec

        # HTTPクライアントを初期化
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Redmine-API-Key"] = self.api_key

        self.client = httpx.Client(
            base_url=self.base_url, headers=headers, timeout=self.timeout
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        """API リクエストを実行"""
        try:
            response = self.client.request(method, endpoint, **kwargs)
            response.raise_for_status()

            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            else:
                return {"text": response.text}

        except httpx.HTTPStatusError as e:
            raise RedmineAPIError(
                f"HTTP {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise RedmineAPIError(f"Request failed: {str(e)}") from e
        except json.JSONDecodeError as e:
            raise RedmineAPIError(f"Invalid JSON response: {str(e)}") from e

    def get_projects(self) -> dict[str, Any]:
        """プロジェクト一覧を取得"""
        return self._make_request("GET", "/projects.json")

    def get_project(self, project_id: str) -> dict[str, Any]:
        """特定プロジェクトを取得"""
        return self._make_request("GET", f"/projects/{project_id}.json")

    def get_issue_statuses(self) -> dict[str, Any]:
        """課題ステータス一覧を取得"""
        return self._make_request("GET", "/issue_statuses.json")

    def get_issues(
        self,
        project_id: str | None = None,
        version_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """課題一覧を取得"""
        params = {"limit": limit, "offset": offset, "status_id": "*"}

        if project_id:
            params["project_id"] = project_id
        if version_id:
            params["fixed_version_id"] = version_id

        return self._make_request("GET", "/issues.json", params=params)

    def get_versions(self, project_id: str) -> dict[str, Any]:
        """プロジェクトのバージョン（マイルストーン）一覧を取得"""
        return self._make_request("GET", f"/projects/{project_id}/versions.json")

    def test_connection(self) -> dict[str, Any]:
        """接続テスト（軽量なエンドポイントを使用）"""
        try:
            # まずはプロジェクト一覧で接続テスト
            projects_response = self.get_projects()

            # ステータス一覧も取得
            statuses_response = self.get_issue_statuses()

            return {
                "success": True,
                "message": "接続成功",
                "projects_count": projects_response.get("total_count", 0),
                "projects": projects_response.get("projects", []),
                "statuses": statuses_response.get("issue_statuses", []),
            }

        except RedmineAPIError as e:
            return {
                "success": False,
                "message": f"接続失敗: {str(e)}",
                "projects_count": 0,
                "projects": [],
                "statuses": [],
            }
