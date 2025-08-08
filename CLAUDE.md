# Redmine 工数ベース・バーンダウン CLI ツール

## 1. ゴール / スコープ

- Redmine のチケットを対象に、工数（estimated_hours） ベースのバーンダウンを日次で生成・保存・可視化する。
- **集計対象の指定方法**：
  - **Version指定**: 特定のマイルストーン/スプリントを対象
  - **期日指定**: 指定期日以前の全チケットを対象（リリースバーンダウン）
- 可視化は以下を同一チャートで表示する：
  - 実績バーンダウン（残工数）
  - 理想線（初期コミット基準、営業日均等減）
  - スコープ総量（任意で重ね表示）
  - 速度シナリオ線：これまでのペースから算出した 平均ベロシティ／最大ベロシティ／最小ベロシティ を適用した将来の残工数予測
- **担当者別負荷分析**：誰にどのくらいの工数負荷がかかっているかを日次で集計・可視化する。
- 実装形態は CLI ツール。Redmine REST API からデータを取得し、ローカルDB（SQLite）にスナップショットを蓄積。
- 配布は PyInstaller による単一実行ファイル（exe） を想定。

## 2. 前提・用語

- Redmine：5.x
- 完了ステータス：["完了","解決"]（設定で変更可能）
- 稼働日：土日・日本の祝日を除外（タイムゾーンは Asia/Tokyo）
- チケット見積：estimated_hours を使用
- 親子見積ルール（重要）
  - 「子チケットにすべて estimated_hours が入っていれば子の合計、1つでも未入力があれば親の estimated_hours を採用」
  - 目的：二重計上防止と運用の柔軟性を両立
- 想定スプリント規模：チケット ～50件 程度（ページング＆差分同期で拡張可）

---

## 3. データモデルと集計定義

### 3.1 データモデル（SQLite 概要）

- `versions(id, project_id, name, start_date, due_date)`
- **`releases(id, project_id, due_date, name, description)`**
  - **期日指定バーンダウン用**：Redmineに対応項目なし、ローカル管理専用
  - name: "Release v2.0" 等の識別ラベル
- `issues(id, project_id, version_id, parent_id, subject, status_name,
  estimated_hours, closed_on, updated_on, is_leaf, last_seen_at,
  assigned_to_id, assigned_to_name, due_date)`
  - **assigned_to_id**: 担当者のRedmine内部ID（NULL可）
  - **assigned_to_name**: 担当者名（表示用、NULL可）
  - **due_date**: チケット期日（期日指定モードで使用）
- `issue_journals(issue_id, at, field, old, new)`
  - （estimated_hours／status_id／fixed_version_id／assigned_to_id など変更履歴）
- `snapshots(date, target_type, target_id, scope_hours, remaining_hours, completed_hours,
  ideal_remaining_hours, v_avg, v_max, v_min)`
  - **target_type**: "version" | "release"
  - **target_id**: version_id または release_id
- `assignee_snapshots(date, target_type, target_id, assigned_to_id, assigned_to_name,
  scope_hours, remaining_hours, completed_hours)`
  - **担当者別の日次スナップショット**：assigned_to_id=NULL は未アサイン課題
- `meta(key, value)`（初期スコープ S0、最終スナップショット日 等）

### 3.2 ロールアップ規則（擬似コード）

```python
effective_estimate(issue):
  if issue has children:
    if all children have non-null estimated_hours (recursively satisfied):
      return sum(effective_estimate(child) for child in children_leafs)
    else:
      return issue.estimated_hours or 0
  else:
    return issue.estimated_hours or 0
```

- **Version指定モード**: Version に属する「ルート課題（親なし）集合」 に effective_estimate を適用した合算
- **期日指定モード**: `due_date <= 指定日` の「ルート課題（親なし）集合」 に effective_estimate を適用した合算
- Version 外の子は対象外。Version 移動/期日変更は当日スナップショットに反映。

### 3.3 スナップショット指標（各日 23:59 JST の「終値」）

#### 3.3.1 全体指標（既存）

- スコープ総量 scope_hours：当日時点で対象範囲に属する全ルート課題の effective_estimate 合計
  - **Version指定**: Version に属する課題
  - **期日指定**: `due_date <= 指定日` の課題
