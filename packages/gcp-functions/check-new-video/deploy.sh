#!/bin/bash
# Cloud Function デプロイスクリプト

set -e

# 環境変数チェック
if [ -z "$GCP_PROJECT_ID" ]; then
    echo "Error: GCP_PROJECT_ID environment variable is not set"
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
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

echo "Deploying Cloud Function: $FUNCTION_NAME"
echo "Project: $GCP_PROJECT_ID"
echo "Region: $REGION"
echo "Service Account: $SERVICE_ACCOUNT_EMAIL"

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=$RUNTIME \
    --region=$REGION \
    --source=. \
    --entry-point=$ENTRY_POINT \
    --trigger-http \
    --allow-unauthenticated \
    --memory=$MEMORY \
    --timeout=$TIMEOUT \
    --max-instances=$MAX_INSTANCES \
    --service-account=$SERVICE_ACCOUNT_EMAIL \
    --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID,PUBSUB_TOPIC=sf6-video-process" \
    --project=$GCP_PROJECT_ID

echo "Deployment complete!"
echo "Function URL:"
gcloud functions describe $FUNCTION_NAME --region=$REGION --project=$GCP_PROJECT_ID --format="value(serviceConfig.uri)"
