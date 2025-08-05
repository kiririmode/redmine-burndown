"""snapshot コマンド - スナップショット生成・保存"""

from datetime import date, datetime

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..config import Config, load_config
from ..models import DatabaseManager
from ..snapshot import SnapshotService

snapshot_command = typer.Typer()
console = Console()


def _load_and_override_config(
    config_path: str | None,
    project: str | None,
    version: str | None,
) -> Config:
    """設定を読み込み、コマンドライン引数で上書き"""
    config = load_config(config_path)

    if project:
        config.redmine.project_identifier = project
    if version:
        config.redmine.version_name = version

    return config


def _validate_snapshot_config(config: Config) -> tuple[str, str]:
    """スナップショット生成に必要な設定を検証し、project_id と version_id を返す"""
    if not config.redmine.project_identifier:
        console.print("[red]エラー: プロジェクトが指定されていません[/red]")
        raise typer.Exit(1)

    if not config.redmine.version_name:
        console.print("[red]エラー: バージョンが指定されていません[/red]")
        raise typer.Exit(1)

    return config.redmine.project_identifier, config.redmine.version_name


@snapshot_command.command("create")
def create_snapshot(
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
    at: str | None = typer.Option(
        None, "--at", help="スナップショット対象日 (YYYY-MM-DD形式、省略時は今日)"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="詳細な出力を表示"),
) -> None:
    """指定日時点でのスナップショットを生成・保存"""

    config = _load_and_override_config(config_path, project, version)
    project_id, version_name = _validate_snapshot_config(config)

    # 対象日の解析
    target_date: date
    if at:
        try:
            target_date = datetime.strptime(at, "%Y-%m-%d").date()
        except ValueError:
            console.print("[red]エラー: 日付は YYYY-MM-DD 形式で指定してください[/red]")
            raise typer.Exit(1) from None
    else:
        target_date = date.today()

    console.print("[bold blue]スナップショット生成開始[/bold blue]")
    console.print(f"プロジェクト: {project_id}")
    console.print(f"バージョン: {version_name}")
    console.print(f"対象日: {target_date}")
    console.print(f"データベース: {db_path}")
    console.print()

    # データベース初期化
    db_manager = DatabaseManager(db_path)
    db_manager.initialize_schema()

    try:
        snapshot_service = SnapshotService(db_manager, config, console)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("スナップショット生成中...", total=None)

            result = snapshot_service.create_snapshot(
                project_identifier=project_id,
                version_name=version_name,
                target_date=target_date,
                verbose=verbose,
                progress=progress,
                task_id=task,
            )

            progress.update(task, description="スナップショット生成完了")

        # 結果表示
        console.print()
        console.print("[bold green]✓ スナップショット生成完了[/bold green]")
        console.print(f"バージョンID: {result['version_id']}")
        console.print(f"スコープ総量: {result['scope_hours']:.1f}h")
        console.print(f"残工数: {result['remaining_hours']:.1f}h")
        console.print(f"完了工数: {result['completed_hours']:.1f}h")
        console.print(f"理想残工数: {result['ideal_remaining_hours']:.1f}h")
        console.print(f"担当者数: {result['assignee_count']}")
        console.print(f"処理時間: {result['duration']:.2f}秒")

        if verbose and result.get("warnings"):
            console.print("\n[yellow]警告:[/yellow]")
            for warning in result["warnings"]:
                console.print(f"  - {warning}")

    except Exception as e:
        console.print(f"\n[red]エラー: {str(e)}[/red]")
        if verbose:
            console.print_exception()
        raise typer.Exit(1) from e


@snapshot_command.command("list")
def list_snapshots(
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
    limit: int = typer.Option(10, "--limit", "-l", help="表示する件数"),
) -> None:
    """保存されているスナップショットの一覧を表示"""

    config = _load_and_override_config(config_path, project, version)
    project_id, version_name = _validate_snapshot_config(config)

    console.print("[bold blue]スナップショット一覧[/bold blue]")
    console.print(f"プロジェクト: {project_id}")
    console.print(f"バージョン: {version_name}")
    console.print(f"データベース: {db_path}")
    console.print()

    # データベース初期化
    db_manager = DatabaseManager(db_path)
    db_manager.initialize_schema()

    try:
        with db_manager.get_connection() as conn:
            # バージョンIDを取得
            cursor = conn.execute(
                "SELECT id FROM versions WHERE name = ?", (version_name,)
            )
            version_row = cursor.fetchone()

            if not version_row:
                console.print(
                    "[yellow]指定されたバージョンのデータが見つかりません[/yellow]"
                )
                console.print("まず `rd-burndown sync data` を実行してください")
                return

            version_id = version_row["id"]

            # スナップショット一覧を取得
            cursor = conn.execute(
                """
                SELECT date, scope_hours, remaining_hours, completed_hours,
                       ideal_remaining_hours, v_avg, v_max, v_min
                FROM snapshots
                WHERE version_id = ?
                ORDER BY date DESC
                LIMIT ?
                """,
                (version_id, limit),
            )
            snapshots = cursor.fetchall()

            if not snapshots:
                console.print("[yellow]スナップショットが見つかりません[/yellow]")
                console.print("まず `rd-burndown snapshot create` を実行してください")
                return

            console.print(f"[bold]直近 {len(snapshots)} 件のスナップショット:[/bold]")
            console.print()

            for snapshot in snapshots:
                console.print(f"[bold cyan]{snapshot['date']}[/bold cyan]")
                console.print(f"  スコープ: {snapshot['scope_hours']:.1f}h")
                console.print(f"  残工数: {snapshot['remaining_hours']:.1f}h")
                console.print(f"  完了工数: {snapshot['completed_hours']:.1f}h")
                console.print(f"  理想残工数: {snapshot['ideal_remaining_hours']:.1f}h")
                if snapshot["v_avg"] is not None:
                    console.print(f"  ベロシティ(平均): {snapshot['v_avg']:.1f}h/日")
                console.print()

    except Exception as e:
        console.print(f"\n[red]エラー: {str(e)}[/red]")
        raise typer.Exit(1) from e
