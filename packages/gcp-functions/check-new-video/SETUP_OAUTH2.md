# OAuth2セットアップ手順

Cloud FunctionsでYouTube API `forMine=True`を使用するための初回セットアップ手順。

## 前提条件

- gcloud CLIがインストールされていること
- `packages/local/`のOAuth2実装が動作していること
- Google Cloud Consoleでプロジェクトが作成されていること

## 手順

### 1. ローカルPCでRefresh Tokenを取得

#### 1.1 OAuth2認証フローを実行

```bash
cd packages/local

# OAuth2認証を実行（ブラウザが開きます）
uv run python -c "
from src.auth.oauth import get_oauth_credentials
credentials = get_oauth_credentials()
print('OAuth2認証完了')
print(f'Refresh Token: {credentials.refresh_token}')
"
```

これにより `token.pickle` が作成されます。

#### 1.2 Refresh Tokenを抽出

```bash
# token.pickleからRefresh Tokenを抽出してファイルに保存
uv run python -c "
import pickle
with open('token.pickle', 'rb') as f:
    credentials = pickle.load(f)
    with open('refresh_token.txt', 'w') as out:
        out.write(credentials.refresh_token)
print('Refresh Tokenをrefresh_token.txtに保存しました')
"
```

**重要**: `refresh_token.txt`は機密情報です。取り扱いに注意してください。

### 2. Secret Managerにシークレットを作成

#### 2.1 YouTube Refresh Tokenを保存

```bash
# 環境変数設定
export GCP_PROJECT_ID="your-project-id"

# Secret Managerにシークレット作成
gcloud secrets create youtube-refresh-token \
    --data-file=refresh_token.txt \
    --replication-policy="automatic" \
    --project=$GCP_PROJECT_ID

# 作成確認
gcloud secrets versions list youtube-refresh-token \
    --project=$GCP_PROJECT_ID
```

#### 2.2 OAuth2 Client IDとClient Secretを保存

```bash
# client_secrets.jsonから抽出
CLIENT_ID=$(cat client_secrets.json | jq -r '.installed.client_id')
CLIENT_SECRET=$(cat client_secrets.json | jq -r '.installed.client_secret')

# Secret Managerに保存
echo -n "$CLIENT_ID" | gcloud secrets create youtube-client-id \
    --data-file=- \
    --replication-policy="automatic" \
    --project=$GCP_PROJECT_ID

echo -n "$CLIENT_SECRET" | gcloud secrets create youtube-client-secret \
    --data-file=- \
    --replication-policy="automatic" \
    --project=$GCP_PROJECT_ID
```

### 3. Cloud Functionに権限を付与

Cloud Functionsの専用サービスアカウントにSecret Managerへのアクセス権限を付与します。

```bash
# サービスアカウント名（ADR-012で定義）
SERVICE_ACCOUNT_NAME="check-new-video-sa"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

# サービスアカウント作成（初回のみ）
gcloud iam service-accounts create $SERVICE_ACCOUNT_NAME \
    --display-name="Service account for check-new-video Cloud Function" \
    --project=$GCP_PROJECT_ID

# 各シークレットへのアクセス権限を付与
for SECRET_NAME in youtube-refresh-token youtube-client-id youtube-client-secret; do
    gcloud secrets add-iam-policy-binding $SECRET_NAME \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/secretmanager.secretAccessor" \
        --project=$GCP_PROJECT_ID
    echo "✓ ${SECRET_NAME}へのアクセス権限を付与しました"
done
```

**Note**: サービスアカウント `check-new-video-sa` の採用理由は [ADR-012](../../../docs/adr/012-check-new-video-dedicated-service-account.md) を参照してください。

### 4. 動作確認

#### 4.1 Secret Managerからの読み取りテスト

```bash
# Cloud Functionsと同じサービスアカウントを使用してテスト
gcloud secrets versions access latest \
    --secret="youtube-refresh-token" \
    --project=$GCP_PROJECT_ID
```

期待される出力: Refresh Tokenの文字列が表示される

#### 4.2 Cloud Functionデプロイ

```bash
cd packages/gcp-functions/check-new-video
./deploy.sh
```

#### 4.3 手動トリガーでテスト

```bash
# Function URLを取得
FUNCTION_URL=$(gcloud functions describe check-new-video \
    --region=asia-northeast1 \
    --project=$GCP_PROJECT_ID \
    --format="value(serviceConfig.uri)")

# HTTPリクエスト送信
curl $FUNCTION_URL

# ログ確認
gcloud functions logs read check-new-video \
    --region=asia-northeast1 \
    --project=$GCP_PROJECT_ID \
    --limit=50
```

期待される出力:
- `OAuth2認証成功` のログ
- `Found X videos within 150 minutes` のログ
- エラーがないこと

### 5. クリーンアップ（オプション）

セットアップ完了後、ローカルの機密ファイルを削除します。

```bash
cd packages/local

# 機密ファイルを削除
rm -f refresh_token.txt
echo "✓ refresh_token.txtを削除しました"

# token.pickleは残す（ローカル処理で使用）
# client_secrets.jsonは残す（将来の再認証で必要）
```

## トラブルシューティング

### エラー: "Refresh token not found in Secret Manager"

**原因**: Secret Managerにシークレットが作成されていない

**対処**:
```bash
# シークレット一覧を確認
gcloud secrets list --project=$GCP_PROJECT_ID

# youtube-refresh-token, youtube-client-id, youtube-client-secretがあることを確認
```

### エラー: "Permission denied accessing secret"

**原因**: Cloud Functionsのサービスアカウントに権限がない

**対処**:
```bash
# IAMポリシーを確認
gcloud secrets get-iam-policy youtube-refresh-token \
    --project=$GCP_PROJECT_ID

# サービスアカウントがroles/secretmanager.secretAccessorを持っているか確認
```

### エラー: "Invalid refresh token"

**原因**: Refresh Tokenが無効または期限切れ

**対処**:
1. ローカルPCで再度OAuth2フローを実行
2. 新しいRefresh TokenをSecret Managerに上書き保存

```bash
# 新しいRefresh Tokenでシークレットを更新
gcloud secrets versions add youtube-refresh-token \
    --data-file=refresh_token.txt \
    --project=$GCP_PROJECT_ID
```

### Refresh Tokenの有効期限

Googleの仕様により、以下の場合にRefresh Tokenが無効化されます：

1. **6ヶ月間未使用**: 最後の使用から6ヶ月経過
2. **ユーザーがアクセス取り消し**: Google アカウント設定でアクセスを取り消した場合
3. **パスワード変更**: アカウントのパスワードを変更した場合

**対策**:
- Cloud Schedulerで2時間毎に実行しているため、通常は問題なし
- エラーが発生した場合は、本手順を再実行してRefresh Tokenを更新

## セキュリティ上の注意

1. **機密ファイルの管理**
   - `refresh_token.txt`は絶対にGitにコミットしない
   - `.gitignore`に追加されていることを確認
   - セットアップ完了後は削除推奨

2. **Secret Managerのアクセス制御**
   - Cloud Functionsのサービスアカウントのみにアクセスを許可
   - プロジェクトの他のユーザーには最小権限を付与

3. **Refresh Tokenのローテーション**
   - 定期的に再認証してRefresh Tokenを更新することを推奨
   - 不正アクセスの疑いがある場合は即座に再生成

## 参考資料

- [Google OAuth2 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Secret Manager Documentation](https://cloud.google.com/secret-manager/docs)
- [ADR-008: Cloud FunctionsでのOAuth2ユーザー認証](../../../docs/adr/008-oauth2-user-authentication-in-cloud-functions.md)
