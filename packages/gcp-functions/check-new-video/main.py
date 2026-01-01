"""
Cloud Function: 新着動画チェック
Cloud Schedulerから2時間毎に実行され、自分の新着動画をPub/Subに発行

処理フロー:
1. YouTube APIでforMine=Trueで自分の新着動画を取得（最大5件）
2. 公開日時と現在日時を比較してフィルタ（2.5時間以内）
3. Firestoreで重複チェック（処理済み動画は除外）
4. 未処理動画をPub/Subに発行
5. Firestoreに処理履歴を保存

設計根拠（ADR-001より）:
- 配信頻度: 1日1回〜数回（30分〜1時間/本）
- 2時間間隔 + 2.5時間フィルタ = 30分のバッファで取りこぼし防止
- YouTube API quotaの節約（1日12回の実行）

注意:
- forMine=TrueではpublishedAfterパラメータは使用できない
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

# forMine=Trueを使用するためTARGET_CHANNEL_IDSは不要
# スケジュール間隔（分）と許容範囲（分）
# 配信頻度: 1日1回〜数回（30分〜1時間/本）を想定
SCHEDULE_INTERVAL_MINUTES = 120  # Cloud Schedulerの実行間隔（2時間毎）
ACCEPTABLE_AGE_MINUTES = 150     # 取得対象とする動画の最大経過時間（2.5時間、余裕を持たせる）
MAX_RESULTS = 5                  # 取得する動画の最大件数（2時間で2-3本程度を想定）

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


def get_my_recent_videos(youtube, max_age_minutes: int = ACCEPTABLE_AGE_MINUTES) -> List[Dict[str, Any]]:
    """
    forMine=Trueで自分の動画を取得し、公開日時でフィルタ

    注意: forMine=TrueではpublishedAfterパラメータが使えないため、
    取得後に手動でフィルタリングを行う
    """
    try:
        request = youtube.search().list(
            part="id,snippet",
            forMine=True,
            type="video",
            order="date",
            maxResults=MAX_RESULTS  # 2時間で2-3本程度を想定
        )
        response = request.execute()

        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(minutes=max_age_minutes)

        videos = []
        for item in response.get("items", []):
            if item["id"]["kind"] == "youtube#video":
                # 公開日時をパース
                published_at_str = item["snippet"]["publishedAt"]
                published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))

                # 指定時間内の動画のみ追加
                if published_at >= cutoff_time:
                    videos.append({
                        "videoId": item["id"]["videoId"],
                        "title": item["snippet"]["title"],
                        "channelId": item["snippet"]["channelId"],
                        "channelTitle": item["snippet"]["channelTitle"],
                        "publishedAt": published_at_str,
                    })
                    logger.info(f"Found recent video: {item['id']['videoId']} published at {published_at_str}")
                else:
                    logger.debug(f"Skipping old video: {item['id']['videoId']} published at {published_at_str}")

        logger.info(f"Found {len(videos)} videos within {max_age_minutes} minutes")
        return videos

    except HttpError as e:
        logger.error(f"YouTube API error: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting videos: {e}")
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
    1. forMine=Trueで自分の新着動画を取得
    2. 公開日時でフィルタ（ACCEPTABLE_AGE_MINUTES以内）
    3. 重複チェック（Firestore）
    4. 未処理動画のみPub/Subに発行
    5. Firestoreに処理履歴を記録
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
        "foundVideos": 0,
        "filteredVideos": 0,
        "skippedVideos": 0,
        "publishedVideos": 0,
        "errors": 0,
    }

    logger.info(f"Checking for videos published within {ACCEPTABLE_AGE_MINUTES} minutes")

    # 自分の動画を取得（日時フィルタ済み）
    videos = get_my_recent_videos(youtube, max_age_minutes=ACCEPTABLE_AGE_MINUTES)
    stats["foundVideos"] = len(videos)

    for video in videos:
        video_id = video["videoId"]
        stats["filteredVideos"] += 1

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
