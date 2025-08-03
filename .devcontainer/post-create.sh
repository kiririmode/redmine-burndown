#!/bin/bash

# Lambda in VPC Terraform開発環境セットアップスクリプト

set -e

npm install -g @anthropic-ai/claude-code

# lambrollのインストール
echo "📦 lambrollをインストール中..."
if ! command -v lambroll &> /dev/null; then
    go install github.com/fujiwara/lambroll/cmd/lambroll@latest
    echo "✅ lambrollインストール完了"
else
    echo "✅ lambrollは既にインストールされています"
fi

# direnvのbashフック設定
echo "🔧 direnvをbashにフック中..."
if ! grep -q 'eval "$(direnv hook bash)"' ~/.bashrc; then
    echo 'eval "$(direnv hook bash)"' >> ~/.bashrc
    echo "✅ direnv bashフック追加完了"
else
    echo "✅ direnv bashフックは既に設定されています"
fi

# pre-commitセットアップ
echo "🔧 pre-commitをセットアップ中..."
uv tool install pre-commit
pre-commit install

# 動作確認
echo "🧪 ツール動作確認中..."
docker --version && echo "✅ Docker OK"
lambroll --version && echo "✅ lambroll OK"

echo "✅ post-createスクリプト完了"
