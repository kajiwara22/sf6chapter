# ADR-014: Cloud FunctionのOIDC認証による保護

## ステータス

承認済み

## コンテキスト

現在、`check-new-video` Cloud FunctionはHTTPトリガーで`--allow-unauthenticated`（認証不要）としてデプロイされています。

この設定では以下の問題があります：

### 現在の問題

1. **無制限アクセス**: エンドポイントURLを知っていれば誰でも実行可能
2. **コスト懸念**: 悪意あるユーザーによる大量リクエストで無用な課金が発生
3. **セキュリティリスク**: YouTube API quotaの浪費、Firestore/Pub/Subの不正利用
4. **ベストプラクティス違反**: Google Cloud推奨のセキュリティ設定に準拠していない

### 実行者の想定

このCloud FunctionはCloud Schedulerからのみ実行されることを想定しています：
- 実行間隔: 2時間毎（1日12回）
- 実行元: Cloud Scheduler（`check-new-video-schedule`ジョブ）
- 人間による手動実行: 不要（デバッグ時のみ）

## 決定

**OIDC（OpenID Connect）認証によるCloud Function保護**を採用します。

### 実装方針

#### 1. Cloud Scheduler専用サービスアカウント

```bash
# サービスアカウント作成
gcloud iam service-accounts create cloud-scheduler-invoker \
    --display-name="Cloud Scheduler invoker for Cloud Functions"
```

**命名規則**: `cloud-scheduler-invoker@{PROJECT_ID}.iam.gserviceaccount.com`

#### 2. Cloud Function権限設定

```bash
# Cloud Functions起動権限を付与
gcloud functions add-invoker-policy-binding check-new-video \
    --region=asia-northeast1 \
    --member="serviceAccount:cloud-scheduler-invoker@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"
```

**必要な権限**: `roles/cloudfunctions.invoker`（Cloud Function実行権限のみ）

#### 3. デプロイ設定変更

```bash
# 認証必須化（--allow-unauthenticatedを削除）
gcloud functions deploy check-new-video \
    --no-allow-unauthenticated \
    ...
```

#### 4. Cloud Scheduler設定更新

```bash
# OIDC認証を使用
gcloud scheduler jobs create http check-new-video-schedule \
    --oidc-service-account-email="cloud-scheduler-invoker@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com" \
    --oidc-token-audience="$FUNCTION_URL" \
    ...
```

**認証フロー**:
1. Cloud SchedulerがOIDCトークン生成
2. トークンをHTTPヘッダーに付与してリクエスト送信
3. Cloud FunctionがトークンをIAMで検証
4. 有効なトークンの場合のみ実行許可

## 代替案

### 1. API Key認証

**メリット**:
- シンプルな実装

**デメリット**:
- 鍵管理の複雑性（Secret Manager必要）
- 鍵漏洩のリスク
- コスト（Secret Managerの追加料金）
- Googleの推奨方式ではない

→ **却下**: OIDC認証が優位

### 2. VPC Service Controls

**メリット**:
- 最高レベルのセキュリティ

**デメリット**:
- **有料機能**（Google Cloud Premium Tier必須）
- オーバースペック（個人プロジェクトには過剰）
- 設定の複雑性

→ **却下**: コストとメリットが見合わない

### 3. 認証なし + 環境変数による簡易認証

**メリット**:
- 実装が簡単

**デメリット**:
- セキュリティが弱い（環境変数漏洩で終了）
- ベストプラクティス違反
- Googleの推奨方式ではない

→ **却下**: セキュリティが不十分

## 影響

### セキュリティ向上

- ✅ Cloud Schedulerからのリクエストのみ許可
- ✅ 外部からの不正アクセス完全防止
- ✅ YouTube API quotaの保護
- ✅ 無用な課金リスクの排除

### 運用への影響

- ⚠️ デバッグ時の手動実行方法が変更:
  ```bash
  # 従来（認証なし）
  curl $FUNCTION_URL

  # 新方式（認証トークン必須）
  curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $FUNCTION_URL
  ```

- ✅ Cloud Schedulerからの実行は変更なし（透過的に動作）

### コスト

- ✅ **追加コストなし**（OIDC認証は無料機能）
- ✅ 不正アクセス防止による**コスト削減効果**

## 実装手順

1. Cloud Scheduler専用サービスアカウント作成
2. `deploy.sh`の修正（`--no-allow-unauthenticated`追加）
3. Cloud Function再デプロイ
4. サービスアカウントに`roles/cloudfunctions.invoker`権限付与
5. Cloud Scheduler設定更新（OIDC認証追加）
6. 動作確認（Cloud Schedulerからの実行テスト）

詳細は[README.md](../../packages/gcp-functions/check-new-video/README.md)を参照。

## 参考資料

- [Google Cloud: Authenticating function-to-function](https://cloud.google.com/functions/docs/securing/authenticating)
- [Google Cloud: Cloud Scheduler with OIDC authentication](https://cloud.google.com/scheduler/docs/creating#authentication)
- [Google Cloud Security Best Practices](https://cloud.google.com/security/best-practices)

## 関連ADR

- [ADR-012: check-new-video専用サービスアカウント](012-check-new-video-dedicated-service-account.md)
