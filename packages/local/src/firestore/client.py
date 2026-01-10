"""
Firestoreクライアント
処理済み動画の状態管理を行う
"""

import os
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from ..auth.oauth import get_oauth_credentials
from ..utils.logger import get_logger

logger = get_logger()


class FirestoreClient:
    """Firestoreクライアント"""

    # コレクション名
    COLLECTION_PROCESSED_VIDEOS = "processed_videos"

    # ステータス定義
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    def __init__(self, project_id: str | None = None):
        """
        初期化

        Args:
            project_id: GCPプロジェクトID（環境変数から取得可能）
        """
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not self.project_id:
            raise ValueError("GOOGLE_CLOUD_PROJECT must be set")

        # OAuth2認証情報を取得
        credentials = get_oauth_credentials()

        # Firestoreクライアントを初期化
        self.db = firestore.Client(project=self.project_id, credentials=credentials)

    def get_video_status(self, video_id: str) -> str | None:
        """
        動画の処理状態を取得

        Args:
            video_id: YouTube動画ID

        Returns:
            ステータス文字列、または未処理の場合はNone
        """
        try:
            doc_ref = self.db.collection(self.COLLECTION_PROCESSED_VIDEOS).document(video_id)
            doc = doc_ref.get()

            if doc.exists:
                data = doc.to_dict()
                return data.get("status")
            return None

        except Exception:
            logger.exception("Error getting video status from Firestore: %s", video_id)
            return None

    def is_completed(self, video_id: str) -> bool:
        """
        動画が処理完了済みかチェック

        Args:
            video_id: YouTube動画ID

        Returns:
            処理完了済みの場合True
        """
        status = self.get_video_status(video_id)
        return status == self.STATUS_COMPLETED

    def update_status(
        self,
        video_id: str,
        status: str,
        error_message: str | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> bool:
        """
        動画の処理状態を更新

        Args:
            video_id: YouTube動画ID
            status: 新しいステータス
            error_message: エラーメッセージ（failedステータスの場合）
            additional_data: 追加データ（任意）

        Returns:
            更新成功の場合True
        """
        try:
            doc_ref = self.db.collection(self.COLLECTION_PROCESSED_VIDEOS).document(video_id)

            update_data: dict[str, Any] = {
                "status": status,
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }

            # ステータス別の追加フィールド
            if status == self.STATUS_PROCESSING:
                update_data["processingStartedAt"] = firestore.SERVER_TIMESTAMP
            elif status == self.STATUS_COMPLETED:
                update_data["completedAt"] = firestore.SERVER_TIMESTAMP
            elif status == self.STATUS_FAILED:
                update_data["failedAt"] = firestore.SERVER_TIMESTAMP
                if error_message:
                    update_data["errorMessage"] = error_message

            # 追加データをマージ
            if additional_data:
                update_data.update(additional_data)

            # ドキュメントが存在する場合は更新、存在しない場合は作成
            doc_ref.set(update_data, merge=True)

            logger.info("Updated Firestore status: %s -> %s", video_id, status)
            return True

        except Exception:
            logger.exception("Error updating Firestore status: %s -> %s", video_id, status)
            return False

    def get_processing_stats(self) -> dict[str, int]:
        """
        処理統計情報を取得

        Returns:
            ステータス別の件数
        """
        try:
            collection_ref = self.db.collection(self.COLLECTION_PROCESSED_VIDEOS)

            stats = {
                "total": 0,
                self.STATUS_QUEUED: 0,
                self.STATUS_PROCESSING: 0,
                self.STATUS_COMPLETED: 0,
                self.STATUS_FAILED: 0,
            }

            # 全ドキュメントを取得（実運用では要最適化）
            docs = collection_ref.stream()

            for doc in docs:
                stats["total"] += 1
                data = doc.to_dict()
                status = data.get("status", "unknown")
                if status in stats:
                    stats[status] += 1

            return stats

        except Exception:
            logger.exception("Error getting processing stats from Firestore")
            return {"total": 0, "error": True}

    def get_failed_videos(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        失敗した動画リストを取得

        Args:
            limit: 取得件数上限

        Returns:
            失敗動画のリスト
        """
        try:
            collection_ref = self.db.collection(self.COLLECTION_PROCESSED_VIDEOS)

            query = collection_ref.where("status", "==", self.STATUS_FAILED).order_by(
                "failedAt", direction=firestore.Query.DESCENDING
            ).limit(limit)

            failed_videos = []
            for doc in query.stream():
                data = doc.to_dict()
                data["videoId"] = doc.id
                failed_videos.append(data)

            return failed_videos

        except Exception:
            logger.exception("Error getting failed videos from Firestore")
            return []
