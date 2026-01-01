# ADR-008: Cloud FunctionsでのOAuth2ユーザー認証実装

- **ステータス**: 採用
- **決定日**: 2026-01-02
- **決定者**: kajiwara22
- **関連ADR**: [ADR-004: OAuth2認証の統一](./004-oauth2-authentication-for-all-gcp-apis.md), [ADR-007: Cloud Schedulerの実行間隔最適化](./007-cloud-scheduler-interval-optimization.md)

## 1. 議論の背景

YouTube API `forMine=True`パラメータを使用して自分の動画のみを取得したい。

### 技術的制約

`forMine=True`はYouTube APIのパラメータで、認証されたユーザー自身の動画のみを取得する。

**YouTube API公式ドキュメントより**:
> `forMine` (boolean) - このパラメータは、適切に承認されたリクエストでのみ使用できます。

### 当初の実装の問題

**Cloud Functions (`packages/gcp-functions/check-new-video/main.py`)** では、サービスアカウント（ADC）を使用していた:

```python
from google.auth import default
credentials, _ = default(scopes=["https://www.googleapis.com/auth/youtube.readonly"])
youtube = build("youtube", "v3", credentials=credentials)
```

**問題点**:
- サービスアカウントには「自分の動画」という概念がない
- `forMine=True`はOAuth2ユーザー認証が必須
- サービスアカウントでは`forMine=True`は使用できない

### ユースケース

- **目的**: 個人のランクマッチ動画分析（反省点の洗い出し効率化）
- **対象**: 自分（kajiwara22）の動画のみ
- **公開範囲**: 他人への公開想定なし（個人用途）
- **ユーザー数**: 単一ユーザー

## 2. 選択肢と結論

### 結論

**選択肢A: Secret Manager + Refresh Token方式**を採用する。

### 検討した選択肢

| ID | 方式 | 概要 |
|----|------|------|
| A | Secret Manager + Refresh Token | ローカルPCで取得したRefresh TokenをSecret Managerに保存 |
| B | OAuth2フロー用エンドポイント追加 | Cloud FunctionsにOAuth2エンドポイントを追加 |
| C | channelIdパラメータ使用 | `forMine=True`を諦め、`channelId`を使用 |

## 3. 各選択肢の比較

### 選択肢A: Secret Manager + Refresh Token（採用）

**アーキテクチャ**:
```
[初回のみ: ローカルPC]
1. OAuth2フローでRefresh Token取得
2. Secret Managerに保存（youtube-refresh-token, youtube-client-id, youtube-client-secret）

[Cloud Function実行時]
1. Secret ManagerからRefresh Token取得
2. google.oauth2.credentials.Credentialsで認証情報構築
3. Access Token自動取得
4. forMine=TrueでYouTube API呼び出し
```

**メリット**:
- ✅ シンプル（単一ユーザー用途に最適）
- ✅ セキュア（Secret Manager暗号化）
- ✅ Cloud Functionsコード内で完結
- ✅ 既存のローカルPC OAuth2実装を再利用可能
- ✅ 保守が容易

**デメリット**:
- ⚠️ 初回セットアップが必要（ローカルでOAuth2フロー実行）
- ⚠️ Refresh Token有効期限管理が必要（6ヶ月未使用で無効化）

**コスト**:
- Secret Manager: 6アクセス/月（$0.03/10,000アクセス） → **$0.001/月（無料枠内）**
- その他変更なし

---

### 選択肢B: OAuth2フロー用エンドポイント追加

**アーキテクチャ**:
```
[初回のみ: ブラウザ]
1. Cloud Function /oauth/authorize → Google認証画面表示
2. Cloud Function /oauth/callback → Refresh Token取得・Firestore保存

[Cloud Function実行時]
1. FirestoreからRefresh Token取得
2. Access Token取得
3. forMine=TrueでYouTube API呼び出し
```

**メリット**:
- ✅ すべてクラウドで完結
- ✅ 複数ユーザー対応可能（将来）

**デメリット**:
- ❌ 実装が複雑（OAuth2エンドポイント2つ追加）
- ❌ 単一ユーザーには過剰設計
- ❌ セキュリティ考慮事項が増加（CSRF対策、state管理等）
- ❌ Redirect URIの管理が必要

**不採用理由**: 単一ユーザー用途に対して実装コストが高すぎる

---

### 選択肢C: channelIdパラメータ使用

**アーキテクチャ**:
```
[Cloud Function実行時]
1. サービスアカウント認証（ADC）
2. channelId指定でYouTube API呼び出し（パブリックデータ）
```

**メリット**:
- ✅ 実装不要（現在のADC認証で動作）
- ✅ シンプル
- ✅ 安定性が高い

**デメリット**:
- ❌ `forMine=True`は使えない
- ❌ 環境変数にchannelIdが必要
- ❌ 非公開動画は取得できない可能性

**不採用理由**: `forMine=True`使用が要件のため不適合

## 4. 実装詳細

### 初回セットアップ（ローカルPC）

