# ADR-012: check-new-video Cloud Function専用サービスアカウントの採用

## ステータス

採用 (2026-01-04)

## コンテキスト

Cloud Functions `check-new-video`のデプロイにおいて、当初はデフォルトのApp Engineサービスアカウント（`${GOOGLE_CLOUD_PROJECT}@appspot.gserviceaccount.com`）を使用していました。

しかし、この命名規則には以下の問題がありました：

1. **用途の不明確さ**: `appspot.gserviceaccount.com`という名前では、このサービスアカウントが何に使われているのか一目で判別できない
2. **管理の複雑さ**: 複数のCloud Functionsが存在する場合、どのサービスアカウントがどの関数に対応しているのか追跡が困難
3. **権限管理の困難さ**: IAMポリシーで権限付与する際、検索性や監査性が低い
4. **セキュリティの観点**: 最小権限の原則に基づき、各Cloud Functionに専用のサービスアカウントを割り当てるべき

## 決定事項

Cloud Function `check-new-video`に専用サービスアカウント **`check-new-video-sa`** を作成・使用することを決定しました。

### サービスアカウント名

- **名前**: `check-new-video-sa`
- **フルメールアドレス**: `check-new-video-sa@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com`
- **表示名**: "Service account for check-new-video Cloud Function"

### 必要な権限

このサービスアカウントには以下の権限を付与します：

1. **Firestore**: `roles/datastore.user`（処理済み動画の読み書き）
2. **Pub/Sub**: `roles/pubsub.publisher`（動画情報の発行）
3. **Secret Manager**: `roles/secretmanager.secretAccessor`（OAuth2認証情報の取得）
   - 対象シークレット: `youtube-refresh-token`, `youtube-client-id`, `youtube-client-secret`

## 代替案

### 1. デフォルトのApp Engineサービスアカウントを使用

**メリット**:
- 追加のサービスアカウント作成が不要
- セットアップ手順が簡略化される

**デメリット**:
- 用途が不明確で管理が煩雑
- 複数のCloud Functionsで共用すると権限の分離が困難
- セキュリティ監査で責任範囲が不明確

**却下理由**: 管理性とセキュリティの観点から不適切

### 2. より汎用的な名前（例: `youtube-video-checker-sa`）

**メリット**:
- ビジネスロールを反映した命名
- 複数のマイクロサービスで構成される場合に対応可能

**デメリット**:
- 現時点では単一のCloud Functionしか存在しない
- 将来の拡張性を過度に考慮した命名で、現在の用途と乖離する可能性

**却下理由**: YAGNI（You Aren't Gonna Need It）原則に反する

### 3. プレフィックス付き命名（例: `cf-check-new-video-sa`）

**メリット**:
- `cf-` プレフィックスでCloud Functions専用と明示
- 他のコンピュートリソース（Compute Engine等）と区別可能

**デメリット**:
- 現時点で複数のコンピュートリソースタイプは使用していない
- プレフィックスが冗長

**却下理由**: 現在のアーキテクチャでは不要な複雑さを追加する

## 根拠

### 採用した命名規則 `check-new-video-sa` の利点

1. **一対一対応**: Cloud Function名と直接対応しており、直感的に理解できる
2. **短くて管理しやすい**: 冗長なプレフィックスがなく、コマンドやコンソールでの入力が容易
3. **検索性**: IAM監査ログやCloud Consoleでの検索が容易
4. **将来の拡張性**: 複数のCloud Functionsを追加する場合も、同じ命名規則を適用できる
5. **最小権限の原則**: 関数ごとに専用のサービスアカウントを割り当てることで、権限の分離が明確

### セキュリティ上の利点

- **権限の最小化**: 必要な権限のみを付与し、他のサービスへの影響を排除
- **監査性**: IAM監査ログで特定のCloud Functionの動作を追跡しやすい
- **責任の明確化**: サービスアカウント名から責任範囲が明確

## 影響

### ドキュメント更新

以下のドキュメントを更新する必要があります：

1. **`packages/gcp-functions/check-new-video/README.md`**
   - サービスアカウントの説明セクション
   - デプロイ手順
   - 権限設定手順

2. **`packages/gcp-functions/check-new-video/SETUP_OAUTH2.md`**
   - サービスアカウントへの権限付与コマンド

3. **`packages/gcp-functions/check-new-video/deploy.sh`**
   - `--service-account` フラグの値を更新

### デプロイ手順の変更

既存のデプロイスクリプトを以下のように更新します：

```bash
# サービスアカウント作成（初回のみ）
SERVICE_ACCOUNT_NAME="check-new-video-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"

gcloud iam service-accounts create $SERVICE_ACCOUNT_NAME \
    --display-name="Service account for check-new-video Cloud Function" \
    --project=$GOOGLE_CLOUD_PROJECT

# 権限付与
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/datastore.user"

gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/pubsub.publisher"

for SECRET_NAME in youtube-refresh-token youtube-client-id youtube-client-secret; do
    gcloud secrets add-iam-policy-binding $SECRET_NAME \
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
        --role="roles/secretmanager.secretAccessor" \
        --project=$GOOGLE_CLOUD_PROJECT
done

# Cloud Functionデプロイ
gcloud functions deploy check-new-video \
    --gen2 \
    --runtime=python312 \
    --region=asia-northeast1 \
    --source=. \
    --entry-point=check_new_video \
    --trigger-http \
    --allow-unauthenticated \
    --service-account=${SERVICE_ACCOUNT_EMAIL} \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT},PUBSUB_TOPIC=sf6-video-process" \
    --project=$GOOGLE_CLOUD_PROJECT
```

## 関連するADR

- [ADR-006: Firestoreによる重複防止](./006-firestore-for-duplicate-prevention.md)
- [ADR-008: Cloud FunctionsでのOAuth2ユーザー認証](./008-oauth2-user-authentication-in-cloud-functions.md)

## 参考資料

- [Google Cloud IAM Best Practices](https://cloud.google.com/iam/docs/best-practices)
- [Cloud Functions Service Accounts](https://cloud.google.com/functions/docs/securing/function-identity)
- [Principle of Least Privilege](https://cloud.google.com/iam/docs/using-iam-securely#least_privilege)
