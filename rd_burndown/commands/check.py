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


def _display_projects_info(projects: list, projects_count: int, verbose: bool) -> None:
    """プロジェクト情報を表示"""
    console.print(f"\n[bold]プロジェクト数:[/bold] {projects_count}")

    if not (verbose and projects):
        return

    project_table = Table(title="プロジェクト一覧")
    project_table.add_column("ID", style="yellow")
    project_table.add_column("識別子", style="blue")
    project_table.add_column("名前", style="green")
    project_table.add_column("説明")

    for project in projects:
        description = project.get("description", "")
        truncated_desc = description[:50] + ("..." if len(description) > 50 else "")
        project_table.add_row(
            str(project.get("id", "")),
            project.get("identifier", ""),
            project.get("name", ""),
            truncated_desc,
        )

    console.print(project_table)


def _display_statuses_info(statuses: list, verbose: bool) -> None:
    """ステータス情報を表示"""
    console.print(f"\n[bold]課題ステータス数:[/bold] {len(statuses)}")

    if not (verbose and statuses):
        return

    status_table = Table(title="課題ステータス一覧")
    status_table.add_column("ID", style="yellow")
    status_table.add_column("名前", style="blue")
    status_table.add_column("完了", style="green")

    for status in statuses:
        status_table.add_row(
            str(status.get("id", "")),
            status.get("name", ""),
            "✓" if status.get("is_closed", False) else "",
        )

    console.print(status_table)


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
