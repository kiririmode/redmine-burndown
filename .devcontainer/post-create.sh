#!/bin/bash

set -e

npm install -g @anthropic-ai/claude-code

# direnvのbashフック設定
echo "🔧 direnvをbashにフック中..."
if ! grep -q 'eval "$(direnv hook bash)"' ~/.bashrc; then
    echo 'eval "$(direnv hook bash)"' >> ~/.bashrc
    echo "✅ direnv bashフック追加完了"
else
    echo "✅ direnv bashフックは既に設定されています"
fi

# uvとpre-commitセットアップ
echo "🔧 uvとpre-commitをセットアップ中..."
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv tool install pre-commit
pre-commit install

# Install similarity-py for code similarity detection and refactoring
echo "🔧 similarity-pyをインストール中..."
cargo install similarity-py

# 動作確認
echo "🧪 ツール動作確認中..."
docker --version && echo "✅ Docker OK"

echo "✅ post-createスクリプト完了"
