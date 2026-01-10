# Cloud Function: check-new-video

Cloud Schedulerから2時間毎に実行され、自分の新着動画をPub/Subに発行するCloud Function。

## 機能

1. **新着動画チェック**: YouTube APIで自分の新着動画を取得（`forMine=True`）
2. **日時フィルタ**: 公開日時でフィルタリング（2.5時間以内の動画のみ）
3. **重複防止**: Firestoreで処理済み動画を管理し、重複処理を防止
4. **Pub/Sub発行**: 未処理動画のみをPub/Subトピックに発行
5. **処理履歴**: Firestoreに処理履歴を記録

## 設計根拠

詳細は [ADR-007: Cloud Schedulerの実行間隔最適化](../../../docs/adr/007-cloud-scheduler-interval-optimization.md) を参照。

- **配信頻度**: 1日1回〜数回（30分〜1時間/本）
- **実行間隔**: 2時間（1日12回実行）
- **API効率**: YouTube API quota 75%削減（1,200 units/日、無料枠の12%）
- **信頼性**: 2.5時間フィルタで30分のバッファを確保

## アーキテクチャ

```
Cloud Scheduler (2時間毎)
    ↓
check-new-video (Cloud Function)
    ↓ YouTube API (forMine=True)
    ├─ 自分の動画取得（最大5件）
    ├─ 日時フィルタ（2.5時間以内）
    ↓ Firestore
    ├─ 重複チェック
    ├─ 処理履歴記録
    ↓ Pub/Sub
    └─ メッセージ発行
```

## 環境変数

| 変数名 | 必須 | 説明 | デフォルト値 |
|--------|------|------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Yes | GCPプロジェクトID | - |
| `PUBSUB_TOPIC` | No | Pub/Subトピック名 | `sf6-video-process` |

**Note**:
- `forMine=True`を使用するため、`TARGET_CHANNEL_IDS`は不要
- YouTube APIはOAuth2ユーザー認証を使用（詳細は [SETUP_OAUTH2.md](./SETUP_OAUTH2.md)）

## デプロイ

### 前提条件

- gcloud CLIがインストールされていること
- GCPプロジェクトが作成されていること
- 以下のAPIが有効化されていること:
  - Cloud Functions API
  - Cloud Build API
  - Pub/Sub API
  - Firestore API
  - YouTube Data API v3
  - Secret Manager API
- **OAuth2認証のセットアップが完了していること**（[SETUP_OAUTH2.md](./SETUP_OAUTH2.md)参照）

### Firestoreセットアップ

#### 1. Firestoreデータベース作成

```bash
# Firestore Native modeでデータベース作成
gcloud firestore databases create \
    --location=asia-northeast1 \
    --project=$GOOGLE_CLOUD_PROJECT
```

**Note**:
- **モード**: Native mode（リアルタイム同期とより柔軟なクエリをサポート）
- **リージョン**: `asia-northeast1`（Cloud Functionと同一リージョン推奨）
- ⚠️ 一度作成したデータベースのリージョンは変更不可

#### 2. セキュリティルール設定

