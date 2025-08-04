"""sync コマンド - Redmine からデータを同期"""

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..api import RedmineAPIError, RedmineClient
from ..config import Config, load_config
from ..models import DatabaseManager
from ..sync import DataSyncService

sync_command = typer.Typer()
console = Console()


def _load_and_override_config(
    config_path: str | None,
    base_url: str | None,
    api_key: str | None,
    project: str | None,
    version: str | None,
) -> Config:
    """設定を読み込み、コマンドライン引数で上書き"""
    config = load_config(config_path)

    if base_url:
        config.redmine.base_url = base_url
    if api_key:
        config.redmine.api_key = api_key
    if project:
        config.redmine.project_identifier = project
    if version:
        config.redmine.version_name = version

    return config


def _validate_sync_config(config: Config) -> tuple[str, str]:
    """同期に必要な設定を検証し、project_id と version_id を返す"""
    if not config.redmine.project_identifier:
        console.print("[red]エラー: プロジェクトが指定されていません[/red]")
        raise typer.Exit(1)

    if not config.redmine.version_name:
        console.print("[red]エラー: バージョンが指定されていません[/red]")
        raise typer.Exit(1)

    return config.redmine.project_identifier, config.redmine.version_name


@sync_command.command("data")
def sync_data(
    config_path: str | None = typer.Option(
        None, "--config", "-c", help="設定ファイルのパス"
    ),
    base_url: str | None = typer.Option(None, "--url", help="Redmine ベースURL"),
    api_key: str | None = typer.Option(None, "--api-key", help="API キー"),
    project: str | None = typer.Option(
        None, "--project", "-p", help="プロジェクトID または識別子"
    ),
    version: str | None = typer.Option(
        None, "--version", "-v", help="バージョンID または名前"
    ),
    db_path: str = typer.Option(
        "./burndown.db", "--db", help="データベースファイルのパス"
    ),
    full_sync: bool = typer.Option(
        False, "--full", help="全データを再同期（差分同期ではない）"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="詳細な出力を表示"),
) -> None:
    """Redmine からデータを同期"""

    config = _load_and_override_config(config_path, base_url, api_key, project, version)
    project_id, version_name = _validate_sync_config(config)

    console.print("[bold blue]データ同期開始[/bold blue]")
    console.print(f"プロジェクト: {project_id}")
    console.print(f"バージョン: {version_name}")
    console.print(f"データベース: {db_path}")
    console.print(f"同期モード: {'完全同期' if full_sync else '差分同期'}")
    console.print()

    # データベース初期化
    db_manager = DatabaseManager(db_path)
    db_manager.initialize_schema()

    try:
        with RedmineClient(config) as client:
            sync_service = DataSyncService(client, db_manager, console)

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                sync_task = progress.add_task("同期中...", total=None)

                result = sync_service.sync_project_data(
                    project_id=project_id,
                    version_name=version_name,
                    full_sync=full_sync,
                    verbose=verbose,
                    progress=progress,
                    task_id=sync_task,
                )

                progress.update(sync_task, description="同期完了")

            # 結果表示
            console.print()
            console.print("[bold green]✓ 同期完了[/bold green]")
            console.print(f"バージョンID: {result['version_id']}")
            console.print(f"課題数: {result['issues_synced']}")
            console.print(f"ジャーナル数: {result['journals_synced']}")
            console.print(f"処理時間: {result['duration']:.2f}秒")

            if verbose and result.get("warnings"):
                console.print("\n[yellow]警告:[/yellow]")
                for warning in result["warnings"]:
                    console.print(f"  - {warning}")

    except RedmineAPIError as e:
        console.print(f"\n[red]API エラー: {str(e)}[/red]")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"\n[red]予期しないエラー: {str(e)}[/red]")
        if verbose:
            console.print_exception()
        raise typer.Exit(1) from e


@sync_command.command("status")
def sync_status(
    config_path: str | None = typer.Option(
        None, "--config", "-c", help="設定ファイルのパス"
    ),
    project: str | None = typer.Option(
        None, "--project", "-p", help="プロジェクトID または識別子"
    ),
    version: str | None = typer.Option(
        None, "--version", "-v", help="バージョンID または名前"
    ),
    db_path: str = typer.Option(
        "./burndown.db", "--db", help="データベースファイルのパス"
    ),
) -> None:
    """同期状況を確認"""

    config = _load_and_override_config(config_path, None, None, project, version)
    project_id, version_name = _validate_sync_config(config)

    console.print("[bold blue]同期状況確認[/bold blue]")
    console.print(f"プロジェクト: {project_id}")
    console.print(f"バージョン: {version_name}")
    console.print(f"データベース: {db_path}")
    console.print()

    # データベース初期化
    db_manager = DatabaseManager(db_path)
    db_manager.initialize_schema()

    try:
        with db_manager.get_connection() as conn:
            # バージョン情報を取得
            cursor = conn.execute(
                """
                SELECT v.*,
                       COUNT(i.id) as issue_count,
                       MAX(i.last_seen_at) as last_sync_at
                FROM versions v
                LEFT JOIN issues i ON v.id = i.version_id
                WHERE v.name = ?
                GROUP BY v.id
                """,
                (version_name,),
            )
            version_info = cursor.fetchone()

            if not version_info:
                console.print(
                    "[yellow]指定されたバージョンのデータが見つかりません[/yellow]"
                )
                console.print("まず `rd-burndown sync data` を実行してください")
                return

            console.print(f"バージョンID: {version_info['id']}")
            console.print(f"プロジェクトID: {version_info['project_id']}")
            console.print(f"開始日: {version_info['start_date'] or 'なし'}")
            console.print(f"期限日: {version_info['due_date'] or 'なし'}")
            console.print(f"課題数: {version_info['issue_count']}")
            console.print(f"最終同期: {version_info['last_sync_at'] or 'なし'}")

            # 担当者別統計
            cursor = conn.execute(
                """
                SELECT assigned_to_name,
                       COUNT(*) as count,
                       SUM(CASE WHEN estimated_hours IS NOT NULL
                                THEN estimated_hours ELSE 0 END) as total_hours
                FROM issues
                WHERE version_id = ?
                GROUP BY assigned_to_name
                ORDER BY total_hours DESC
                """,
                (version_info["id"],),
            )
            assignee_stats = cursor.fetchall()

            if assignee_stats:
                console.print("\n[bold]担当者別統計:[/bold]")
                for stat in assignee_stats:
                    assignee = stat["assigned_to_name"] or "未アサイン"
                    console.print(
                        f"  {assignee}: {stat['count']}件 ({stat['total_hours']:.1f}h)"
                    )

    except Exception as e:
        console.print(f"\n[red]エラー: {str(e)}[/red]")
        raise typer.Exit(1) from e
