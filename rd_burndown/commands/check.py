"""疎通確認コマンド"""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..api import RedmineAPIError, RedmineClient
from ..config import Config, load_config

check_command = typer.Typer()
console = Console()


def _load_and_override_config(
    config_path: str | None, base_url: str | None, api_key: str | None
) -> Config:
    """設定を読み込み、コマンドライン引数で上書き"""
    config = load_config(config_path)

    if base_url:
        config.redmine.base_url = base_url
    if api_key:
        config.redmine.api_key = api_key

    return config


def _print_connection_header(config: Config) -> None:
    """接続確認のヘッダー情報を表示"""
    console.print("[bold blue]Redmine 疎通確認[/bold blue]")
    console.print(f"URL: {config.redmine.base_url}")
    console.print(f"API Key: {'設定済み' if config.redmine.api_key else '未設定'}")
    console.print()


def _create_info_table(
    title: str, items: list, columns: list[dict[str, str]], count: int | None = None
) -> None:
    """情報テーブルを作成・表示する共通関数"""
    if count is not None:
        console.print(f"\n[bold]{title}数:[/bold] {count}")

    if not items:
        return

    table = Table(title=f"{title}一覧")
    for col in columns:
        table.add_column(col["name"], style=col.get("style", ""))

    for item in items:
        row = []
        for col in columns:
            value = item.get(col["key"], "")
            if col.get("truncate"):
                value = value[:50] + ("..." if len(value) > 50 else "")
            if col.get("transform"):
                value = col["transform"](value)
            row.append(str(value))
        table.add_row(*row)

    console.print(table)


def _display_projects_info(projects: list, projects_count: int, verbose: bool) -> None:
    """プロジェクト情報を表示"""
    if not verbose:
        console.print(f"\n[bold]プロジェクト数:[/bold] {projects_count}")
        return

    columns = [
        {"name": "ID", "key": "id", "style": "yellow"},
        {"name": "識別子", "key": "identifier", "style": "blue"},
        {"name": "名前", "key": "name", "style": "green"},
        {"name": "説明", "key": "description", "truncate": True},
    ]
    _create_info_table("プロジェクト", projects, columns, projects_count)


def _display_statuses_info(statuses: list, verbose: bool) -> None:
    """ステータス情報を表示"""
    if not verbose:
        console.print(f"\n[bold]課題ステータス数:[/bold] {len(statuses)}")
        return

    columns = [
        {"name": "ID", "key": "id", "style": "yellow"},
        {"name": "名前", "key": "name", "style": "blue"},
        {
            "name": "完了",
            "key": "is_closed",
            "style": "green",
            "transform": lambda x: "✓" if x else "",
        },
    ]
    _create_info_table("課題ステータス", statuses, columns, len(statuses))


def _handle_connection_error(error: Exception) -> None:
    """接続エラーを処理"""
    if isinstance(error, RedmineAPIError):
        console.print(
            Panel(
                f"[bold red]✗ API Error: {str(error)}[/bold red]",
                title="接続結果",
                border_style="red",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]✗ Unexpected Error: {str(error)}[/bold red]",
                title="接続結果",
                border_style="red",
            )
        )
    raise typer.Exit(1) from error


@check_command.command("connection")
def check_connection(
    config_path: str | None = typer.Option(
        None, "--config", "-c", help="設定ファイルのパス"
    ),
    base_url: str | None = typer.Option(None, "--url", help="Redmine ベースURL"),
    api_key: str | None = typer.Option(None, "--api-key", help="API キー"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="詳細な情報を表示"),
) -> None:
    """Redmine との疎通確認"""

    config = _load_and_override_config(config_path, base_url, api_key)
    _print_connection_header(config)

    try:
        with RedmineClient(config) as client:
            result = client.test_connection()

            if result["success"]:
                console.print(
                    Panel(
                        f"[bold green]✓ {result['message']}[/bold green]",
                        title="接続結果",
                        border_style="green",
                    )
                )

                _display_projects_info(
                    result["projects"], result["projects_count"], verbose
                )
                _display_statuses_info(result["statuses"], verbose)
            else:
                console.print(
                    Panel(
                        f"[bold red]✗ {result['message']}[/bold red]",
                        title="接続結果",
                        border_style="red",
                    )
                )
                raise typer.Exit(1)

    except (RedmineAPIError, Exception) as e:
        _handle_connection_error(e)


@check_command.command("config")
def check_config(
    config_path: str | None = typer.Option(
        None, "--config", "-c", help="設定ファイルのパス"
    ),
) -> None:
    """設定ファイルの確認"""

    config = load_config(config_path)

    console.print("[bold blue]設定確認[/bold blue]")

    # Redmine 設定
    redmine_table = Table(title="Redmine 設定")
    redmine_table.add_column("項目", style="blue")
    redmine_table.add_column("値", style="green")

    redmine_table.add_row("Base URL", config.redmine.base_url)
    redmine_table.add_row("API Key", "設定済み" if config.redmine.api_key else "未設定")
    redmine_table.add_row("Timeout", f"{config.redmine.timeout_sec}秒")
    redmine_table.add_row("Project ID", config.redmine.project_identifier or "未設定")
    redmine_table.add_row("Version Name", config.redmine.version_name or "未設定")

    console.print(redmine_table)

    # スプリント設定
    sprint_table = Table(title="スプリント設定")
    sprint_table.add_column("項目", style="blue")
    sprint_table.add_column("値", style="green")

    sprint_table.add_row("Timezone", config.sprint.timezone)
    sprint_table.add_row("完了ステータス", ", ".join(config.sprint.done_statuses))

    console.print(sprint_table)