Firestore Console（`https://console.firebase.google.com/project/<PROJECT_ID>/firestore/rules`）で以下のルールを設定:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /processed_videos/{videoId} {
      // サービスアカウントからのアクセスのみ許可
      allow read, write: if request.auth != null;
    }
  }
}
```

#### 3. コレクション初期化

コレクション `processed_videos` は初回実行時に自動作成されます。手動作成は不要です。

#### 4. インデックス確認

通常、単純なクエリ（ドキュメントID検索）のみ使用するため、複合インデックスは不要です。

Cloud Functionの初回実行後、ログで複合インデックスの作成要求が表示された場合は、表示されたURLから自動作成してください。

### 認証と権限設定

**重要なドキュメント**:
- **[SETUP_OAUTH2.md](./SETUP_OAUTH2.md)**: YouTube API用OAuth2認証のセットアップ
- **[SETUP_SECURITY.md](./SETUP_SECURITY.md)**: Cloud Function OIDC認証のセットアップ（必読）

#### OAuth2ユーザー認証（YouTube API用）

**重要**: `forMine=True`を使用するため、YouTube APIはOAuth2ユーザー認証が必須です。

詳細な手順は [SETUP_OAUTH2.md](./SETUP_OAUTH2.md) を参照してください。

**概要**:
1. ローカルPCでOAuth2フローを実行しRefresh Token取得
2. Secret ManagerにRefresh Token、Client ID、Client Secretを保存
3. Cloud FunctionがSecret Managerから認証情報を取得

#### サービスアカウント権限

このCloud Functionでは2つのサービスアカウントを使用します：

##### 1. Cloud Function実行用サービスアカウント（ADR-012）

**サービスアカウント**: `check-new-video-sa@{PROJECT_ID}.iam.gserviceaccount.com`

Cloud Functionが各種GCPサービスにアクセスするための権限を持ちます。

```bash
# サービスアカウント名
SERVICE_ACCOUNT_NAME="check-new-video-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"

# サービスアカウント作成（初回のみ）
gcloud iam service-accounts create $SERVICE_ACCOUNT_NAME \
    --display-name="Service account for check-new-video Cloud Function" \
    --project=$GOOGLE_CLOUD_PROJECT

# Firestore読み書き権限
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/datastore.user"

# Pub/Sub発行権限
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/pubsub.publisher"

# Secret Manager読み取り権限（OAuth2認証情報取得用）
for SECRET_NAME in youtube-refresh-token youtube-client-id youtube-client-secret; do
    gcloud secrets add-iam-policy-binding $SECRET_NAME \
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
        --role="roles/secretmanager.secretAccessor" \
        --project=$GOOGLE_CLOUD_PROJECT
done
```

##### 2. Cloud Scheduler用サービスアカウント（ADR-014）

**サービスアカウント**: `cloud-scheduler-invoker@{PROJECT_ID}.iam.gserviceaccount.com`

Cloud SchedulerがCloud Functionを呼び出すための認証に使用します。

```bash
# Cloud Scheduler用サービスアカウント作成
SCHEDULER_SA_NAME="cloud-scheduler-invoker"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA_NAME}@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"

gcloud iam service-accounts create $SCHEDULER_SA_NAME \
    --display-name="Cloud Scheduler invoker for Cloud Functions" \
    --project=$GOOGLE_CLOUD_PROJECT
```

**セキュリティ上の利点**:
- 最小権限の原則に基づき、必要な権限のみを付与
- 実行権限と呼び出し権限を分離
- Cloud Function専用アカウントで責任範囲が明確
- IAM監査ログでの追跡が容易

### 環境変数設定

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
# TARGET_CHANNEL_IDSは不要（forMine=Trueを使用）
```

### デプロイ実行

```bash
./deploy.sh
```

### デプロイ後の権限設定

Cloud Functionをデプロイした後、Cloud Scheduler用サービスアカウントに呼び出し権限を付与します：

```bash
# Cloud Functionの呼び出し権限を付与
gcloud functions add-invoker-policy-binding check-new-video \
    --region=asia-northeast1 \
    --member="serviceAccount:cloud-scheduler-invoker@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com" \
    --project=$GOOGLE_CLOUD_PROJECT
```

**重要**: この権限設定により、Cloud Schedulerからのみ実行可能になります（[ADR-014](../../../docs/adr/014-cloud-function-oidc-authentication.md)参照）。

## テスト

### ユニットテスト

このプロジェクトは`uv`を使用してテスト環境を管理します。

#### 環境セットアップ（初回のみ）

```bash
# 開発用依存関係を含む環境をセットアップ
uv sync --all-extras
```

#### テスト実行

