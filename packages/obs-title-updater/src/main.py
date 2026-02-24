#!/usr/bin/env python3
"""
OBS配信開始イベント連動のYouTube動画タイトル更新スクリプト

packages/obs-title-updater 独立パッケージ

配信開始時にOBSスクリプト経由で実行され、
YouTube Data APIから最新の動画を取得し、
タイトルプレースホルダー {DateTime} をYYYY/MM/DD形式の日付に置き換える
"""

import logging
import sys
from datetime import datetime

import pytz
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from oauth import get_oauth_credentials

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_latest_video_with_placeholder(youtube_service, limit: int = 50) -> dict | None:
    """
    最新のアップロード済み動画から {DateTime} プレースホルダーを含むものを検索

    Args:
        youtube_service: YouTube API クライアント
        limit: 検索対象の最新動画数（デフォルト50）

    Returns:
        プレースホルダーを含む動画情報（ID、title、publishedAt）、
        または該当する動画がない場合は None
    """
    try:
        # 自分の最新アップロード動画を取得
        response = youtube_service.search().list(
            forMine=True,
            part="snippet",
            type="video",
            maxResults=limit,
            order="date"
        ).execute()

        videos = response.get("items", [])
        if not videos:
            logger.info("No videos found in account")
            return None

        # {DateTime} プレースホルダーを含む最初の動画を検索
        for video in videos:
            title = video["snippet"]["title"]
            if "{DateTime}" in title:
                logger.info(f"Found video with placeholder: {video['id']} - '{title}'")
                return {
                    "id": video["id"],
                    "title": title,
                    "publishedAt": video["snippet"]["publishedAt"]
                }

        logger.info("No video with {DateTime} placeholder found")
        return None

    except HttpError as e:
        logger.error(f"YouTube API error while searching videos: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error searching videos: {e}")
        return None


def convert_published_at_to_jst_date(published_at_utc: str) -> str | None:
    """
    YouTube APIから取得した公開日時（UTC）をJST準拠のYYYY/MM/DD形式に変換

    Args:
        published_at_utc: ISO 8601形式、UTC（例: "2026-02-25T10:30:00Z"）

    Returns:
        YYYY/MM/DD形式の日付文字列（例: "26/02/25"）、
        変換失敗時は None
    """
    try:
        # UTC → JST 変換
        dt_utc = datetime.fromisoformat(published_at_utc.replace("Z", "+00:00"))
        jst = pytz.timezone("Asia/Tokyo")
        dt_jst = dt_utc.astimezone(jst)

        # YYYY/MM/DD 形式に変換
        return dt_jst.strftime("%y/%m/%d")

    except Exception as e:
        logger.error(f"Error converting date: {e}")
        return None


def replace_placeholder_in_title(title: str, date_str: str) -> str:
    """
    タイトル内の {DateTime} プレースホルダーをYYYY/MM/DD形式の日付で置き換え

    Args:
        title: 置き換え前のタイトル（例: "スト６ランクマ {DateTime}"）
        date_str: 置き換える日付文字列（例: "26/02/25"）

    Returns:
        置き換え後のタイトル（例: "スト６ランクマ 26/02/25"）
    """
    return title.replace("{DateTime}", date_str)


def update_video_title(youtube_service, video_id: str, new_title: str) -> bool:
    """
    YouTube Data APIでビデオタイトルを更新

    Args:
        youtube_service: YouTube API クライアント
        video_id: 更新対象の動画ID
        new_title: 新しいタイトル

    Returns:
        成功時 True、失敗時 False
    """
    try:
        # 現在のビデオ情報を取得（snippet部分）
        get_response = youtube_service.videos().list(
            part="snippet",
            id=video_id
        ).execute()

        if not get_response.get("items"):
            logger.error(f"Video not found: {video_id}")
            return False

        # スニペット情報を取得してタイトルを更新
        snippet = get_response["items"][0]["snippet"]
        snippet["title"] = new_title

        # 更新リクエスト実行
        youtube_service.videos().update(
            part="snippet",
            body={
                "id": video_id,
                "snippet": snippet
            }
        ).execute()

        logger.info(f"Successfully updated video {video_id} title to '{new_title}'")
        return True

    except HttpError as e:
        logger.error(f"YouTube API error while updating {video_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error updating {video_id}: {e}")
        return False


def main(
    token_path: str | None = None,
    client_secrets_path: str | None = None,
    search_limit: int = 50
) -> int:
    """
    メイン処理：最新動画のタイトルプレースホルダーを置き換え

    Args:
        token_path: トークンファイルのパス（デフォルト: token.pickle）
        client_secrets_path: クライアントシークレットファイルのパス（デフォルト: client_secrets.json）
        search_limit: 検索対象の最新動画数（デフォルト: 50）

    Returns:
        成功時 0、失敗時 1
    """
    try:
        # OAuth2認証を実行
        credentials = get_oauth_credentials(
            token_path=token_path,
            client_secrets_path=client_secrets_path,
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"]
        )

        # YouTube APIクライアントを初期化
        youtube = build("youtube", "v3", credentials=credentials)
        logger.info("YouTube API client initialized")

        # 最新動画から {DateTime} プレースホルダーを検索
        video_info = get_latest_video_with_placeholder(youtube, limit=search_limit)

        if not video_info:
            logger.info("No action needed: no video with {DateTime} placeholder found")
            return 0

        # 公開日時をJST準拠のYYYY/MM/DD形式に変換
        date_str = convert_published_at_to_jst_date(video_info["publishedAt"])
        if not date_str:
            logger.error("Failed to convert date")
            return 1

        # タイトル内の {DateTime} を置き換え
        new_title = replace_placeholder_in_title(video_info["title"], date_str)
        logger.info(f"Replacing title: '{video_info['title']}' → '{new_title}'")

        # YouTube APIでタイトルを更新
        if update_video_title(youtube, video_info["id"], new_title):
            logger.info("Title update completed successfully")
            return 0
        else:
            logger.error("Title update failed")
            return 1

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
