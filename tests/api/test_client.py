"""RedmineClient のテスト"""

from unittest.mock import Mock, patch

import httpx
import pytest

from rd_burndown.api.client import RedmineAPIError, RedmineClient


class TestRedmineClient:
    """RedmineClient のテストクラス"""

    def test_init(self, mock_config):
        """初期化のテスト"""
        client = RedmineClient(mock_config)
        assert client.base_url == "http://test-redmine:3000"
        assert client.api_key == "test-api-key"
        assert client.timeout == 10

    @patch("httpx.Client")
    def test_context_manager(self, mock_httpx_client, mock_config):
        """コンテキストマネージャーのテスト"""
        mock_client_instance = Mock()
        mock_httpx_client.return_value = mock_client_instance

        with RedmineClient(mock_config) as client:
            assert client is not None

        mock_client_instance.close.assert_called_once()

    @patch("httpx.Client")
    def test_make_request_success(self, mock_httpx_client, mock_config):
        """正常なAPIリクエストのテスト"""
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {"test": "data"}
        mock_response.headers = {"content-type": "application/json"}
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)
        result = client._make_request("GET", "/test.json")

        assert result == {"test": "data"}
        mock_client_instance.request.assert_called_once_with("GET", "/test.json")

    @patch("httpx.Client")
    def test_make_request_http_error(self, mock_httpx_client, mock_config):
        """HTTPエラーのテスト"""
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_client_instance.request.side_effect = httpx.HTTPStatusError(
            "404", request=Mock(), response=mock_response
        )
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)

        with pytest.raises(RedmineAPIError, match="HTTP 404: Not Found"):
            client._make_request("GET", "/test.json")

    @patch("httpx.Client")
    def test_make_request_connection_error(self, mock_httpx_client, mock_config):
        """接続エラーのテスト"""
        mock_client_instance = Mock()
        mock_client_instance.request.side_effect = httpx.RequestError(
            "Connection failed"
        )
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)

        with pytest.raises(RedmineAPIError, match="Request failed: Connection failed"):
            client._make_request("GET", "/test.json")

    @patch("httpx.Client")
    def test_get_projects(self, mock_httpx_client, mock_config, mock_redmine_response):
        """プロジェクト取得のテスト"""
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.json.return_value = mock_redmine_response["projects"]
        mock_response.headers = {"content-type": "application/json"}
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)
        result = client.get_projects()

        assert result == mock_redmine_response["projects"]
        mock_client_instance.request.assert_called_once_with("GET", "/projects.json")

    @patch("httpx.Client")
    def test_get_issue_statuses(
        self, mock_httpx_client, mock_config, mock_redmine_response
    ):
        """課題ステータス取得のテスト"""
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.json.return_value = mock_redmine_response["issue_statuses"]
        mock_response.headers = {"content-type": "application/json"}
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)
        result = client.get_issue_statuses()

        assert result == mock_redmine_response["issue_statuses"]
        mock_client_instance.request.assert_called_once_with(
            "GET", "/issue_statuses.json"
        )

    @patch("httpx.Client")
    def test_test_connection_success(
        self, mock_httpx_client, mock_config, mock_redmine_response
    ):
        """接続テスト成功のテスト"""
        mock_client_instance = Mock()

        def mock_request(method, endpoint):
            mock_response = Mock()
            mock_response.headers = {"content-type": "application/json"}
            if endpoint == "/projects.json":
                mock_response.json.return_value = mock_redmine_response["projects"]
            elif endpoint == "/issue_statuses.json":
                mock_response.json.return_value = mock_redmine_response[
                    "issue_statuses"
                ]
            return mock_response

        mock_client_instance.request.side_effect = mock_request
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)
        result = client.test_connection()

        assert result["success"] is True
        assert result["message"] == "接続成功"
        assert result["projects_count"] == 1
        assert len(result["projects"]) == 1
        assert len(result["statuses"]) == 2

    @patch("httpx.Client")
    def test_test_connection_failure(self, mock_httpx_client, mock_config):
        """接続テスト失敗のテスト"""
        mock_client_instance = Mock()
        mock_client_instance.request.side_effect = httpx.RequestError(
            "Connection failed"
        )
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)
        result = client.test_connection()

        assert result["success"] is False
        assert "接続失敗" in result["message"]
        assert result["projects_count"] == 0
        assert result["projects"] == []
        assert result["statuses"] == []

    @patch("httpx.Client")
    def test_get_issues_with_journals(self, mock_httpx_client, mock_config):
        """ジャーナル付き課題取得のテスト"""
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {"issues": []}
        mock_response.headers = {"content-type": "application/json"}
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)
        result = client.get_issues(
            project_id="1",
            version_id="10",
            include_journals=True,
            include_children=True,
            updated_on="2025-01-01T00:00:00Z",
        )

        assert result == {"issues": []}
        expected_params = {
            "limit": 100,
            "offset": 0,
            "status_id": "*",
            "project_id": "1",
            "fixed_version_id": "10",
            "updated_on": ">=2025-01-01T00:00:00Z",
            "set_filter": "1",
            "include": "journals,children",
        }
        mock_client_instance.request.assert_called_once_with(
            "GET", "/issues.json", params=expected_params
        )

    @patch("httpx.Client")
    def test_get_issue(self, mock_httpx_client, mock_config):
        """単一課題取得のテスト"""
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {"issue": {}}
        mock_response.headers = {"content-type": "application/json"}
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)
        result = client.get_issue(123, include_journals=True)

        assert result == {"issue": {}}
        mock_client_instance.request.assert_called_once_with(
            "GET", "/issues/123.json", params={"include": "journals"}
        )

    @patch("httpx.Client")
    def test_get_users(self, mock_httpx_client, mock_config):
        """ユーザー取得のテスト"""
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {"users": []}
        mock_response.headers = {"content-type": "application/json"}
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance

        client = RedmineClient(mock_config)
        result = client.get_users(limit=50, offset=10)

        assert result == {"users": []}
        mock_client_instance.request.assert_called_once_with(
            "GET", "/users.json", params={"limit": 50, "offset": 10}
        )