- 残工数 remaining_hours：同上のうち 完了でない 課題の合計
- 完了工数 completed_hours：scope_hours - remaining_hours
- 初期コミット S0：開始日の scope_hours（理想線の基準）
  - **Version指定**: Version開始日
  - **期日指定**: 最初のスナップショット日
- 理想線 ideal_remaining_hours(d)：
  - 営業日総数 D、開始から d 営業日経過 → S0 * (D - d) / D（0 下限）
- 日次バーン量（当日） burn(d)：
  - スコープ変動の影響を除くため、
  - burn(d) = max(0, (remaining(d-1) - remaining(d)) - (scope(d) - scope(d-1)))

#### 3.3.2 担当者別指標（新規）

- **担当者別スコープ** assignee_scope_hours(assignee, d)：
  - 担当者別の effective_estimate 合計（親子ルールは全体と同一）
- **担当者別残工数** assignee_remaining_hours(assignee, d)：
  - 担当者別の未完了課題工数合計
- **担当者別完了工数** assignee_completed_hours(assignee, d)：
  - assignee_scope_hours - assignee_remaining_hours
- **未アサイン課題**：assigned_to_id=NULL として別途集計
- **担当変更の扱い**：変更日に旧担当→新担当へ工数移管として記録

### 3.4 ベロシティ定義（「これまでのペース」）

- 対象：当スプリントの営業日ごとの burn(d) シリーズ
- 平均ベロシティ V_avg：mean(burn(d))（0 含む、外れ値除外は任意設定）
- 最大 V_max：max(burn(d))
- 最小 V_min：min(burn(d))（0 のみが続く場合は 0）
- シナリオ線（将来の残）：
  - 残営業日を R として、remaining_today - n * V_x を日毎に直線減衰（0 下限）
  - x ∈ {avg, max, min}
  - 注：V_x = 0 の場合は水平線（リスク視覚化）

---

## 4. 可視化（チャート仕様）

### 4.1 メインバーンダウンチャート

- 1枚のチャートに重ね描画
  1. 実績バーンダウン（残工数） … 折れ線
  2. 理想線 … 破線
  3. スコープ総量 … 薄色の折れ線（任意）
  4. 速度シナリオ … avg／max／min の 3 本（点線や別スタイル）
- 注記：
  - x 軸は営業日（カレンダー日ではなく）でプロット（祝日・週末は欠番）
  - 途中の**スコープ変動（Δh）**はポイント注記（+△h/-△h）
  - 予測完了日（各シナリオ）をツールチップまたは凡例に表示

### 4.2 担当者別負荷チャート（新規）

- **積み上げ面グラフ** または **複数線グラフ** で担当者別残工数を表示
- 各担当者を異なる色で区別、未アサイン課題も含む
- y軸：残工数（時間）、x軸：営業日
- ツールチップ：担当者名、当日残工数、スコープ変動
- **上位N名表示**：工数上位の担当者のみ表示（設定可能、デフォルト10名）
- **個別担当者フィルタ**：特定担当者のみハイライト表示

---

## 5. CLI ツール仕様

### 5.1 代表コマンド

```bash
rd-burndown init

# Version指定モード（従来）
rd-burndown sync        --project <id|identifier> --version <id|name>
rd-burndown snapshot    --project <...> --version <...> [--at YYYY-MM-DD]
rd-burndown replay      --project <...> --version <...>
rd-burndown export      --project <...> --version <...> --fmt csv|json > out.csv
rd-burndown plot        --project <...> --version <...> --out sprint.png

# 期日指定モード（新規）
rd-burndown sync        --project <id|identifier> --due-date YYYY-MM-DD \
  [--name "Release v2.0"]
rd-burndown snapshot    --project <...> --due-date <...> [--at YYYY-MM-DD]
rd-burndown replay      --project <...> --due-date <...>
rd-burndown export      --project <...> --due-date <...> --fmt csv|json > out.csv
rd-burndown plot        --project <...> --due-date <...> --out release.png \
  [--html release.html] [--by-assignee] [--assignee-chart assignee_load.png]

# 共通オプション
# --by-assignee: 担当者別チャートも生成
# --assignee-chart: 担当者別負荷チャートファイル名
# --name: 期日指定時のローカル識別名（デフォルト: "Release-YYYY-MM-DD"）
```

### 5.2 設定ファイル（rd-burndown.yaml）

