# Lambda in VPC Terraform Development Container

このdevcontainerは、Lambda in VPCプロジェクトのTerraform開発に最適化された開発環境を提供します。

## 🚀 セットアップ

### 前提条件

- Docker Desktop
- Visual Studio Code
- Dev Containers拡張機能

### 使用方法

1. VS Codeでプロジェクトを開く
2. コマンドパレット（`Cmd+Shift+P` / `Ctrl+Shift+P`）を開く
3. "Dev Containers: Reopen in Container"を実行
4. コンテナのビルドと初期化を待つ

## 📦 インストール済みツール

### 基本ツール

- **Python 3.12** - ベースイメージ
- **AWS CLI** - AWS コマンドラインツール（devcontainer featuresでインストール）
- **Terraform** - Infrastructure as Code（devcontainer featuresでインストール）
- **Node.js** - 各種ツール用（devcontainer featuresでインストール）

### システムパッケージ

- curl - HTTP通信ツール
- unzip - アーカイブ解凍
- git - バージョン管理
- jq - JSON処理

### Claude Code

- **@anthropic-ai/claude-code** - AI開発アシスタント（post-createでインストール）

## 🔧 設定

### コンテナ設定

- ベースイメージ: `mcr.microsoft.com/devcontainers/python:3.12`
- ユーザー: `vscode`
- 作業ディレクトリ: `/workspaces/lambda-in-vpc`

### Terraform設定

- プラグインキャッシュディレクトリ: `/home/vscode/.terraform.d/plugin-cache`

## 📁 現在のプロジェクト構造

```
.
├── .devcontainer/          # devcontainer設定
│   ├── devcontainer.json   # devcontainer設定ファイル
│   ├── Dockerfile          # 開発環境用Dockerイメージ
│   ├── post-create.sh      # 初期セットアップスクリプト
│   └── README.md           # このファイル
├── CLAUDE.md               # プロジェクト詳細ドキュメント
├── README.md               # プロジェクト基本情報
└── 2025-07-19.md          # 作業メモ
```

## 🚧 今後の拡張予定

以下の機能は将来的に追加予定です：

### 追加予定ツール

- **lambroll** - Lambda関数デプロイツール
- **TFLint** - Terraform linter
- **TFSec** - Terraform security scanner
- **Terragrunt** - Terraform wrapper

### Python パッケージ

- boto3 - AWS SDK
- black - コードフォーマッター
- flake8 - コードリンター
- mypy - 型チェッカー
- pytest - テストフレームワーク
- moto - AWSモック

### VS Code拡張機能

- HashiCorp Terraform
- Docker
- Python関連
- Go言語サポート
- YAML/JSON サポート
- GitHub Copilot（利用可能な場合）
- Markdown関連

### プロジェクト構造（計画）

```
.
├── .devcontainer/          # devcontainer設定
├── environments/           # 環境別Terraform設定
│   ├── dev/
│   ├── staging/
│   └── prod/
├── modules/                # Terraformモジュール
│   ├── networking/
│   ├── lambda/
│   ├── storage/
│   ├── monitoring/
│   └── ecr/
├── lambda/                 # Lambda関数（lambroll管理）
│   └── src/
├── docker/                 # Dockerイメージ
│   └── app/
└── scripts/                # 運用スクリプト
```

## 🔐 AWS認証設定

### 方法1: AWS認証情報ファイル

ローカルの `~/.aws/` ディレクトリがコンテナにマウントされます。

### 方法2: 環境変数

```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_DEFAULT_REGION="ap-northeast-1"
```

### 方法3: IAM Roles for Service Accounts (IRSA)

EKS環境などでの利用時

## 🐛 トラブルシューティング

### コンテナが起動しない

1. Docker Desktopが起動しているか確認
2. `Dev Containers: Rebuild Container`を実行

### Terraform初期化エラー

```bash
# プラグインキャッシュをクリア
rm -rf /home/vscode/.terraform.d/plugin-cache/*
make init
```

### AWS認証エラー

```bash
# AWS設定確認
aws configure list
aws sts get-caller-identity
```

### lambrollエラー

```bash
# Go環境確認
go version
which lambroll
```

## 📚 参考リンク

- [Terraform Documentation](https://www.terraform.io/docs)
- [AWS Provider Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [lambroll Documentation](https://github.com/fujiwara/lambroll)
- [Dev Containers Documentation](https://containers.dev/)

## 💡 ヒント

1. **Terraform プラグインキャッシュ**: 初回起動時にプロバイダーがダウンロードされ、以降は高速化されます
2. **Python仮想環境**: 自動的にアクティベートされます
3. **Git設定**: 初回起動時にGit設定を確認してください
4. **pre-commit**: コミット前の自動チェックが設定されています