```bash
# すべてのテストを実行
uv run pytest

# 詳細出力
uv run pytest -v

# カバレッジレポート付き
uv run pytest --cov=main --cov-report=term-missing

# HTMLカバレッジレポート生成
uv run pytest --cov=main --cov-report=html
# ブラウザで htmlcov/index.html を開いて確認

# 特定のテストクラスのみ実行
uv run pytest test_main.py::TestGetRecentVideos -v

# 特定のテスト関数のみ実行
uv run pytest test_main.py::TestGetRecentVideos::test_get_recent_videos_success -v
```

#### テストカバレッジ

現在のテストカバレッジ: **78%**

- ✅ 10/10テスト成功
- ✅ 主要機能すべてカバー
- ⚠️ エラーハンドリングの一部ブランチは未カバー（正常）

### ローカル動作確認

Functions Frameworkでローカル起動して動作確認:

```bash
# ローカルで起動（uv環境を使用）
uv run functions-framework --target=check_new_video --debug

# 別ターミナルからHTTPリクエスト
curl http://localhost:8080
```

**Note**: ローカル実行時は環境変数の設定が必要です:

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
# TARGET_CHANNEL_IDSは不要（forMine=Trueを使用）
```

### デプロイ後のテスト

#### 1. Function URLの取得

```bash
# Function URLを取得（Gen2関数用）
FUNCTION_URL=$(gcloud functions describe check-new-video \
    --region=asia-northeast1 \
    --gen2 \
    --project=$GOOGLE_CLOUD_PROJECT \
    --format="value(serviceConfig.uri)")

echo "Function URL: $FUNCTION_URL"
```

**Note**: Gen2関数では`--gen2`フラグが必要です。URLは`https://check-new-video-xxxxx-an.a.run.app`の形式になります。

#### 2. 手動実行テスト

**認証付きリクエスト**（OIDC認証が有効なため）:

```bash
# 認証トークンを取得してリクエスト送信
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $FUNCTION_URL

# 期待されるレスポンス（新着動画がない場合）
# {"stats":{"errors":0,"filteredVideos":0,"foundVideos":0,"publishedVideos":0,"skippedVideos":0},"status":"success"}
```

**認証エラーの場合**:
```json
{
  "error": {
    "code": 403,
    "message": "Forbidden",
    "status": "PERMISSION_DENIED"
  }
}
```

**正常なレスポンス**:
- `status: "success"`: 関数が正常に実行された
- `foundVideos: 0`: 2.5時間以内に新着動画がない（正常）
- `publishedVideos: 0`: Pub/Subに発行した動画数

**Note**: 認証なしでアクセスした場合、403 Forbiddenエラーが返されます（セキュリティ強化、[ADR-014](../../../docs/adr/014-cloud-function-oidc-authentication.md)参照）。

## Firestoreデータ構造

### コレクション: `processed_videos`

各ドキュメントのIDは`videoId`。

```json
{
  "videoId": "xxxxxxxxxxx",
  "title": "動画タイトル",
  "channelId": "UCxxx",
  "channelTitle": "チャンネル名",
  "publishedAt": "2024-12-31T10:00:00Z",
  "status": "queued",
  "queuedAt": "2024-12-31T10:00:00Z",
  "updatedAt": "2024-12-31T10:00:00Z"
}
```

**ステータス**:
- `queued`: Pub/Subキューに追加済み
- `processing`: ローカル処理中
- `completed`: 処理完了
- `failed`: 処理失敗

## Cloud Scheduler設定

### 1. Function URLの取得

Cloud Schedulerの設定前に、Function URLを取得します：

```bash
# Function URLを取得して環境変数に保存
FUNCTION_URL=$(gcloud functions describe check-new-video \
    --region=asia-northeast1 \
    --gen2 \
    --project=$GOOGLE_CLOUD_PROJECT \
    --format="value(serviceConfig.uri)")

echo "Function URL: $FUNCTION_URL"
```

### 2. Schedulerジョブの作成