```yaml
redmine:
  base_url: "https://redmine.example.com"
  api_key: "${REDMINE_API_KEY}"    # 環境変数推奨
  timeout_sec: 15
  project_identifier: "myproj"     # or project_id

  # Version指定モード用
  version_name: "Sprint-2025.08-1" # or fixed_version_id

  # 期日指定モード用
  release_due_date: "2025-12-31"   # YYYY-MM-DD
  release_name: "Release v2.0"     # ローカル識別名

sprint:
  timezone: "Asia/Tokyo"
  business_calendar:
    weekends: [SAT, SUN]
    holidays: JP
  done_statuses: ["完了", "解決"]

rollup:
  # 親子規則は固定（子が全て埋まれば子合計/1つでも空なら親）
  strict_validation: true  # ルール違反検出時に警告を出す

velocity:
  use_business_days: true
  outlier:
    enabled: true
    method: "iqr"      # IQR で極端値除外（任意）
    iqr_k: 1.5

output:
  show_burnup_scope: true
  assignee:
    enabled: true              # 担当者別集計を有効にする
    top_n_display: 10          # 上位N名のみチャート表示
    include_unassigned: true   # 未アサイン課題を含める
    chart_type: "stacked_area" # "stacked_area" | "multi_line"
  chart:
    # "plotly" | "matplotlib"（配布容易性と好みで選択）
    backend: "plotly"
    image_format: "png"    # png/svg
```

## 6. Redmine API 取得戦略（5.x）

### 6.1 Version指定モード（従来）

- Issues：GET /issues.json?project_id=...&fixed_version_id=...&status_id=*&include=journals,children&limit=100&offset=...
- Versions：GET /projects/:id/versions.json（start_date/due_date）

### 6.2 期日指定モード（新規）

- Issues：GET /issues.json?project_id=...&due_date=<=YYYY-MM-DD&status_id=*&include=journals,children&limit=100&offset=...
  - `due_date` フィルターを使用してバージョン指定なしで取得
  - 期日未設定チケット（due_date=NULL）は除外

### 6.3 共通処理

- **assigned_to 情報取得**：レスポンスの `assigned_to.id` と `assigned_to.name` を抽出
- ページング対応、updated_on で差分同期（set_filter=1 を併用）
- journals.details から estimated_hours／status_id／fixed_version_id／due_date／
  **assigned_to_id** の変更を抽出
- Statuses：GET /issue_statuses.json（表示用途。判定は設定ファイル優先）
- **Users（任意）**：GET /users.json
  - 担当者名の正規化、アクティブ状態確認用
- エラーハンドリング：429/5xx は指数バックオフ／再試行。ネットワーク切断時は部分同期をロールバック。

## 7. アーキテクチャ / 実装

### 7.1 技術スタック

- Python 3.11（実行／開発）
- **uv**（パッケージ・仮想環境管理）
  - 依存関係は `pyproject.toml` で管理
  - 開発用依存関係：`uv add --dev <package>`
  - 実行環境構築：`uv sync`
- pandas（集計・整形）
- Plotly（モダン描画・インタラクティブ／kaleidoで PNG 化）
- 代替：Matplotlib（軽量・PyInstaller 相性良）を静的出力用にフォールバック
- jpholiday（日本の祝日）
- SQLite（ローカルスナップショット保存）
- typer / click（CLI）
- httpx / requests（API）
- pydantic（設定スキーマ）
- ruff / black / mypy / pytest（品質）

### 7.2 処理フロー

1. sync：
   - **Version指定**: Version/Issues/Statuses を取得
   - **期日指定**: Issues（期日フィルター）/Statuses を取得
   - → issues と issue_journals を更新
2. snapshot：当日23:59 JST基準で as-of 集計 → snapshots と **assignee_snapshots** に保存
3. velocity 算出：対象範囲の burn(d) から V_avg/V_max/V_min を計算
4. plot/export：CSV/JSON と PNG/HTML を出力（**担当者別チャートを含む**）

### 7.3 ベロシティ計算の実装ポイント

- 営業日ベースで burn(d) を並べる（休業日は欠番）
- IQR 外れ値除外は任意（設定で無効化可）
- スコープ変動が大きい日でも burn(d) は式により純粋な完了寄与分のみ反映

## 8. 配布（PyInstaller）とビルド運用

