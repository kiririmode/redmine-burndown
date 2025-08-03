# Redmine 工数ベース・バーンダウン CLI ツール

## 1. ゴール / スコープ

- Redmine の Version（マイルストーン）＝スプリント を対象に、工数（estimated_hours） ベースのバーンダウンを日次で生成・保存・可視化する。
- 可視化は以下を同一チャートで表示する：
  - 実績バーンダウン（残工数）
  - 理想線（初期コミット基準、営業日均等減）
  - スコープ総量（任意で重ね表示）
  - 速度シナリオ線：これまでのペースから算出した 平均ベロシティ／最大ベロシティ／最小ベロシティ を適用した将来の残工数予測
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
- `issues(id, project_id, version_id, parent_id, subject, status_name,
  estimated_hours, closed_on, updated_on, is_leaf, last_seen_at)`
- `issue_journals(issue_id, at, field, old, new)`
  - （estimated_hours／status_id／fixed_version_id など変更履歴）
- `snapshots(date, version_id, scope_hours, remaining_hours, completed_hours,
  ideal_remaining_hours, v_avg, v_max, v_min)`
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

- バーン集計対象は Version に属する「ルート課題（親なし）集合」 に effective_estimate を適用した合算。
- Version 外の子は対象外。Version 移動は当日スナップショットに反映。

### 3.3 スナップショット指標（各日 23:59 JST の「終値」）

- スコープ総量 scope_hours：当日時点で Version に属する全ルート課題の effective_estimate 合計
- 残工数 remaining_hours：同上のうち 完了でない 課題の合計
- 完了工数 completed_hours：scope_hours - remaining_hours
- 初期コミット S0：スプリント開始日の scope_hours（理想線の基準）
- 理想線 ideal_remaining_hours(d)：
  - 営業日総数 D、開始から d 営業日経過 → S0 * (D - d) / D（0 下限）
- 日次バーン量（当日） burn(d)：
  - スコープ変動の影響を除くため、
  - burn(d) = max(0, (remaining(d-1) - remaining(d)) - (scope(d) - scope(d-1)))

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

- 1枚のチャートに重ね描画
  1. 実績バーンダウン（残工数） … 折れ線
  2. 理想線 … 破線
  3. スコープ総量 … 薄色の折れ線（任意）
  4. 速度シナリオ … avg／max／min の 3 本（点線や別スタイル）
- 注記：
  - x 軸は営業日（カレンダー日ではなく）でプロット（祝日・週末は欠番）
  - 途中の**スコープ変動（Δh）**はポイント注記（+△h/-△h）
  - 予測完了日（各シナリオ）をツールチップまたは凡例に表示

---

## 5. CLI ツール仕様

### 5.1 代表コマンド

```bash
rd-burndown init
rd-burndown sync        --project <id|identifier> --version <id|name>
rd-burndown snapshot    --project <...> --version <...> [--at YYYY-MM-DD]
rd-burndown replay      --project <...> --version <...>
# 開始～終了まで全営業日を再生
rd-burndown export      --project <...> --version <...> --fmt csv|json > out.csv
rd-burndown plot        --project <...> --version <...> --out sprint.png \
  [--html sprint.html]
```

### 5.2 設定ファイル（rd-burndown.yaml）

```yaml
redmine:
  base_url: "https://redmine.example.com"
  api_key: "${REDMINE_API_KEY}"    # 環境変数推奨
  timeout_sec: 15
  project_identifier: "myproj"     # or project_id
  version_name: "Sprint-2025.08-1" # or fixed_version_id

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
  chart:
    # "plotly" | "matplotlib"（配布容易性と好みで選択）
    backend: "plotly"
    image_format: "png"    # png/svg
```

## 6. Redmine API 取得戦略（5.x）

- Issues：GET /issues.json?project_id=...&fixed_version_id=...&status_id=*&include=journals,children&limit=100&offset=...
- ページング対応、updated_on で差分同期（set_filter=1 を併用）
- journals.details から estimated_hours／status_id／fixed_version_id の変更を抽出
- Versions：GET /projects/:id/versions.json（start_date/due_date）
- Statuses：GET /issue_statuses.json（表示用途。判定は設定ファイル優先）
- エラーハンドリング：429/5xx は指数バックオフ／再試行。ネットワーク切断時は部分同期をロールバック。

## 7. アーキテクチャ / 実装

### 7.1 技術スタック

- Python 3.11（実行／開発）
- uv（パッケージ・仮想環境管理）
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

1. sync：Version/Issues/Statuses を取得 → issues と issue_journals を更新
2. snapshot：当日23:59 JST基準で as-of 集計 → snapshots に保存
3. velocity 算出：当スプリントの burn(d) から V_avg/V_max/V_min を計算
4. plot/export：CSV/JSON と PNG/HTML を出力

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
