# Cloud Function: check-new-video

Cloud Schedulerから15分毎に実行され、対象チャンネルの新着動画をPub/Subに発行するCloud Function。

## 機能

1. **新着動画チェック**: YouTube APIで対象チャンネルの新着動画を取得
2. **重複防止**: Firestoreで処理済み動画を管理し、重複処理を防止
3. **Pub/Sub発行**: 未処理動画のみをPub/Subトピックに発行
4. **処理履歴**: Firestoreに処理履歴を記録

## アーキテクチャ

```
Cloud Scheduler (15分毎)
    ↓
check-new-video (Cloud Function)
    ↓ YouTube API
    ├─ 新着動画取得
    ↓ Firestore
    ├─ 重複チェック
    ├─ 処理履歴記録
    ↓ Pub/Sub
    └─ メッセージ発行
```

## 環境変数

| 変数名 | 必須 | 説明 | 例 |
|--------|------|------|-----|
| `GCP_PROJECT_ID` | Yes | GCPプロジェクトID | `sf6-chapter-12345` |
| `TARGET_CHANNEL_IDS` | Yes | 監視対象のチャンネルID（カンマ区切り） | `UCxxx,UCyyy` |
| `PUBSUB_TOPIC` | No | Pub/Subトピック名 | `sf6-video-process` (デフォルト) |

**Note**: YouTube APIもサービスアカウント（ADC）を使用するため、APIキーは不要です。

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

### 認証と権限設定

#### Application Default Credentials (ADC)

Cloud Functionsは自動的にサービスアカウントを使用します（OAuth2は不要）。

デフォルトのサービスアカウント: `{PROJECT_ID}@appspot.gserviceaccount.com`

#### 必要な権限

以下の権限をサービスアカウントに付与:

```bash
# Firestore読み書き権限
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
    --member="serviceAccount:${GCP_PROJECT_ID}@appspot.gserviceaccount.com" \
    --role="roles/datastore.user"

# Pub/Sub発行権限
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
    --member="serviceAccount:${GCP_PROJECT_ID}@appspot.gserviceaccount.com" \
    --role="roles/pubsub.publisher"

# YouTube Data API読み取り権限（不要な場合もあるが、明示的に付与推奨）
# Note: YouTube APIはパブリックデータの読み取りのみなので、通常は追加権限不要
```

### 環境変数設定

```bash
export GCP_PROJECT_ID="your-project-id"
export TARGET_CHANNEL_IDS="UCxxx,UCyyy,UCzzz"
```

### デプロイ実行

```bash
./deploy.sh
```

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
export GCP_PROJECT_ID="your-project-id"
export TARGET_CHANNEL_IDS="UCxxx,UCyyy"
```

### デプロイ後のテスト

```bash
# Function URLを取得
gcloud functions describe check-new-video \
    --region=asia-northeast1 \
    --project=$GCP_PROJECT_ID \
    --format="value(serviceConfig.uri)"

# HTTPリクエスト送信
curl <FUNCTION_URL>
```

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

```bash
# Schedulerジョブ作成
gcloud scheduler jobs create http check-new-video-schedule \
    --location=asia-northeast1 \
    --schedule="*/15 * * * *" \
    --uri="<FUNCTION_URL>" \
    --http-method=GET \
    --project=$GCP_PROJECT_ID
```

## モニタリング

### ログ確認

```bash
gcloud functions logs read check-new-video \
    --region=asia-northeast1 \
    --project=$GCP_PROJECT_ID \
    --limit=50
```

### Firestoreデータ確認

```bash
# Firebase Consoleで確認
# https://console.firebase.google.com/project/<PROJECT_ID>/firestore
```

## トラブルシューティング

### エラー: "Missing GCP_PROJECT_ID"

環境変数が設定されていません。デプロイ時に`--set-env-vars`で設定してください。

### エラー: "YouTube API error"

- YouTube Data API v3が有効化されているか確認
- APIキーが正しいか確認
- API利用制限（10,000 units/日）に達していないか確認

### 重複したメッセージが発行される

- Firestoreの読み取り/書き込みに失敗している可能性
- ログでFirestoreエラーを確認

## コスト見積もり

**無料枠内での運用想定**:

- Cloud Functions: 200万invocations/月（15分毎 = 2,880回/月）
- Firestore: 50,000 reads/日, 20,000 writes/日（実使用: <1,000回/日）
- Pub/Sub: 10 GiB/月（メッセージサイズ: 数百バイト程度）

→ **すべて無料枠内で運用可能**
