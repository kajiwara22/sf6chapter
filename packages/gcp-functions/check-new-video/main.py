"""
Cloud Function: 新着動画チェック
Cloud Schedulerから15分毎に実行され、対象チャンネルの新着動画をPub/Subに発行

処理フロー:
1. YouTube APIで対象チャンネルの新着動画を取得
2. Firestoreで重複チェック（処理済み動画は除外）
3. 未処理動画をPub/Subに発行
4. Firestoreに処理履歴を保存
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import functions_framework
from google.cloud import pubsub_v1, firestore
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC", "sf6-video-process")
TARGET_CHANNEL_IDS = os.environ.get("TARGET_CHANNEL_IDS", "").split(",")

# Firestore設定
FIRESTORE_COLLECTION = "processed_videos"

# グローバルクライアント（再利用のため）
_firestore_client: Optional[firestore.Client] = None
_pubsub_publisher: Optional[pubsub_v1.PublisherClient] = None


def get_firestore_client() -> firestore.Client:
    """Firestoreクライアントを取得（シングルトン）"""
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = firestore.Client(project=PROJECT_ID)
    return _firestore_client


def get_pubsub_publisher() -> pubsub_v1.PublisherClient:
    """Pub/Sub Publisherクライアントを取得（シングルトン）"""
    global _pubsub_publisher
    if _pubsub_publisher is None:
        _pubsub_publisher = pubsub_v1.PublisherClient()
    return _pubsub_publisher


def is_video_processed(video_id: str) -> bool:
    """動画が処理済みかどうかをFirestoreで確認"""
    try:
        db = get_firestore_client()
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(video_id)
        doc = doc_ref.get()
        return doc.exists
    except Exception as e:
        logger.error(f"Firestore check error for {video_id}: {e}")
        # エラー時は未処理として扱う（重複処理のリスクを取る）
        return False


def mark_video_as_processing(video_id: str, video_data: Dict[str, Any]) -> bool:
    """動画を処理中としてFirestoreに記録"""
    try:
        db = get_firestore_client()
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(video_id)

        # ドキュメントが既に存在する場合は処理しない
        if doc_ref.get().exists:
            logger.info(f"Video {video_id} already exists in Firestore, skipping")
            return False

        # 新規ドキュメントとして作成
        doc_ref.set({
            "videoId": video_id,
            "title": video_data.get("title", ""),
            "channelId": video_data.get("channelId", ""),
            "channelTitle": video_data.get("channelTitle", ""),
            "publishedAt": video_data.get("publishedAt", ""),
            "status": "queued",  # queued, processing, completed, failed
            "queuedAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        logger.info(f"Video {video_id} marked as queued in Firestore")
        return True
    except Exception as e:
        logger.error(f"Firestore write error for {video_id}: {e}")
        # エラー時は処理を継続しない（重複発行を避ける）
        return False


def get_recent_videos(youtube, channel_id: str, hours: int = 1) -> List[Dict[str, Any]]:
    """指定チャンネルの最近の動画を取得"""
    try:
        published_after = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        request = youtube.search().list(
            part="id,snippet",
            channelId=channel_id,
            publishedAfter=published_after,
            type="video",
            order="date",
            maxResults=10
        )
        response = request.execute()

        videos = []
        for item in response.get("items", []):
            if item["id"]["kind"] == "youtube#video":
                videos.append({
                    "videoId": item["id"]["videoId"],
                    "title": item["snippet"]["title"],
                    "channelId": channel_id,
                    "channelTitle": item["snippet"]["channelTitle"],
                    "publishedAt": item["snippet"]["publishedAt"],
                })

        return videos
    except HttpError as e:
        logger.error(f"YouTube API error for channel {channel_id}: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting videos for channel {channel_id}: {e}")
        return []


def publish_to_pubsub(video_data: Dict[str, Any]) -> bool:
    """Pub/Subにメッセージを発行"""
    try:
        publisher = get_pubsub_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC)

        message_json = json.dumps(video_data)
        message_bytes = message_json.encode("utf-8")

        future = publisher.publish(topic_path, message_bytes)
        message_id = future.result(timeout=10.0)
        logger.info(f"Published message {message_id} for video {video_data['videoId']}")
        return True
    except Exception as e:
        logger.error(f"Error publishing video {video_data['videoId']}: {e}")
        return False


@functions_framework.http
def check_new_video(request):
    """
    HTTPトリガーのエントリポイント

    処理フロー:
    1. 各チャンネルから新着動画を取得
    2. 重複チェック（Firestore）
    3. 未処理動画のみPub/Subに発行
    4. Firestoreに処理履歴を記録
    """
    # 環境変数チェック
    if not PROJECT_ID:
        logger.error("GCP_PROJECT_ID environment variable is not set")
        return {"status": "error", "message": "Missing GCP_PROJECT_ID"}, 500

    # YouTube APIクライアントを構築（ADC使用）
    try:
        # Application Default Credentials (サービスアカウント) を使用
        from google.auth import default
        from google.auth.transport.requests import Request

        credentials, _ = default(scopes=["https://www.googleapis.com/auth/youtube.readonly"])
        youtube = build("youtube", "v3", credentials=credentials)
        logger.info("YouTube API client initialized with service account")
    except Exception as e:
        logger.error(f"Failed to build YouTube API client: {e}")
        return {"status": "error", "message": f"YouTube API error: {str(e)}"}, 500

    # 統計情報
    stats = {
        "checkedChannels": 0,
        "foundVideos": 0,
        "skippedVideos": 0,
        "publishedVideos": 0,
        "errors": 0,
    }

    for channel_id in TARGET_CHANNEL_IDS:
        if not channel_id.strip():
            continue

        stats["checkedChannels"] += 1
        logger.info(f"Checking channel: {channel_id.strip()}")

        videos = get_recent_videos(youtube, channel_id.strip(), hours=1)
        stats["foundVideos"] += len(videos)

        for video in videos:
            video_id = video["videoId"]

            # 重複チェック
            if is_video_processed(video_id):
                logger.info(f"Video {video_id} already processed, skipping")
                stats["skippedVideos"] += 1
                continue

            # Firestoreに記録（トランザクション的に処理）
            if not mark_video_as_processing(video_id, video):
                logger.warning(f"Failed to mark video {video_id} as processing, skipping")
                stats["skippedVideos"] += 1
                continue

            # Pub/Subに発行
            if publish_to_pubsub(video):
                stats["publishedVideos"] += 1
            else:
                stats["errors"] += 1

    logger.info(f"Check completed: {stats}")

    return {
        "status": "success",
        "stats": stats,
    }, 200
