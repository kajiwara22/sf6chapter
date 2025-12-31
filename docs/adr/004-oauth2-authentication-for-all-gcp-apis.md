# 4. ローカルPC処理でOAuth2認証を使用

日付: 2025-12-31
更新: 2025-12-31（適用範囲を明確化）

## ステータス

採用（ローカルPC処理のみ）

## 適用範囲

**このADRは `packages/local/` のローカルPC処理のみに適用される。**

Cloud Functions (`packages/gcp-functions/`) では、Application Default Credentials (ADC) を使用する。

## コンテキスト

ローカルPC上で動作するPython処理では、以下のGoogle Cloud APIを呼び出す必要がある:

- YouTube Data API (チャプター更新)
- Cloud Pub/Sub API (メッセージ受信)
- Vertex AI / Gemini API (キャラクター認識)

当初、環境変数 `GOOGLE_APPLICATION_CREDENTIALS` によるサービスアカウント認証を想定していたが、以下の課題がある:

- サービスアカウントキーの管理が必要
- YouTube Data APIはユーザー権限が必要な操作がある
- 認証方式が統一されていない

## 決定

**すべてのGoogle Cloud API呼び出しで `oauth.py` によるOAuth2認証を使用する。**

### 認証フロー

1. 初回実行時に `oauth.py` の `get_oauth_credentials()` で認証を実行
2. `token.pickle` にトークンを保存（pickle形式）
3. 以降の実行では保存されたトークンを使用（自動リフレッシュ）

### スコープ

```python
SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",  # YouTube Data API
    "https://www.googleapis.com/auth/cloud-platform",     # Pub/Sub, Vertex AI
]
```

### 実装方針

- `oauth.py` の `get_oauth_credentials()` を共通関数として使用
- Pub/Sub、YouTube、Gemini APIすべてで同じ認証情報を利用
- `GOOGLE_APPLICATION_CREDENTIALS` 環境変数は使用しない
- トークンファイルとクライアントシークレットファイルのパスは引数で指定可能
- デフォルトでは `client_secrets.json`（クライアントシークレット）と `token.pickle`（トークン保存）を使用

## 結果

### メリット

- **認証方式の統一**: すべてのAPIで同じ認証フローを使用
- **セキュリティ**: サービスアカウントキーをファイルで管理する必要がない
- **ユーザー権限**: YouTube Data APIで必要なユーザー権限を正しく取得
- **トークン管理**: 自動リフレッシュにより手動での再認証が不要

### デメリット

- **初回認証**: ブラウザでの認証フローが必要
- **トークン有効期限**: 長期間未使用の場合、再認証が必要になる可能性

## Cloud Functionsでの認証

Cloud Functions では OAuth2 を使用**せず**、Application Default Credentials (ADC) を使用する。

### 認証方式

```python
# Cloud Functionsでは自動的にサービスアカウントを使用
from google.cloud import firestore, pubsub_v1

# 環境変数不要、ADCが自動検出
db = firestore.Client(project=PROJECT_ID)
publisher = pubsub_v1.PublisherClient()
```

### サービスアカウント権限

Cloud Functionsのデフォルトサービスアカウント (`{project}@appspot.gserviceaccount.com`) に以下の権限が必要:

- `roles/datastore.user` - Firestore読み書き
- `roles/pubsub.publisher` - Pub/Sub発行

### YouTube API

Cloud Functionsでも**サービスアカウント（ADC）**を使用:

```python
from google.auth import default

credentials, _ = default(scopes=["https://www.googleapis.com/auth/youtube.readonly"])
youtube = build("youtube", "v3", credentials=credentials)
```

**理由**: APIキーは追跡・管理が困難なため、すべての認証をサービスアカウントに統一する。

## 関連

### ローカルPC処理
- `packages/local/src/auth/oauth.py` - OAuth2認証実装
- `packages/local/src/pubsub/subscriber.py` - Pub/Subクライアント
- `packages/local/src/youtube/chapters.py` - YouTube Data APIクライアント
- `packages/local/src/character/recognizer.py` - Gemini APIクライアント

### Cloud Functions
- `packages/gcp-functions/check-new-video/main.py` - ADC使用例
