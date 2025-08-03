"""CLI エントリーポイント"""


import typer
from rich.console import Console

from .commands.check import check_command

app = typer.Typer(help="Redmine 工数ベース・バーンダウン CLI ツール")
console = Console()

# サブコマンドを追加
app.add_typer(check_command, name="check", help="Redmineとの疎通確認")


def main_entry() -> None:
    """メインエントリーポイント"""
    app()


if __name__ == "__main__":
    main_entry()
