# Cloud Function セキュリティ設定ガイド

OIDC認証によるCloud Function保護の完全セットアップ手順（[ADR-014](../../../docs/adr/014-cloud-function-oidc-authentication.md)参照）

## 概要

Cloud SchedulerからCloud Functionを安全に呼び出すため、OIDC（OpenID Connect）認証を使用します。

### セキュリティ効果

- ✅ Cloud Schedulerからのリクエストのみ許可
- ✅ 外部からの不正アクセス完全防止
- ✅ YouTube API quotaの保護
- ✅ 無用な課金リスクの排除
- ✅ 追加コストなし（無料機能）

## セットアップ手順

### 前提条件

以下が既に完了していることを確認してください：

- [x] GCPプロジェクトの作成
- [x] Cloud Functions APIの有効化
- [x] Cloud Scheduler APIの有効化
- [x] `check-new-video-sa`サービスアカウントの作成（[README.md](./README.md#認証と権限設定)参照）

### 1. Cloud Scheduler用サービスアカウント作成

```bash
# プロジェクトID設定
export GCP_PROJECT_ID="your-project-id"

# サービスアカウント名
SCHEDULER_SA_NAME="cloud-scheduler-invoker"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

# サービスアカウント作成
gcloud iam service-accounts create $SCHEDULER_SA_NAME \
    --display-name="Cloud Scheduler invoker for Cloud Functions" \
    --project=$GCP_PROJECT_ID

# 作成確認
gcloud iam service-accounts describe $SCHEDULER_SA_EMAIL \
    --project=$GCP_PROJECT_ID
```

**期待される出力**:
```
email: cloud-scheduler-invoker@{PROJECT_ID}.iam.gserviceaccount.com
name: projects/{PROJECT_ID}/serviceAccounts/cloud-scheduler-invoker@{PROJECT_ID}.iam.gserviceaccount.com
...
```

### 2. Cloud Functionのデプロイ（認証必須化）

```bash
# デプロイスクリプトを実行（--no-allow-unauthenticatedが設定されている）
cd packages/gcp-functions/check-new-video
./deploy.sh
```

**重要**: `deploy.sh`では`--no-allow-unauthenticated`が設定されているため、認証なしのアクセスは拒否されます。

### 3. Cloud Function呼び出し権限の付与

デプロイ完了後、Cloud Scheduler用サービスアカウントにCloud Function呼び出し権限を付与します：

```bash
# Cloud Functionの呼び出し権限を付与
gcloud functions add-invoker-policy-binding check-new-video \
    --region=asia-northeast1 \
    --member="serviceAccount:${SCHEDULER_SA_EMAIL}" \
    --project=$GCP_PROJECT_ID

# 権限確認
gcloud functions get-iam-policy check-new-video \
    --region=asia-northeast1 \
    --project=$GCP_PROJECT_ID
```

**期待される出力**:
```yaml
bindings:
- members:
  - serviceAccount:cloud-scheduler-invoker@{PROJECT_ID}.iam.gserviceaccount.com
  role: roles/cloudfunctions.invoker
```

### 4. Function URL取得

Cloud Schedulerの設定に必要なFunction URLを取得します：

```bash
# Function URLを取得して環境変数に保存
FUNCTION_URL=$(gcloud functions describe check-new-video \
    --region=asia-northeast1 \
    --gen2 \
    --project=$GCP_PROJECT_ID \
    --format="value(serviceConfig.uri)")

echo "Function URL: $FUNCTION_URL"
```

**期待される出力**:
```
Function URL: https://check-new-video-xxxxx-an.a.run.app
```

### 5. Cloud Schedulerジョブ作成（OIDC認証付き）

```bash
# Cloud Schedulerジョブ作成（OIDC認証を使用）
gcloud scheduler jobs create http check-new-video-schedule \
    --location=asia-northeast1 \
    --schedule="0 */2 * * *" \
    --uri="$FUNCTION_URL" \
    --http-method=GET \
    --time-zone="Asia/Tokyo" \
    --oidc-service-account-email="$SCHEDULER_SA_EMAIL" \
    --oidc-token-audience="$FUNCTION_URL" \
    --project=$GCP_PROJECT_ID

# ジョブ確認
gcloud scheduler jobs describe check-new-video-schedule \
    --location=asia-northeast1 \
    --project=$GCP_PROJECT_ID
```

**重要なパラメータ**:
- `--oidc-service-account-email`: OIDC認証に使用するサービスアカウント
- `--oidc-token-audience`: トークンの検証対象（Function URL）

**期待される出力**:
```yaml
httpTarget:
  httpMethod: GET
  oidcToken:
    audience: https://check-new-video-xxxxx-an.a.run.app
    serviceAccountEmail: cloud-scheduler-invoker@{PROJECT_ID}.iam.gserviceaccount.com
  uri: https://check-new-video-xxxxx-an.a.run.app
schedule: 0 */2 * * *
timeZone: Asia/Tokyo
```

## 動作確認

### 1. 認証付き手動テスト

```bash
# 自分のIDトークンを使用してリクエスト
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $FUNCTION_URL
```

**期待される出力**:
```json
{
  "status": "success",
  "stats": {
    "foundVideos": 0,
    "filteredVideos": 0,
    "skippedVideos": 0,
    "publishedVideos": 0,
    "errors": 0
  }
}
```

### 2. 認証なしアクセステスト（失敗することを確認）

```bash
# 認証なしでアクセス（403エラーが返されることを確認）
curl -v $FUNCTION_URL
```

**期待される出力**:
```
< HTTP/2 403
...
{
  "error": {
    "code": 403,
    "message": "Forbidden",
    "status": "PERMISSION_DENIED"
  }
}
```

✅ 403エラーが返されればセキュリティ設定が正常に機能しています。

### 3. Cloud Schedulerからの実行テスト

```bash
# Cloud Schedulerジョブを手動実行
gcloud scheduler jobs run check-new-video-schedule \
    --location=asia-northeast1 \
    --project=$GCP_PROJECT_ID

# 実行ログを確認（1分程度待ってから）
gcloud functions logs read check-new-video \
    --region=asia-northeast1 \
    --project=$GCP_PROJECT_ID \
    --limit=20
```

**期待されるログ**:
```
...
INFO     YouTube API client initialized with OAuth2
INFO     Checking for videos published within 150 minutes
INFO     Found 0 videos within 150 minutes
INFO     Check completed: {'foundVideos': 0, 'filteredVideos': 0, ...}
```

✅ ログに`Check completed`が表示されればCloud Schedulerからの実行が成功しています。

## トラブルシューティング

### エラー: "PERMISSION_DENIED: Missing or insufficient permissions"

**原因**: Cloud Scheduler用サービスアカウントにCloud Function呼び出し権限がない

**解決策**:
```bash
# 権限を再付与
gcloud functions add-invoker-policy-binding check-new-video \
    --region=asia-northeast1 \
    --member="serviceAccount:cloud-scheduler-invoker@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
    --project=$GCP_PROJECT_ID
```

### エラー: "Service account does not exist"

**原因**: Cloud Scheduler用サービスアカウントが作成されていない

**解決策**:
```bash
# サービスアカウントを作成
gcloud iam service-accounts create cloud-scheduler-invoker \
    --display-name="Cloud Scheduler invoker for Cloud Functions" \
    --project=$GCP_PROJECT_ID
```

### Cloud Schedulerから403エラー

**原因**: OIDC認証の設定が不足している、またはFunction URLが間違っている

**解決策**:
```bash
# Cloud Schedulerジョブを削除
gcloud scheduler jobs delete check-new-video-schedule \
    --location=asia-northeast1 \
    --project=$GCP_PROJECT_ID

# 正しいパラメータで再作成（上記の手順5を参照）
```

## セキュリティ確認チェックリスト

- [ ] Cloud Function呼び出しに認証トークンが必須（認証なしでは403エラー）
- [ ] Cloud Schedulerからの実行が成功
- [ ] Cloud Scheduler用サービスアカウントに`roles/cloudfunctions.invoker`権限がある
- [ ] Cloud Function実行用サービスアカウントに最小限の権限のみ付与
- [ ] Function URLが外部に公開されていない（ドキュメント等から削除）

## 参考資料

- [ADR-014: Cloud FunctionのOIDC認証による保護](../../../docs/adr/014-cloud-function-oidc-authentication.md)
- [Google Cloud: Authenticating function-to-function](https://cloud.google.com/functions/docs/securing/authenticating)
- [Google Cloud: Cloud Scheduler with OIDC authentication](https://cloud.google.com/scheduler/docs/creating#authentication)
