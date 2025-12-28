"""
Cloud Function: 新着動画チェック
Cloud Schedulerから15分毎に実行され、対象チャンネルの新着動画をPub/Subに発行
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any

import functions_framework
from google.cloud import pubsub_v1
from googleapiclient.discovery import build


# 環境変数
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC", "sf6-video-process")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
TARGET_CHANNEL_IDS = os.environ.get("TARGET_CHANNEL_IDS", "").split(",")


def get_recent_videos(youtube, channel_id: str, hours: int = 1) -> list[Dict[str, Any]]:
    """指定チャンネルの最近の動画を取得"""
    published_after = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"

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


def publish_to_pubsub(video_data: Dict[str, Any]) -> None:
    """Pub/Subにメッセージを発行"""
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC)

    message_json = json.dumps(video_data)
    message_bytes = message_json.encode("utf-8")

    future = publisher.publish(topic_path, message_bytes)
    print(f"Published message {future.result()} for video {video_data['videoId']}")


@functions_framework.http
def check_new_video(request):
    """HTTPトリガーのエントリポイント"""
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    total_published = 0

    for channel_id in TARGET_CHANNEL_IDS:
        if not channel_id.strip():
            continue

        print(f"Checking channel: {channel_id}")
        videos = get_recent_videos(youtube, channel_id.strip(), hours=1)

        for video in videos:
            try:
                publish_to_pubsub(video)
                total_published += 1
            except Exception as e:
                print(f"Error publishing video {video['videoId']}: {e}")

    return {
        "status": "success",
        "checkedChannels": len([c for c in TARGET_CHANNEL_IDS if c.strip()]),
        "publishedVideos": total_published,
    }, 200
