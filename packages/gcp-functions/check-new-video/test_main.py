"""
Cloud Function のユニットテスト
"""

import json
import os
from unittest.mock import Mock, patch, MagicMock
import pytest


# 環境変数をモック
os.environ["GCP_PROJECT_ID"] = "test-project"
os.environ["TARGET_CHANNEL_IDS"] = "UCtest1,UCtest2"
os.environ["PUBSUB_TOPIC"] = "test-topic"

import main


class TestGetRecentVideos:
    """get_recent_videos関数のテスト"""

    @patch("main.datetime")
    def test_get_recent_videos_success(self, mock_datetime):
        """正常系: 動画取得成功"""
        # Mock YouTube API
        mock_youtube = Mock()
        mock_search = Mock()
        mock_list = Mock()

        mock_list.execute.return_value = {
            "items": [
                {
                    "id": {"kind": "youtube#video", "videoId": "test123"},
                    "snippet": {
                        "title": "Test Video",
                        "channelTitle": "Test Channel",
                        "publishedAt": "2024-12-31T10:00:00Z",
                    },
                }
            ]
        }

        mock_search.list.return_value = mock_list
        mock_youtube.search.return_value = mock_search

        # Execute
        videos = main.get_recent_videos(mock_youtube, "UCtest", hours=1)

        # Assert
        assert len(videos) == 1
        assert videos[0]["videoId"] == "test123"
        assert videos[0]["title"] == "Test Video"

    def test_get_recent_videos_api_error(self):
        """異常系: YouTube API エラー"""
        from googleapiclient.errors import HttpError

        mock_youtube = Mock()
        mock_youtube.search().list().execute.side_effect = HttpError(
            Mock(status=403), b"API quota exceeded"
        )

        videos = main.get_recent_videos(mock_youtube, "UCtest", hours=1)

        # エラー時は空リストを返す
        assert videos == []


class TestFirestoreFunctions:
    """Firestore関連関数のテスト"""

    @patch("main.get_firestore_client")
    def test_is_video_processed_exists(self, mock_get_client):
        """正常系: 処理済み動画"""
        mock_db = Mock()
        mock_collection = Mock()
        mock_doc_ref = Mock()
        mock_doc = Mock()
        mock_doc.exists = True

        mock_doc_ref.get.return_value = mock_doc
        mock_collection.document.return_value = mock_doc_ref
        mock_db.collection.return_value = mock_collection
        mock_get_client.return_value = mock_db

        result = main.is_video_processed("test123")

        assert result is True
        mock_db.collection.assert_called_with("processed_videos")

    @patch("main.get_firestore_client")
    def test_is_video_processed_not_exists(self, mock_get_client):
        """正常系: 未処理動画"""
        mock_db = Mock()
        mock_doc_ref = Mock()
        mock_doc = Mock()
        mock_doc.exists = False

        mock_doc_ref.get.return_value = mock_doc
        mock_db.collection().document.return_value = mock_doc_ref
        mock_get_client.return_value = mock_db

        result = main.is_video_processed("test123")

        assert result is False

    @patch("main.get_firestore_client")
    def test_mark_video_as_processing_success(self, mock_get_client):
        """正常系: 動画マーク成功"""
        mock_db = Mock()
        mock_doc_ref = Mock()
        mock_doc = Mock()
        mock_doc.exists = False

        mock_doc_ref.get.return_value = mock_doc
        mock_db.collection().document.return_value = mock_doc_ref
        mock_get_client.return_value = mock_db

        video_data = {
            "videoId": "test123",
            "title": "Test",
            "channelId": "UC123",
            "channelTitle": "Test Channel",
            "publishedAt": "2024-12-31T10:00:00Z",
        }

        result = main.mark_video_as_processing("test123", video_data)

        assert result is True
        mock_doc_ref.set.assert_called_once()

    @patch("main.get_firestore_client")
    def test_mark_video_as_processing_already_exists(self, mock_get_client):
        """異常系: 既に存在する動画"""
        mock_db = Mock()
        mock_doc_ref = Mock()
        mock_doc = Mock()
        mock_doc.exists = True

        mock_doc_ref.get.return_value = mock_doc
        mock_db.collection().document.return_value = mock_doc_ref
        mock_get_client.return_value = mock_db

        video_data = {"videoId": "test123"}

        result = main.mark_video_as_processing("test123", video_data)

        assert result is False
        mock_doc_ref.set.assert_not_called()


class TestPublishToPubsub:
    """publish_to_pubsub関数のテスト"""

    @patch("main.get_pubsub_publisher")
    def test_publish_success(self, mock_get_publisher):
        """正常系: メッセージ発行成功"""
        mock_publisher = Mock()
        mock_future = Mock()
        mock_future.result.return_value = "message-id-123"

        mock_publisher.topic_path.return_value = "projects/test/topics/test-topic"
        mock_publisher.publish.return_value = mock_future
        mock_get_publisher.return_value = mock_publisher

        video_data = {"videoId": "test123", "title": "Test"}

        result = main.publish_to_pubsub(video_data)

        assert result is True
        mock_publisher.publish.assert_called_once()

    @patch("main.get_pubsub_publisher")
    def test_publish_timeout(self, mock_get_publisher):
        """異常系: タイムアウト"""
        from concurrent.futures import TimeoutError

        mock_publisher = Mock()
        mock_future = Mock()
        mock_future.result.side_effect = TimeoutError()

        mock_publisher.topic_path.return_value = "projects/test/topics/test-topic"
        mock_publisher.publish.return_value = mock_future
        mock_get_publisher.return_value = mock_publisher

        video_data = {"videoId": "test123"}

        result = main.publish_to_pubsub(video_data)

        assert result is False


class TestCheckNewVideoEndpoint:
    """check_new_video エンドポイントのテスト"""

    @patch("main.get_recent_videos")
    @patch("main.is_video_processed")
    @patch("main.mark_video_as_processing")
    @patch("main.publish_to_pubsub")
    @patch("google.auth.default")
    @patch("main.build")
    def test_check_new_video_success(
        self,
        mock_build,
        mock_default,
        mock_publish,
        mock_mark,
        mock_is_processed,
        mock_get_videos,
    ):
        """正常系: 新着動画チェック成功"""
        # Setup mocks
        mock_credentials = Mock()
        mock_default.return_value = (mock_credentials, "test-project")

        mock_youtube = Mock()
        mock_build.return_value = mock_youtube

        mock_get_videos.return_value = [
            {
                "videoId": "new123",
                "title": "New Video",
                "channelId": "UCtest1",
                "channelTitle": "Test Channel",
                "publishedAt": "2024-12-31T10:00:00Z",
            }
        ]

        mock_is_processed.return_value = False
        mock_mark.return_value = True
        mock_publish.return_value = True

        # Execute
        mock_request = Mock()
        response, status_code = main.check_new_video(mock_request)

        # Assert
        assert status_code == 200
        assert response["status"] == "success"
        assert response["stats"]["publishedVideos"] == 2  # 2 channels

    def test_check_new_video_missing_env(self):
        """異常系: 環境変数不足"""
        # 一時的に環境変数を削除
        original_project_id = os.environ.pop("GCP_PROJECT_ID", None)

        mock_request = Mock()
        response, status_code = main.check_new_video(mock_request)

        assert status_code == 500
        assert response["status"] == "error"

        # 環境変数を復元
        if original_project_id:
            os.environ["GCP_PROJECT_ID"] = original_project_id
