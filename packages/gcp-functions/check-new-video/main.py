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

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import functions_framework
import google.cloud.logging
import pytz
from google.cloud import firestore, pubsub_v1, secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ロギング設定（Cloud Logging統合）
# Cloud Loggingクライアントをセットアップ
logging_client = google.cloud.logging.Client()
logging_client.setup_logging()

# 標準的なPythonロギングを使用（Cloud Loggingに自動統合される）
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 環境変数
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
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
_secret_manager_client: Optional[secretmanager.SecretManagerServiceClient] = None
_oauth_credentials: Optional[Credentials] = None


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


def get_secret_manager_client() -> secretmanager.SecretManagerServiceClient:
    """Secret Managerクライアントを取得（シングルトン）"""
    global _secret_manager_client
    if _secret_manager_client is None:
        _secret_manager_client = secretmanager.SecretManagerServiceClient()
    return _secret_manager_client


def get_secret(secret_name: str) -> str:
    """Secret Managerからシークレットを取得"""
    try:
        client = get_secret_manager_client()
        name = f"projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        logger.info(f"Successfully retrieved secret: {secret_name}")
        return secret_value
    except Exception as e:
        logger.error(f"Failed to retrieve secret {secret_name}: {e}")
        raise


def get_oauth_credentials() -> Credentials:
    """OAuth2認証情報を取得（Secret Managerから）"""
    global _oauth_credentials

    if _oauth_credentials is not None:
        logger.info("Using cached OAuth2 credentials")
        return _oauth_credentials

    try:
        # Secret Managerからクレデンシャルを取得
        client_id = get_secret("youtube-client-id")
        client_secret = get_secret("youtube-client-secret")
        refresh_token = get_secret("youtube-refresh-token")

        # OAuth2認証情報を構築
        credentials = Credentials(
            token=None,  # Access tokenは自動取得される
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"]
        )

        # キャッシュに保存
        _oauth_credentials = credentials
        logger.info("OAuth2 credentials initialized successfully")
        return credentials

    except Exception as e:
        logger.error(f"Failed to initialize OAuth2 credentials: {e}")
        raise


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


def is_ps5_auto_title(title: str) -> bool:
    """PS5のデフォルトタイトル（連続した同一のひらがな3文字）判定"""
    return bool(re.match(r'^([ぁ-ん])\1{2}$', title))


def get_rename_title(published_at_utc: str) -> str:
    """
    公開日時（UTC）から JST を求め、時刻に応じてリネーム後のタイトルを決定

    Args:
        published_at_utc: YouTube APIから取得した公開日時（ISO 8601形式、UTC）
                         例: "2025-12-04T10:30:00Z"

    Returns:
        リネーム後のタイトル
        例: "お昼休みにスト６ 2025-12-04"
    """
    # UTC → JST 変換
    dt_utc = datetime.fromisoformat(published_at_utc.replace("Z", "+00:00"))
    jst = pytz.timezone("Asia/Tokyo")
    dt_jst = dt_utc.astimezone(jst)

    # 時刻を取得
    hour = dt_jst.hour
    date_str = dt_jst.strftime("%Y-%m-%d")

    # 時刻帯で判定
    if 12 <= hour < 13:
        prefix = "お昼休みにスト６"
    elif 18 <= hour < 22:
        prefix = "就業後にスト６"
    else:
        prefix = "PS5からスト６"

    return f"{prefix} {date_str}"


def rename_video_title(youtube, video_id: str, new_title: str) -> bool:
    """
    YouTube Data APIでビデオタイトルを更新

    Args:
        youtube: YouTube API クライアント
        video_id: 更新対象の動画 ID
        new_title: 新しいタイトル

    Returns:
        成功時 True、失敗時 False
    """
    try:
        # 現在のビデオ情報を取得
        get_response = youtube.videos().list(
            part="snippet",
            id=video_id
        ).execute()

        if not get_response.get("items"):
            logger.error(f"Video not found: {video_id}")
            return False

        # タイトルを更新
        snippet = get_response["items"][0]["snippet"]
        snippet["title"] = new_title

        # 更新リクエスト実行
        youtube.videos().update(
            part="snippet",
            body={
                "id": video_id,
                "snippet": snippet
            }
        ).execute()

        logger.info(f"Successfully renamed video {video_id} to '{new_title}'")
        return True

    except HttpError as e:
        logger.error(f"YouTube API error while renaming {video_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error renaming {video_id}: {e}")
        return False


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
        logger.error("GOOGLE_CLOUD_PROJECT environment variable is not set")
        return {"status": "error", "message": "Missing GOOGLE_CLOUD_PROJECT"}, 500

    # YouTube APIクライアントを構築（OAuth2使用）
    try:
        # Secret ManagerからOAuth2認証情報を取得
        credentials = get_oauth_credentials()
        youtube = build("youtube", "v3", credentials=credentials)
        logger.info("YouTube API client initialized with OAuth2")
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
        title = video["title"]
        published_at = video["publishedAt"]
        stats["filteredVideos"] += 1

        # PS5自動タイトル検出と更新
        if is_ps5_auto_title(title):
            logger.info(f"Detected PS5 auto-title: '{title}' for {video_id}")

            # 新しいタイトルを決定
            new_title = get_rename_title(published_at)

            # YouTube APIでタイトルを更新（エラーは処理継続）
            if rename_video_title(youtube, video_id, new_title):
                logger.info(f"Renamed {video_id}: '{title}' → '{new_title}'")
                # Firestore記録時に新しいタイトルを使用
                video["title"] = new_title
            else:
                logger.warning(f"Failed to rename {video_id}, proceeding with original title")
                # エラーでも処理は継続（元のタイトルで記録）

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
