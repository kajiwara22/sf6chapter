# ADR-038: Dependabot + GitHub Actions による依存関係自動更新の導入

## ステータス

承認済み - 2026-05-05

## 文脈

### 現状の課題

本リポジトリは以下の5つの package で構成されており、依存管理が分散している。

| package | 言語 | 依存管理 | デプロイ先 |
|---|---|---|---|
| `packages/local` | Python / uv | `pyproject.toml` + `uv.lock` | ローカルPC / Docker |
| `packages/gcp-functions/check-new-video` | Python / uv | `pyproject.toml` + `uv.lock` | Cloud Functions |
| `packages/obs-title-updater` | Python / uv | `pyproject.toml` | ローカルPC |
| `packages/report-generator` | Python / uv | `pyproject.toml` | ローカルPC |
| `packages/web` | TypeScript / pnpm | `package.json` | Cloudflare Pages |

現状 `.github/workflows/` は空であり、CI が存在しない。依存ライブラリのセキュリティ更新が遅延するリスクがある。

### `gcp-functions/check-new-video` の `requirements.txt` について

Cloud Functions は過去 `requirements.txt` を必要としていたが、Google Cloud Functions が uv をサポートするようになったため、現在は `pyproject.toml` / `uv.lock` による uv 管理に移行済みである。`requirements.txt` は移行前の遺物であり、Dependabot の対象外とするとともに、このADRの実装時に削除する。

## 決定事項

### 1. Dependabot の設定

#### グルーピング戦略

package 単位で依存更新を集約し、1つの package につき1つのPRとする。細かくPRを分けると対応コストが増えるため、package 内の全依存をまとめて更新する。

#### スケジュール

全 package とも `weekly`（週次）とする。`daily` はノイズが多く、`monthly` は更新が溜まりすぎるため、週次が最適。

#### 対象エコシステム

| package | エコシステム | 対象ディレクトリ |
|---|---|---|
| `local` | `pip` (uv) | `packages/local` |
| `gcp-functions/check-new-video` | `pip` (uv) | `packages/gcp-functions/check-new-video` |
| `obs-title-updater` | `pip` (uv) | `packages/obs-title-updater` |
| `report-generator` | `pip` (uv) | `packages/report-generator` |
| `web` | `npm` (pnpm) | `packages/web` |

### 2. マージ方針

| バージョン種別 | マージ方針 |
|---|---|
| `patch` | CI 通過で auto-merge |
| `minor` | 手動レビュー・マージ |
| `major` | 手動レビュー・マージ（破壊的変更のため慎重に） |

セキュリティアドバイザリに起因する更新（Dependabot Security Update）は、バージョン種別に関係なく優先的に手動でレビュー・マージする。

### 3. CI（GitHub Actions）で担保する内容

#### CI が通ることを auto-merge の条件とする

package ごとに以下を実行する GitHub Actions ワークフローを整備する。

**`packages/local`**
- `uv sync --frozen`（lock file との整合性チェック）
- `ruff check src/`
- `ruff format --check src/`

**`packages/gcp-functions/check-new-video`**
- `uv sync --frozen`
- `ruff check .`（`ruff.toml` または `pyproject.toml` に設定があれば）
- `pytest`（既存テストを実行）

**`packages/obs-title-updater`**
- `uv sync --frozen`
- `ruff check src/`
- `ruff format --check src/`

**`packages/report-generator`**
- `uv sync --frozen`
- `ruff check src/`
- `ruff format --check src/`

**`packages/web`**
- `pnpm install --frozen-lockfile`
- `pnpm run typecheck`（`tsc --noEmit`）
- `pnpm run build`

#### CI の範囲についての制約事項

- `packages/web` はE2Eテストが存在しないため、ビルドとタイプチェックの通過のみを担保とする。E2Eテストの整備は別課題とする。
- `packages/local` は `opencv-python` 等の重いライブラリを含むため、実際の動作テストはCIで担保しない。`uv sync --frozen` によるインストール互換性の確認と lint にとどめる。
- `packages/gcp-functions/check-new-video` は本番稼働しているため、CI として pytest を必須にする（現時点で既存テストあり）。

### 4. `requirements.txt` の削除

`packages/gcp-functions/check-new-video/requirements.txt` をリポジトリから削除する。uv による管理（`pyproject.toml` + `uv.lock`）を唯一の依存管理とし、二重管理による混乱を防ぐ。

## 結果

### 良い点

- 依存ライブラリのセキュリティ更新が自動化され、対応漏れが減る
- patch 更新の auto-merge により、手動作業コストを削減できる
- CI により、依存更新による lint エラー・型エラー・ビルド失敗を早期に検知できる
- `requirements.txt` 削除により、`gcp-functions` の依存管理が uv に一本化される

### 制約・トレードオフ

- `packages/web` はE2Eテストがないため、動作の正しさはビルド成功でしか担保できない
- `packages/local` は重いライブラリのため、CI での `uv sync` に時間がかかる可能性がある（キャッシュで緩和）
- `minor` / `major` 更新は手動レビューが必要であり、更新が溜まった場合は対応コストが発生する
- uv の GitHub Actions サポートは `astral-sh/setup-uv` アクション経由で提供されており、これを利用する
