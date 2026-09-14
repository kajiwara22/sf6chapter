# GCP リソース削除手順（check-new-video 廃止）

`packages/gcp-functions/check-new-video` の廃止（[ADR-046](adr/046-remove-gcp-functions.md)）に伴い、未使用となった GCP リソースを削除する手順です。

> **重要**: この手順は破壊的操作です。実行前に必ず「削除しないリソース」の節を確認し、対象プロジェクトが正しいことを確認してください。

## 0. 前提

```bash
# gcloud のログインとプロジェクト設定
gcloud auth login
export GOOGLE_CLOUD_PROJECT="my-hobby-cloud-lab"   # 実際のプロジェクトIDに置き換え
gcloud config set project $GOOGLE_CLOUD_PROJECT
```

対象リージョン: `asia-northeast1`（東京）

---

## 削除しないリソース（継続利用）

以下はローカル PC（`packages/local/`）が引き続き利用するため **削除しないでください**。

| リソース | 理由 |
|---------|------|
| Firestore の `processed_videos` コレクション | ローカルの `FirestoreClient` が重複防止・状態管理で利用 |
| OAuth クライアント（`client_secrets.json` の元） | ローカルの YouTube Data API / Vertex AI 認証で利用 |
| Vertex AI（Gemini）/ YouTube Data API / Firestore API | ローカルが直接利用 |

---

## 1. 現状の一覧確認

削除前に、実際に存在するリソース名を確認します（ドキュメントと実際の名前が異なる場合があるため）。

```bash
# Cloud Scheduler ジョブ
gcloud scheduler jobs list --location=asia-northeast1 --project=$GOOGLE_CLOUD_PROJECT

# Cloud Functions（Gen2 は Cloud Run としても表示される）
gcloud functions list --project=$GOOGLE_CLOUD_PROJECT

# Pub/Sub トピック / サブスクリプション
gcloud pubsub topics list --project=$GOOGLE_CLOUD_PROJECT
gcloud pubsub subscriptions list --project=$GOOGLE_CLOUD_PROJECT

# Secret Manager シークレット
gcloud secrets list --project=$GOOGLE_CLOUD_PROJECT

# サービスアカウント
gcloud iam service-accounts list --project=$GOOGLE_CLOUD_PROJECT
```

---

## 2. 削除手順（依存関係の順）

### 2.1 Cloud Scheduler ジョブ（最初に削除）

定期実行を止めるため、最初に削除します。ジョブ名は `check-new-video-schedule`（旧ドキュメントでは `check-new-video-job` の記載もあり）。上記の一覧で確認してください。

```bash
gcloud scheduler jobs delete check-new-video-schedule \
    --location=asia-northeast1 \
    --project=$GOOGLE_CLOUD_PROJECT
```

### 2.2 Cloud Function（Gen2）

```bash
gcloud functions delete check-new-video \
    --region=asia-northeast1 \
    --gen2 \
    --project=$GOOGLE_CLOUD_PROJECT
```

Gen2 は Cloud Run サービスとしてデプロイされるため、このコマンドで裏側の Cloud Run サービスも削除されます。

### 2.3 Pub/Sub サブスクリプション

候補: `new-video-trigger` / `sf6-video-process-sub`（ADR-036 以降は未使用）。一覧で確認し、存在するものを削除します。

```bash
gcloud pubsub subscriptions delete new-video-trigger \
    --project=$GOOGLE_CLOUD_PROJECT

gcloud pubsub subscriptions delete sf6-video-process-sub \
    --project=$GOOGLE_CLOUD_PROJECT
```

### 2.4 Pub/Sub トピック

候補: `sf6-new-video`（deploy.sh の `PUBSUB_TOPIC`）。サブスクリプション削除後にトピックを削除します。

```bash
gcloud pubsub topics delete sf6-new-video \
    --project=$GOOGLE_CLOUD_PROJECT
```

### 2.5 Secret Manager シークレット

