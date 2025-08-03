# Terraform開発用devcontainer
FROM mcr.microsoft.com/devcontainers/python:3.12

# 環境変数設定
ENV LAMBROLL_VERSION=1.0.2

# 必要なパッケージインストール
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    curl \
    unzip \
    git \
    jq \
    direnv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# lambrollインストール
# RUN go install github.com/fujiwara/lambroll/cmd/lambroll@v${LAMBROLL_VERSION}

# Terraformプラグインキャッシュディレクトリ作成
RUN mkdir -p /home/vscode/.terraform.d/plugin-cache \
    && chown -R vscode:vscode /home/vscode/.terraform.d

# デフォルトユーザーをvscodeに設定
USER vscode

# uvのインストール
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/home/vscode/.cargo/bin:$PATH"

WORKDIR /workspaces/lambda-in-vpc
