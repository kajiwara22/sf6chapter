"""
Pub/Subメッセージ受信モジュール
GCPのPub/Subから新着動画情報を受信
"""

import json
import os
from collections.abc import Callable
from concurrent.futures import TimeoutError
from typing import Any

from google.cloud import pubsub_v1

from ..auth.oauth import get_oauth_credentials
from ..utils.logger import get_logger

logger = get_logger()


class PubSubSubscriber:
    """Pub/Subサブスクライバー"""

    def __init__(
        self,
        project_id: str | None = None,
        subscription_id: str | None = None,
    ):
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID")
        self.subscription_id = subscription_id or os.environ.get("PUBSUB_SUBSCRIPTION", "sf6-video-process-sub")

        if not self.project_id:
            raise ValueError("GCP_PROJECT_ID must be set")

        # OAuth2認証情報を取得
        credentials = get_oauth_credentials()

        # 認証情報を使ってPub/Subクライアントを初期化
        self.subscriber = pubsub_v1.SubscriberClient(credentials=credentials)
        self.subscription_path = self.subscriber.subscription_path(self.project_id, self.subscription_id)

    def pull_messages(
        self,
        callback: Callable[[dict[str, Any]], None],
        max_messages: int = 10,
        timeout: float = 60.0,
    ) -> None:
        """
        メッセージをPullして処理

        Args:
            callback: メッセージ処理コールバック関数
            max_messages: 一度に取得する最大メッセージ数
            timeout: タイムアウト（秒）
        """
        try:
            response = self.subscriber.pull(
                request={
                    "subscription": self.subscription_path,
                    "max_messages": max_messages,
                },
                timeout=timeout,
            )

            ack_ids = []

            for received_message in response.received_messages:
                try:
                    # メッセージデコード
                    message_data = json.loads(received_message.message.data.decode("utf-8"))

                    # コールバック実行
                    callback(message_data)

                    # 処理成功したメッセージをACK対象に追加
                    ack_ids.append(received_message.ack_id)

                except Exception:
                    logger.exception("Error processing message")
                    # エラーが発生したメッセージは再処理されるようにACKしない
                    continue

            # 処理済みメッセージをACK
            if ack_ids:
                self.subscriber.acknowledge(
                    request={
                        "subscription": self.subscription_path,
                        "ack_ids": ack_ids,
                    }
                )
                logger.info("Acknowledged %d messages", len(ack_ids))

        except TimeoutError:
            logger.info("No messages received within timeout period")
        except Exception:
            logger.exception("Error pulling messages")
            raise

    def listen_streaming(
        self,
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """
        ストリーミング方式でメッセージを受信（常駐モード）

        Args:
            callback: メッセージ処理コールバック関数
        """

        def message_callback(message: pubsub_v1.subscriber.message.Message) -> None:
            try:
                message_data = json.loads(message.data.decode("utf-8"))
                callback(message_data)
                message.ack()
            except Exception:
                logger.exception("Error processing message")
                message.nack()

        streaming_pull_future = self.subscriber.subscribe(self.subscription_path, callback=message_callback)

        logger.info("Listening for messages on %s...", self.subscription_path)

        try:
            streaming_pull_future.result()
        except KeyboardInterrupt:
            streaming_pull_future.cancel()
            logger.info("Stopped listening for messages")