詳細は `packages/gcp-functions/check-new-video/SETUP_OAUTH2.md` を参照。

**手順概要**:
1. ローカルPCでOAuth2フローを実行
2. Refresh Token、Client ID、Client Secretを抽出
3. Secret Managerに3つのシークレットを作成
4. Cloud Functionsサービスアカウントに権限付与

### Cloud Function実装

**main.py追加実装**:

```python
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials

def get_secret(secret_name: str) -> str:
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def get_oauth_credentials() -> Credentials:
    """OAuth2認証情報を取得（Secret Managerから）"""
    client_id = get_secret("youtube-client-id")
    client_secret = get_secret("youtube-client-secret")
    refresh_token = get_secret("youtube-refresh-token")

    credentials = Credentials(
        token=None,  # Access tokenは自動取得される
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.force-ssl"]
    )
    return credentials

# YouTube APIクライアント構築
credentials = get_oauth_credentials()
youtube = build("youtube", "v3", credentials=credentials)
```

**requirements.txt追加**:
```
google-cloud-secret-manager==2.16.*
```

### 必要な権限

**Secret Managerアクセス**:
```bash
for SECRET_NAME in youtube-refresh-token youtube-client-id youtube-client-secret; do
    gcloud secrets add-iam-policy-binding $SECRET_NAME \
        --member="serviceAccount:${GCP_PROJECT_ID}@appspot.gserviceaccount.com" \
        --role="roles/secretmanager.secretAccessor" \
        --project=$GCP_PROJECT_ID
done
```

## 5. 帰結

### 5.1 メリット

| 観点 | 効果 |
|------|------|
| **セキュリティ** | Secret Managerで暗号化保存 |
| **シンプルさ** | 単一ユーザー用途に最適化 |
| **コスト** | 無料枠内で運用可能（$0.001/月） |
| **保守性** | 既存OAuth2実装を再利用 |
| **機能性** | `forMine=True`使用可能 |

### 5.2 トレードオフ

| デメリット | 対策 |
|-----------|------|
| 初回セットアップが必要 | SETUP_OAUTH2.mdで詳細手順を提供 |
| Refresh Token有効期限管理 | 2時間毎の実行で6ヶ月未使用は回避可能 |
| Secret Manager依存 | 無料枠内、GCPマネージドサービスで信頼性高い |

### 5.3 セキュリティ考慮事項

1. **Secret Manager**:
   - 暗号化: Google管理の暗号化キー
   - アクセス制御: Cloud Functionsサービスアカウントのみ
   - 監査ログ: Cloud Logging で全アクセスを記録

2. **Refresh Token**:
   - 有効期限: 最後の使用から6ヶ月（通常は問題なし）
   - 無効化条件: パスワード変更、アクセス取り消し
   - ローテーション: 定期的な再認証を推奨

3. **機密ファイル**:
   - `.gitignore`に追加: `refresh_token.txt`, `token.pickle`
   - セットアップ完了後は削除推奨

### 5.4 監視指標

| 指標 | 目標 | 確認方法 |
|------|------|---------|
| OAuth2認証成功率 | 100% | Cloud Logsで`OAuth2 credentials initialized successfully` |
| Secret Manager取得成功率 | 100% | Cloud Logsで`Successfully retrieved secret` |
| Refresh Token有効性 | 常に有効 | エラーログ監視、6ヶ月に1回確認 |

## 6. 将来の見直し条件

以下の場合、実装方式の見直しを検討する:

### 6.1 複数ユーザー対応

- **条件**: 他のユーザーも同様の機能を使いたい場合
- **対応**: 選択肢Bへの移行検討（OAuth2エンドポイント追加）

### 6.2 Refresh Token管理の負担増加

- **条件**: Refresh Tokenの無効化が頻繁に発生
- **対応**: 自動再認証フローの実装検討

### 6.3 Secret Managerコストの増加

- **条件**: アクセス頻度の大幅増加により課金が発生
- **対応**: キャッシュ戦略の見直し、または代替ストレージ検討

### 6.4 YouTube API認証仕様の変更

- **条件**: GoogleがOAuth2フローや認証要件を変更
- **対応**: 新仕様への適合、実装の見直し

## 7. 関連情報

### ADRとの関連

- **ADR-004**: ローカルPC処理でOAuth2を使用（同様のアプローチ）
- **ADR-007**: Cloud Schedulerの実行間隔（2時間毎でRefresh Token維持）

### ドキュメント

- `packages/gcp-functions/check-new-video/SETUP_OAUTH2.md` - セットアップ手順
- `packages/gcp-functions/check-new-video/README.md` - デプロイ手順

### 参考資料

- [YouTube Data API - OAuth2 Authentication](https://developers.google.com/youtube/v3/guides/authentication)
- [Google Cloud Secret Manager Documentation](https://cloud.google.com/secret-manager/docs)
- [OAuth 2.0 Best Practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices)

---

**変更履歴**:
- 2026-01-02: 初版作成、Secret Manager + Refresh Token方式を採用
