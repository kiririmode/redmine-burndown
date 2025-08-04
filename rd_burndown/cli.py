"""CLI エントリーポイント"""

import typer  # pragma: no cover
from rich.console import Console  # pragma: no cover

from .commands.check import check_command  # pragma: no cover

app = typer.Typer(
    help="Redmine 工数ベース・バーンダウン CLI ツール"
)  # pragma: no cover
console = Console()  # pragma: no cover

# サブコマンドを追加
app.add_typer(
    check_command, name="check", help="Redmineとの疎通確認"
)  # pragma: no cover


def main_entry() -> None:  # pragma: no cover
    """メインエントリーポイント"""
    app()  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    main_entry()  # pragma: no cover
