"""
Cloudflare R2へのデータアップロード
JSON/ParquetファイルをR2にアップロード
"""

import json
import os
from typing import Any

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from ..utils.logger import get_logger

logger = get_logger()


class R2Uploader:
    """Cloudflare R2アップローダー（S3互換API）"""

    def __init__(
        self,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        endpoint_url: str | None = None,
        bucket_name: str | None = None,
    ):
        """
        Args:
            access_key_id: R2 アクセスキーID（バケット専用APIトークンのID）
            secret_access_key: R2 シークレットアクセスキー（トークンのSHA-256ハッシュ）
            endpoint_url: R2 エンドポイントURL（例: {account_id}.r2.cloudflarestorage.com）
            bucket_name: バケット名
        """
        self.access_key_id = access_key_id or os.environ.get("R2_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.environ.get("R2_SECRET_ACCESS_KEY")
        endpoint = endpoint_url or os.environ.get("R2_ENDPOINT_URL")
        self.bucket_name = bucket_name or os.environ.get("R2_BUCKET_NAME", "sf6-chapter-data")

        if not all([self.access_key_id, self.secret_access_key, endpoint]):
            raise ValueError(
                "R2 credentials must be set: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL"
            )

        # エンドポイントURLの正規化（https://プレフィックスを追加）
        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"

        # S3互換クライアント
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name="auto",  # R2では "auto" を使用
        )

    def upload_json(
        self,
        data: dict[str, Any] | list[dict[str, Any]],
        key: str,
    ) -> str:
        """
        JSON データをアップロード

        Args:
            data: アップロードするデータ
            key: R2オブジェクトキー（例: "videos/ZHA10O69Eew.json"）

        Returns:
            アップロードされたオブジェクトのキー
        """
        json_str = json.dumps(data, ensure_ascii=False, indent=2)

        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json_str.encode("utf-8"),
                ContentType="application/json",
            )
            logger.info("Uploaded JSON: %s", key)
            return key
        except ClientError:
            logger.exception("Error uploading JSON to R2: %s", key)
            raise

    def upload_parquet(
        self,
        data: list[dict[str, Any]],
        key: str,
        schema: pa.Schema | None = None,
    ) -> str:
        """
        Parquet ファイルをアップロード

        Args:
            data: アップロードするデータ（辞書のリスト）
            key: R2オブジェクトキー（例: "matches.parquet"）
            schema: PyArrow スキーマ（省略時は自動推論）

        Returns:
            アップロードされたオブジェクトのキー
        """
        # Parquetファイル作成
        table = pa.Table.from_pylist(data, schema=schema) if schema else pa.Table.from_pylist(data)

        # メモリ上にParquetを書き込み
        import io

        buffer = io.BytesIO()
        pq.write_table(table, buffer, compression="snappy")
        buffer.seek(0)

        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=buffer.getvalue(),
                ContentType="application/octet-stream",
            )
            logger.info("Uploaded Parquet: %s", key)
            return key
        except ClientError:
            logger.exception("Error uploading Parquet to R2: %s", key)
            raise

    def append_to_json_array(
        self,
        new_data: dict[str, Any],
        key: str,
    ) -> str:
        """
        既存のJSON配列に新しいデータを追加

        Args:
            new_data: 追加するデータ
            key: R2オブジェクトキー

        Returns:
            更新されたオブジェクトのキー
        """
        try:
            # 既存データを取得
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            existing_data = json.loads(response["Body"].read().decode("utf-8"))

            # 配列でない場合は配列化
            if not isinstance(existing_data, list):
                existing_data = [existing_data]

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                # ファイルが存在しない場合は新規作成
                existing_data = []
            else:
                raise

        # 新しいデータを追加
        existing_data.append(new_data)

        # アップロード
        return self.upload_json(existing_data, key)

    def update_parquet_table(
        self,
        new_data: list[dict[str, Any]],
        key: str,
        schema: pa.Schema | None = None,
        video_id: str | None = None,
    ) -> str:
        """
        既存のParquetテーブルを更新（videoId単位で置換）

        指定されたvideoIdに紐づく既存レコードをすべて削除してから、
        新しいデータを追加します。これにより、中間ファイルで削除された
        レコードがParquetに残らなくなります。

        Args:
            new_data: 追加するデータ
            key: R2オブジェクトキー
            schema: PyArrow スキーマ
            video_id: 置換対象のvideoId（必須）

        Returns:
            更新されたオブジェクトのキー
        """
        if not video_id:
            raise ValueError("video_id is required for update_parquet_table")

        try:
            # 既存データを取得
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            import io

            buffer = io.BytesIO(response["Body"].read())
            existing_table = pq.read_table(buffer)
            existing_data = existing_table.to_pylist()

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                # ファイルが存在しない場合は新規作成
                existing_data = []
            else:
                raise

        # 指定されたvideoIdのレコードをすべて削除
        filtered_data = [item for item in existing_data if item.get("videoId") != video_id]
        deleted_count = len(existing_data) - len(filtered_data)
        if deleted_count > 0:
            logger.info(
                "Deleted %d existing records for videoId=%s from %s",
                deleted_count,
                video_id,
                key,
            )

        # 新しいデータを追加
        merged_data = filtered_data + new_data
        logger.info(
            "Adding %d new records for videoId=%s to %s",
            len(new_data),
            video_id,
            key,
        )

        # アップロード
        return self.upload_parquet(merged_data, key, schema)