**OIDC認証を使用してCloud Functionを呼び出します**（[ADR-014](../../../docs/adr/014-cloud-function-oidc-authentication.md)参照）:

```bash
# Schedulerジョブ作成（2時間毎、偶数時に実行: 0時、2時、4時...）
gcloud scheduler jobs create http check-new-video-schedule \
    --location=asia-northeast1 \
    --schedule="0 */2 * * *" \
    --uri="$FUNCTION_URL" \
    --http-method=GET \
    --time-zone="Asia/Tokyo" \
    --oidc-service-account-email="cloud-scheduler-invoker@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com" \
    --oidc-token-audience="$FUNCTION_URL" \
    --project=$GOOGLE_CLOUD_PROJECT
```

**重要なパラメータ**:
- `--oidc-service-account-email`: Cloud Scheduler用サービスアカウント
- `--oidc-token-audience`: トークンの検証対象（Function URL）
- OIDC認証により、Cloud Schedulerからのリクエストのみ許可されます

**Note**:
- `$FUNCTION_URL`は上記で取得した値を使用
- `--gen2`フラグでFunction URLを取得することが重要（Gen2関数の場合）

### 3. Schedulerジョブの確認

```bash
# ジョブの詳細確認
gcloud scheduler jobs describe check-new-video-schedule \
    --location=asia-northeast1 \
    --project=$GOOGLE_CLOUD_PROJECT

# 手動実行テスト
gcloud scheduler jobs run check-new-video-schedule \
    --location=asia-northeast1 \
    --project=$GOOGLE_CLOUD_PROJECT
```

**設計根拠**: [ADR-007](../../../docs/adr/007-cloud-scheduler-interval-optimization.md)参照
- 配信頻度（1日1-数回）に最適化
- YouTube API quota 75%削減（1,200 units/日）

## モニタリング

### ログ確認

```bash
gcloud functions logs read check-new-video \
    --region=asia-northeast1 \
    --project=$GOOGLE_CLOUD_PROJECT \
    --limit=50
```

### Firestoreデータ確認

```bash
# Firebase Consoleで確認
# https://console.firebase.google.com/project/<PROJECT_ID>/firestore
```

## トラブルシューティング

### エラー: "Missing GOOGLE_CLOUD_PROJECT"

環境変数が設定されていません。デプロイ時に`--set-env-vars`で設定してください。

### エラー: "YouTube API error"

- YouTube Data API v3が有効化されているか確認
- サービスアカウントに適切な権限があるか確認
- API利用制限（10,000 units/日）に達していないか確認
  - 2時間間隔実行: 1,200 units/日（無料枠の12%）

### 重複したメッセージが発行される

- Firestoreの読み取り/書き込みに失敗している可能性
- ログでFirestoreエラーを確認

## コスト見積もり

**無料枠内での運用想定**:

- **Cloud Functions**: 200万invocations/月（2時間毎 = 360回/月） → **無料枠の0.018%**
- **YouTube API**: 10,000 units/日（実使用: 1,200 units/日） → **無料枠の12%**
- **Firestore**: 50,000 reads/日, 20,000 writes/日（実使用: <100回/日） → **無料枠の0.2%**
- **Pub/Sub**: 10 GiB/月（メッセージサイズ: 数百バイト程度） → **無料枠の0.001%**

→ **すべて無料枠内で運用可能**

### 従来構成（15分間隔）との比較

| 項目 | 15分間隔 | 2時間間隔（現在） | 削減率 |
|------|---------|-----------------|--------|
| Cloud Functions実行回数 | 2,880回/月 | 360回/月 | **87.5%削減** |
| YouTube API quota | 4,800 units/日 | 1,200 units/日 | **75%削減** |
| Firestore read/write | <800回/日 | <100回/日 | **87.5%削減** |

詳細は [ADR-007](../../../docs/adr/007-cloud-scheduler-interval-optimization.md) を参照。
