"""疎通確認コマンド"""


import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..api import RedmineAPIError, RedmineClient
from ..config import load_config

check_command = typer.Typer()
console = Console()


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

    # 設定を読み込み
    config = load_config(config_path)

    # コマンドライン引数で設定を上書き
    if base_url:
        config.redmine.base_url = base_url
    if api_key:
        config.redmine.api_key = api_key

    console.print("[bold blue]Redmine 疎通確認[/bold blue]")
    console.print(f"URL: {config.redmine.base_url}")
    console.print(f"API Key: {'設定済み' if config.redmine.api_key else '未設定'}")
    console.print()

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

                # プロジェクト情報を表示
                projects = result["projects"]
                console.print(
                    f"\n[bold]プロジェクト数:[/bold] {result['projects_count']}"
                )

                if verbose and projects:
                    project_table = Table(title="プロジェクト一覧")
                    project_table.add_column("ID", style="yellow")
                    project_table.add_column("識別子", style="blue")
                    project_table.add_column("名前", style="green")
                    project_table.add_column("説明")

                    for project in projects:
                        project_table.add_row(
                            str(project.get("id", "")),
                            project.get("identifier", ""),
                            project.get("name", ""),
                            project.get("description", "")[:50]
                            + (
                                "..."
                                if len(project.get("description", "")) > 50
                                else ""
                            ),
                        )

                    console.print(project_table)

                # ステータス情報を表示
                statuses = result["statuses"]
                console.print(f"\n[bold]課題ステータス数:[/bold] {len(statuses)}")

                if verbose and statuses:
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

            else:
                console.print(
                    Panel(
                        f"[bold red]✗ {result['message']}[/bold red]",
                        title="接続結果",
                        border_style="red",
                    )
                )
                raise typer.Exit(1)

    except RedmineAPIError as e:
        console.print(
            Panel(
                f"[bold red]✗ API Error: {str(e)}[/bold red]",
                title="接続結果",
                border_style="red",
            )
        )
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(
            Panel(
                f"[bold red]✗ Unexpected Error: {str(e)}[/bold red]",
                title="接続結果",
                border_style="red",
            )
        )
        raise typer.Exit(1) from e


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
