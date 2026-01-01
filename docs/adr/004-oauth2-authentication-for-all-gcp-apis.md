# ADR-004: OAuth2認証の統一

日付: 2025-12-31
更新: 2026-01-02（Cloud Functionsへの適用拡大）

## ステータス

採用

## 適用範囲

**このADRは以下の両方に適用される**:

1. **ローカルPC処理** (`packages/local/`): ユーザー認証が必要なすべてのAPI
2. **Cloud Functions** (`packages/gcp-functions/check-new-video/`): YouTube API `forMine=True`使用のため

**適用方法の違い**:
- **ローカルPC**: `token.pickle`にトークンを保存
- **Cloud Functions**: Secret ManagerにRefresh Tokenを保存

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

### 2026-01-02更新: YouTube APIでOAuth2ユーザー認証を使用

**背景**: YouTube API `forMine=True`パラメータはOAuth2ユーザー認証が必須であり、サービスアカウント（ADC）では使用できない。

詳細は [ADR-008: Cloud FunctionsでのOAuth2ユーザー認証実装](./008-oauth2-user-authentication-in-cloud-functions.md) を参照。

### Firestore/Pub/SubではADCを使用

```python
# Cloud Functionsでは自動的にサービスアカウントを使用
from google.cloud import firestore, pubsub_v1

# 環境変数不要、ADCが自動検出
db = firestore.Client(project=PROJECT_ID)
publisher = pubsub_v1.PublisherClient()
```

### YouTube APIではOAuth2を使用

```python
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials

# Secret ManagerからRefresh Tokenを取得
client_id = get_secret("youtube-client-id")
client_secret = get_secret("youtube-client-secret")
refresh_token = get_secret("youtube-refresh-token")

# OAuth2認証情報を構築
credentials = Credentials(
    token=None,
    refresh_token=refresh_token,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=client_id,
    client_secret=client_secret,
    scopes=["https://www.googleapis.com/auth/youtube.force-ssl"]
)

youtube = build("youtube", "v3", credentials=credentials)
```

### サービスアカウント権限

Cloud Functionsのデフォルトサービスアカウント (`{project}@appspot.gserviceaccount.com`) に以下の権限が必要:

- `roles/datastore.user` - Firestore読み書き
- `roles/pubsub.publisher` - Pub/Sub発行
- `roles/secretmanager.secretAccessor` - Secret Manager読み取り（OAuth2認証情報取得用）

## 関連

### ローカルPC処理
- `packages/local/src/auth/oauth.py` - OAuth2認証実装
- `packages/local/src/pubsub/subscriber.py` - Pub/Subクライアント
- `packages/local/src/youtube/chapters.py` - YouTube Data APIクライアント
- `packages/local/src/character/recognizer.py` - Gemini APIクライアント

### Cloud Functions
- `packages/gcp-functions/check-new-video/main.py` - ADC使用例
