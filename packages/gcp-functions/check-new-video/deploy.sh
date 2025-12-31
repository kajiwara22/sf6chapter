#!/bin/bash
# Cloud Function デプロイスクリプト

set -e

# 環境変数チェック
if [ -z "$GCP_PROJECT_ID" ]; then
    echo "Error: GCP_PROJECT_ID environment variable is not set"
    exit 1
fi

if [ -z "$TARGET_CHANNEL_IDS" ]; then
    echo "Error: TARGET_CHANNEL_IDS environment variable is not set"
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

echo "Deploying Cloud Function: $FUNCTION_NAME"
echo "Project: $GCP_PROJECT_ID"
echo "Region: $REGION"

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
    --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID,TARGET_CHANNEL_IDS=$TARGET_CHANNEL_IDS,PUBSUB_TOPIC=sf6-video-process" \
    --project=$GCP_PROJECT_ID

echo "Deployment complete!"
echo "Function URL:"
gcloud functions describe $FUNCTION_NAME --region=$REGION --project=$GCP_PROJECT_ID --format="value(serviceConfig.uri)"
