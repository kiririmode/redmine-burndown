"""pytest設定とフィクスチャ"""

from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest
import yaml

from rd_burndown.config import Config, RedmineConfig, SprintConfig


@pytest.fixture
def mock_config():
    """テスト用の設定オブジェクト"""
    return Config(
        redmine=RedmineConfig(
            base_url="http://test-redmine:3000",
            api_key="test-api-key",
            timeout_sec=10,
            project_identifier="test-project",
            version_name="test-version",
        ),
        sprint=SprintConfig(timezone="Asia/Tokyo", done_statuses=["完了", "解決"]),
    )


@pytest.fixture
def temp_config_file():
    """一時的な設定ファイル"""
    config_data = {
        "redmine": {
            "base_url": "http://temp-redmine:3000",
            "api_key": "temp-api-key",
            "timeout_sec": 20,
            "project_identifier": "temp-project",
            "version_name": "temp-version",
        },
        "sprint": {"timezone": "UTC", "done_statuses": ["Done", "Closed"]},
    }

    with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f, default_flow_style=False)
        temp_file = f.name

    yield temp_file

    # クリーンアップ
    Path(temp_file).unlink(missing_ok=True)


@pytest.fixture
def mock_redmine_response():
    """モックRedmineレスポンス"""
    return {
        "projects": {
            "projects": [
                {
                    "id": 1,
                    "identifier": "test-project",
                    "name": "Test Project",
                    "description": "Test Description",
                }
            ],
            "total_count": 1,
            "offset": 0,
            "limit": 25,
        },
        "issue_statuses": {
            "issue_statuses": [
                {"id": 1, "name": "新規", "is_closed": False},
                {"id": 5, "name": "完了", "is_closed": True},
            ]
        },
    }