check-new-video 専用の 3 シークレットを削除します。ローカル PC は Secret Manager を使わずローカルの `client_secrets.json` / `token.pickle` で認証するため、削除しても影響ありません。

```bash
gcloud secrets delete youtube-refresh-token --project=$GOOGLE_CLOUD_PROJECT
gcloud secrets delete youtube-client-id     --project=$GOOGLE_CLOUD_PROJECT
gcloud secrets delete youtube-client-secret --project=$GOOGLE_CLOUD_PROJECT
```

### 2.6 サービスアカウント

```bash
gcloud iam service-accounts delete \
    check-new-video-sa@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com \
    --project=$GOOGLE_CLOUD_PROJECT

gcloud iam service-accounts delete \
    cloud-scheduler-invoker@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com \
    --project=$GOOGLE_CLOUD_PROJECT
```

> サービスアカウント削除により、これらの SA に紐づく IAM バインディング（プロジェクトレベル・シークレットレベル）も解除されます。

### 2.7 （オプション）Firestore コレクション

**通常は不要です。** ローカル PC が `processed_videos` を引き続き利用するため残します。

ローカルの Firestore 利用も完全にやめる場合のみ、Firebase Console で `processed_videos` コレクションを手動削除してください（gcloud CLI ではコレクション削除できないため）。

### 2.8 （オプション）未使用 API の無効化

check-new-video 専用だった API のみ無効化できます。**ローカル PC が使う API は有効のまま残してください。**

```bash
# 無効化してよい（check-new-video 専用）
gcloud services disable cloudfunctions.googleapis.com  --project=$GOOGLE_CLOUD_PROJECT
gcloud services disable run.googleapis.com             --project=$GOOGLE_CLOUD_PROJECT
gcloud services disable cloudscheduler.googleapis.com  --project=$GOOGLE_CLOUD_PROJECT
gcloud services disable pubsub.googleapis.com          --project=$GOOGLE_CLOUD_PROJECT
gcloud services disable secretmanager.googleapis.com   --project=$GOOGLE_CLOUD_PROJECT
gcloud services disable cloudbuild.googleapis.com      --project=$GOOGLE_CLOUD_PROJECT

# 残す（ローカル PC が利用）
# - firestore.googleapis.com    : 重複防止・キュー
# - aiplatform.googleapis.com   : Vertex AI (Gemini)
# - YouTube Data API v3         : チャプター更新
```

> `run.googleapis.com` は他に Cloud Run を使っていない場合のみ無効化してください。

---

## 3. 削除後の検証

```bash
# すべて空になっていることを確認
gcloud scheduler jobs list --location=asia-northeast1 --project=$GOOGLE_CLOUD_PROJECT
gcloud functions list --project=$GOOGLE_CLOUD_PROJECT
gcloud pubsub topics list --project=$GOOGLE_CLOUD_PROJECT
gcloud pubsub subscriptions list --project=$GOOGLE_CLOUD_PROJECT
gcloud secrets list --project=$GOOGLE_CLOUD_PROJECT
gcloud iam service-accounts list --project=$GOOGLE_CLOUD_PROJECT
```

---

## 4. コンソール（UI）での代替手順

各リソースは Google Cloud Console からも削除できます：

| リソース | コンソールの場所 |
|---------|-----------------|
| Cloud Scheduler | Cloud Scheduler → 該当ジョブ → 削除 |
| Cloud Functions | Cloud Functions → `check-new-video` → 削除 |
| Pub/Sub | Pub/Sub → トピック / サブスクリプション → 削除 |
| Secret Manager | Security → Secret Manager → 各シークレット → 削除 |
| サービスアカウント | IAM & Admin → サービスアカウント → 削除 |
| API | API とサービス → 有効な API → 該当 API → 無効にする |

---

## 補足

- Cloud Logging のログはリソース削除後も保持期間（既定 30 日）経過で自動削除されるため、手動削除は不要です。
- `docs/architecture.drawio` の GCP ブロック（Scheduler / Functions / Pub/Sub）は別途手動で更新が必要です（図の編集は draw.io で実施）。