### 8.1 uv + PyInstaller 手順（例）

```bash
uv venv
uv pip install -e .
uv pip install pyinstaller plotly kaleido pandas jpholiday typer httpx pydantic
pyinstaller -F -n rd-burndown cli_entry.py
```

- 同梱注意点
  - pandas／plotly はサイズ増。軽量配布が必要なら Matplotlib 静的出力モードを既定にし、plotly+kaleido はオプション化
  - kaleido はオフライン PNG 出力に必要（Plotly 使用時）
  - フォント（日本語）を PNG に含めたい場合は Noto Sans CJK などを同梱 or OS 依存にする
  - 設定ファイル探索：$CWD/rd-burndown.yaml → $HOME/.config/rd-burndown/config.yaml の順で解決

### 8.2 CI

- GitHub Actions で Windows 用 exe をビルドし Releases に添付
- スナップショット自動実行は 社内サーバ/PC のタスクスケジューラ（23:59 JST）で snapshot を起動

---

## 9. 品質保証（テスト観点）

- 日付境界：金→月（週末またぎ）、祝日挟み、月末／月初
- スコープ変動：追加 +8h、削除 -5h、見積変更 +3h
- 再オープン：完了→進行→完了 の往復
- 親子規則：
  - (1) 子すべて埋まり＝子合計
  - (2) 子の一部未入力＝親採用
  - (3) 親子両方入力 → ルールに従いつつ 警告 を出す
- 性能：50件規模での sync／snapshot 所要時間、ページング・差分同期の正当性
- 冪等性：同日スナップショットの再実行で同値になること

---

## 10. 開発環境・テスト用Redmine

### 10.1 Docker Compose による Redmine 起動

```bash
# コンテナ起動
docker-compose up -d

# 状態確認
docker-compose ps

# ログ確認
docker-compose logs redmine

# コンテナ停止
docker-compose down
```

### 10.2 API アクセス方法

開発環境では以下の方法でRedmine APIにアクセス可能：

- **コンテナ名による内部アクセス**：`http://redmine:3000`

```bash
# API動作確認例
curl -s "http://redmine:3000/projects.json" | jq .
curl -s "http://redmine:3000/issue_statuses.json" | jq .
curl -s "http://redmine:3000/issues.json" | jq .
```

---

## 11. 開発・品質管理ツール

### 11.1 uv によるパッケージ管理

このプロジェクトは **uv** を使用してPythonの依存関係と仮想環境を管理しています。

```bash
# 開発環境のセットアップ
uv sync

# パッケージの追加
uv add <package-name>

# 開発専用パッケージの追加
uv add --dev <package-name>

# スクリプトの実行
uv run <command>

# テストの実行
uv run pytest
```

### 11.2 pre-commit による品質管理

コミット前に自動的に以下の品質チェックが実行されます：

#### 基本チェック

- **trailing-whitespace**: 行末空白の除去
- **end-of-file-fixer**: ファイル末尾改行の修正
- **check-yaml/toml/json**: 設定ファイルの構文チェック
- **check-added-large-files**: 大容量ファイルの検出
- **check-merge-conflict**: マージコンフリクトの検出
- **debug-statements**: デバッグ文の検出

#### コード品質

- **ruff**: Pythonリンター・フォーマッター（自動修正あり）
- **pyright**: 静的型チェック（TypeScript系）
- **bandit**: セキュリティ脆弱性の検出（rd_burndown/配下のみ）
- **detect-secrets**: 機密情報の検出（.secrets.baselineベースライン使用）

#### 複雑性・品質メトリクス

- **lizard-complexity**: 循環的複雑度チェック（CCN≤10）
- **code-similarity**: コード重複の検出（リファクタリング推奨）
- **test-coverage**: テストカバレッジチェック（**85%以上必須**）

#### ドキュメント

- **markdownlint**: Markdownファイルの文法チェック・自動修正

### 11.3 テスト・カバレッジ設定

```yaml
# pyproject.toml 抜粋
[tool.pytest.ini_options]
addopts = "--cov=rd_burndown --cov-report=term-missing --cov-fail-under=85"

[tool.coverage.report]
fail_under = 85  # 85%未満でCI失敗
```

カバレッジレポートは `htmlcov/` ディレクトリに出力され、詳細な未カバー箇所を確認できます。
