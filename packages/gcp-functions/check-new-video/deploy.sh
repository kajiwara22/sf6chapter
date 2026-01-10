#!/bin/bash
# Cloud Function デプロイスクリプト

set -e

# 環境変数チェック
if [ -z "$GOOGLE_CLOUD_PROJECT" ]; then
    echo "Error: GOOGLE_CLOUD_PROJECT environment variable is not set"
    exit 1
fi


# デプロイ設定
FUNCTION_NAME="check-new-video"
REGION="asia-northeast1"  # 東京リージョン
RUNTIME="python312"
ENTRY_POINT="check_new_video"
MEMORY="256MB"
TIMEOUT="60s"
MAX_INSTANCES="1"

# 専用サービスアカウント（ADR-012で定義）
SERVICE_ACCOUNT_NAME="check-new-video-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"

echo "Deploying Cloud Function: $FUNCTION_NAME"
echo "Project: $GOOGLE_CLOUD_PROJECT"
echo "Region: $REGION"
echo "Service Account: $SERVICE_ACCOUNT_EMAIL"

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=$RUNTIME \
    --region=$REGION \
    --source=. \
    --entry-point=$ENTRY_POINT \
    --trigger-http \
    --no-allow-unauthenticated \
    --memory=$MEMORY \
    --timeout=$TIMEOUT \
    --max-instances=$MAX_INSTANCES \
    --service-account=$SERVICE_ACCOUNT_EMAIL \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,PUBSUB_TOPIC=sf6-video-process" \
    --project=$GOOGLE_CLOUD_PROJECT

echo "Deployment complete!"
echo "Function URL:"
gcloud functions describe $FUNCTION_NAME --region=$REGION --project=$GOOGLE_CLOUD_PROJECT --format="value(serviceConfig.uri)"
