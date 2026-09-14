# ADR-046: GCP Functions（check-new-video）の廃止

## ステータス

採用 - 2026-09-14

## 文脈

### 現状

`packages/gcp-functions/check-new-video` は、Cloud Scheduler から 2 時間毎に呼び出され、以下の処理を行っていた：

1. YouTube Data API（`forMine=True`）で自分の新着動画を取得
2. PS5 自動アップロード動画のタイトル自動書き換え（ADR-027）
3. Firestore の `processed_videos` コレクションに `status="queued"` を書き込み（キュー投入）

ローカル PC 側（`packages/local/`）は、ADR-036 で Pub/Sub を廃止して以降、Firestore の `status="queued"` レコードをポーリング（`--mode once` / `--mode daemon`）して処理していた。

### 課題

- 実際の運用では動画 ID を直接指定する `--mode test --video-id <ID>` が主な処理経路となっており、自動検知パイプライン（Scheduler → Function → Firestore キュー）は利用されていない
- Cloud Function・Cloud Scheduler・Pub/Sub・Secret Manager・専用サービスアカウントなど、未使用の GCP リソースが残存し、運用・課金・セキュリティ上の管理コストとなっている
- コードベースにも `packages/gcp-functions/`、専用 CI ワークフロー、Dependabot 設定などが残り、メンテナンス対象が増えている

## 決定

`packages/gcp-functions/check-new-video` を廃止し、関連する GCP リソースを削除する。

### 削除対象（コード）

- `packages/gcp-functions/` ディレクトリ全体
- `.github/workflows/ci-check-new-video.yml`
- `.github/dependabot.yml` の `packages/gcp-functions/check-new-video` エントリ
- ルート `README.md` / `CLAUDE.md` のアーキテクチャ・構成・環境変数などの記述

### 削除対象（GCP リソース）

| リソース | 識別子 |
|---------|--------|
| Cloud Scheduler ジョブ | `check-new-video-schedule`（asia-northeast1） |
| Cloud Function（Gen2） | `check-new-video`（asia-northeast1） |
| Pub/Sub トピック | `sf6-new-video`（ほか候補あり） |
| Pub/Sub サブスクリプション | `new-video-trigger` / `sf6-video-process-sub` |
| Secret Manager シークレット | `youtube-client-id` / `youtube-client-secret` / `youtube-refresh-token` |
| サービスアカウント | `check-new-video-sa` / `cloud-scheduler-invoker` |

削除手順の詳細は [docs/GCP_RESOURCE_DELETION.md](../GCP_RESOURCE_DELETION.md) を参照。

### 削除しないリソース（継続利用）

- **Firestore の `processed_videos` コレクション**: ローカル PC が重複防止・状態管理（`FirestoreClient`）で引き続き利用するため残す
- **OAuth クライアント（`client_secrets.json` の元）**: ローカル PC の YouTube Data API / Vertex AI 認証で利用するため残す
- **Vertex AI / YouTube Data API / Firestore API**: ローカル PC が直接利用するため有効のまま残す

## トレードオフと帰結

### メリット

- 未使用の GCP リソースが削除され、課金・セキュリティ・運用の管理コストが低減する
- リポジトリから未使用コード・CI・Dependabot 設定が消え、メンテナンス対象が減る

### デメリット・注意点

- **自動キュー投入がなくなる**: `--mode once` / `--mode daemon` は Firestore に `queued` レコードが存在する場合のみ処理する。廃止後は自動的にキューが積まれないため、動画処理は `--mode test --video-id <ID>` による直接指定が主経路になる
- **PS5 自動タイトル書き換え（ADR-027）の移設**: 当機能は `check-new-video` 内に実装されていた。引き続き必要であれば、ローカル PC 側または OBS タイトルアップデータ側への移設が必要
- **`packages/local` に残る Pub/Sub の残骸**: `src/pubsub/` モジュールと `google-cloud-pubsub` 依存は未使用のまま残存する（ADR-036 時点で意図的に残置）。別途削除を検討する

## 実装チェックリスト

- [x] `packages/gcp-functions/` の削除
- [x] `.github/workflows/ci-check-new-video.yml` の削除
- [x] `.github/dependabot.yml` から該当エントリを削除
- [x] `README.md` / `CLAUDE.md` の記述更新
- [x] 本 ADR の作成
- [ ] GCP リソースの削除（[docs/GCP_RESOURCE_DELETION.md](../GCP_RESOURCE_DELETION.md) 参照）
- [ ] `docs/architecture.drawio` の更新（GCP ブロックの除去） — 別途対応

## 関連 ADR

- [ADR-003: リポジトリ構成](003-repository-structure.md) - 当初のパッケージ構成
- [ADR-007: Cloud Scheduler実行間隔最適化](007-cloud-scheduler-interval-optimization.md)
- [ADR-012: check-new-video Cloud Function専用サービスアカウントの採用](012-check-new-video-dedicated-service-account.md)
- [ADR-027: PS5 自動アップロード動画のタイトル自動書き換え](027-ps5-auto-title-rename.md)
- [ADR-036: Pub/Sub キューを Firestore キューに置き換える](036-replace-pubsub-with-firestore-queue.md)
