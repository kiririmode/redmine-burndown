"""設定管理"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class RedmineConfig(BaseModel):
    """Redmine設定"""

    base_url: str = Field(default="http://redmine:3000")
    api_key: Optional[str] = Field(default=None)
    timeout_sec: int = Field(default=15)
    project_identifier: Optional[str] = Field(default=None)
    version_name: Optional[str] = Field(default=None)


class SprintConfig(BaseModel):
    """スプリント設定"""

    timezone: str = Field(default="Asia/Tokyo")
    done_statuses: list[str] = Field(default=["完了", "解決"])


class Config(BaseModel):
    """全体設定"""

    redmine: RedmineConfig = Field(default_factory=RedmineConfig)
    sprint: SprintConfig = Field(default_factory=SprintConfig)


def load_config(config_path: Optional[str] = None) -> Config:
    """設定ファイルを読み込み"""
    if config_path is None:
        # デフォルトの設定ファイルパスを探索
        candidates = [
            Path.cwd() / "rd-burndown.yaml",
            Path.home() / ".config" / "rd-burndown" / "config.yaml",
        ]
        config_path = None
        for candidate in candidates:
            if candidate.exists():
                config_path = str(candidate)
                break

    if config_path and Path(config_path).exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return Config(**data)

    # 設定ファイルがない場合はデフォルト設定を返す
    config = Config()

    # 環境変数からAPI_KEYを取得
    if os.getenv("REDMINE_API_KEY"):
        config.redmine.api_key = os.getenv("REDMINE_API_KEY")

    return config
