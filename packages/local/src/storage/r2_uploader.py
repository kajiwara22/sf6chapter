"""
Cloudflare R2へのデータアップロード
JSON/ParquetファイルをR2にアップロード
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from ..utils.logger import get_logger

logger = get_logger()

# ADR-055: Web の OPFS キャッシュが参照するデータマニフェスト
MANIFEST_KEY = "manifest.json"
MANIFEST_SCHEMA = 1
MANIFEST_PARQUET_KEYS = (
    "matches.parquet",
    "battlelog_replays.parquet",
    "round_stats.parquet",
)


def publish_manifest(
    s3_client: Any,
    bucket_name: str,
    keys: tuple[str, ...] = MANIFEST_PARQUET_KEYS,
) -> dict[str, Any]:
    """データマニフェスト（ADR-055）を R2 に書き出す

    追跡対象の Parquet の ETag / サイズを head_object で取得し、ETag 集合から
    決定的な version を計算して `manifest.json` をアップロードする。

    Web はこの manifest を唯一の真実として OPFS キャッシュ（Parquet バイト・
    DuckDB データベース）の有効性を判定する。pipeline の全アップロードが
    完了した後に呼び出すこと。

    R2Uploader を持たない経路（修復スクリプト等）からも呼べるようにモジュール
    レベル関数としている。

    Args:
        s3_client: boto3 の S3 クライアント
        bucket_name: バケット名
        keys: 追跡対象の Parquet オブジェクトキー

    Returns:
        書き出した manifest の dict
    """
    import hashlib

    files: dict[str, dict[str, Any]] = {}
    for key in keys:
        try:
            response = s3_client.head_object(Bucket=bucket_name, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                logger.warning("Manifest: %s が見つかりません。スキップします", key)
                continue
            raise
        files[key] = {
            "etag": str(response["ETag"]).strip('"'),
            "size": int(response["ContentLength"]),
        }

    # Web 側（shared/manifest.ts）と同じアルゴリズムで version を計算する
    payload = "\n".join(f"{key}:{files[key]['etag']}" for key in sorted(files))
    version = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "version": version,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": files,
    }

    body = json.dumps(manifest, ensure_ascii=False, indent=2)
    s3_client.put_object(
        Bucket=bucket_name,
        Key=MANIFEST_KEY,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    logger.info("Uploaded manifest: version=%s files=%s", version, sorted(files))
    return manifest


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
            raise ValueError("R2 credentials must be set: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL")

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

    def _get_matches_schema(self) -> pa.Schema:
        """
        matches.parquet用のスキーマを定義
        player1/player2 の構造体に result フィールドを含める
        """
        player_struct = pa.struct(
            [
                pa.field("character", pa.string()),
                pa.field("result", pa.string(), nullable=True),  # "win" | "loss" | None
                pa.field("side", pa.string()),
            ]
        )

        return pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("videoId", pa.string()),
                pa.field("videoTitle", pa.string()),
                pa.field("videoPublishedAt", pa.string()),
                pa.field("startTime", pa.int64()),
                pa.field("player1", player_struct),
                pa.field("player2", player_struct),
                pa.field("detectedAt", pa.string()),
                pa.field("confidence", pa.float64()),
                pa.field("templateMatchScore", pa.float64()),
                pa.field("frameTimestamp", pa.int64()),
                pa.field("battlelogMatched", pa.bool_(), nullable=True),
                pa.field("battlelogConfidence", pa.string(), nullable=True),
                pa.field("battlelogReplayId", pa.string(), nullable=True),
                pa.field("battlelogTimeDiff", pa.int64(), nullable=True),
            ]
        )

    def _get_round_stats_schema(self) -> pa.Schema:
        """round_stats.parquet用のスキーマ（ADR-048/049/050/051）

        1行 = 1ラウンド x 1サイド。ラウンド単位のゲージ統計と勝敗を保持する。
        ADR-051 で driveAvg / healthAvg を削除し、勝敗・被弾・バーンアウト・SA使い残しを追加した。
        """
        return pa.schema(
            [
                pa.field("videoId", pa.string()),
                pa.field("matchId", pa.string()),
                pa.field("round", pa.int32()),
                pa.field("side", pa.string()),
                pa.field("character", pa.string(), nullable=True),
                pa.field("roundStartTime", pa.int64()),
                pa.field("roundEndTime", pa.int64()),
                pa.field("durationSec", pa.float64()),
                # ADR-051: ラウンド勝敗と勝利方法（Battlelog round_results。未マッチ時は null）
                pa.field("roundResult", pa.string(), nullable=True),
                pa.field("roundMethod", pa.string(), nullable=True),
                pa.field("driveMin", pa.float64(), nullable=True),
                pa.field("driveEnd", pa.float64(), nullable=True),
                pa.field("saMax", pa.int32(), nullable=True),
                pa.field("saUsedCount", pa.int32()),
                # ADR-051: ラウンド終了時の SA ストック（使い残しの検知）
                pa.field("saLeftAtEnd", pa.int32(), nullable=True),
                pa.field("detectionCoverage", pa.float64(), nullable=True),
                # ADR-050/051: 残体力（％、K.O. 札着の敗者は 0 に補正する）
                pa.field("healthEnd", pa.float64(), nullable=True),
                # ADR-051: 最大の変化点間減少（％、コンボ合計の近似）
                pa.field("maxHitTaken", pa.float64(), nullable=True),
                # ADR-058: 薄い黄色ゲージのピーク（＝最大コンボ被ダメージ、％）と発生相対秒
                pa.field("maxComboDamage", pa.float64(), nullable=True),
                pa.field("maxComboDamageAt", pa.float64(), nullable=True),
                # ADR-051: バーンアウト回数・累計秒（未計測時は null）
                pa.field("burnoutCount", pa.int32(), nullable=True),
                pa.field("burnoutSec", pa.float64(), nullable=True),
                # ADR-049: カウンター・パニッシュカウンター回数（未計測時は null）
                pa.field("counterCount", pa.int32(), nullable=True),
                pa.field("punishCounterCount", pa.int32(), nullable=True),
            ]
        )

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
            schema: PyArrow スキーマ（省略時は自動推論。matches.parquetの場合は明示的に定義）

        Returns:
            アップロードされたオブジェクトのキー
        """
        # matches.parquetの場合はスキーマを自動選択
        if key == "matches.parquet" and schema is None:
            schema = self._get_matches_schema()
        elif key == "round_stats.parquet" and schema is None:
            schema = self._get_round_stats_schema()

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
            schema: PyArrow スキーマ（matches.parquetの場合は自動選択）
            video_id: 置換対象のvideoId（必須）

        Returns:
            更新されたオブジェクトのキー
        """
        if not video_id:
            raise ValueError("video_id is required for update_parquet_table")

        # matches.parquetの場合はスキーマを自動選択
        if key == "matches.parquet" and schema is None:
            schema = self._get_matches_schema()
        elif key == "round_stats.parquet" and schema is None:
            schema = self._get_round_stats_schema()

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

    def publish_manifest(self, keys: tuple[str, ...] = MANIFEST_PARQUET_KEYS) -> dict[str, Any]:
        """データマニフェスト（ADR-055）を R2 に書き出す

        pipeline の全アップロードが完了した後に呼び出すこと。
        """
        return publish_manifest(self.s3_client, self.bucket_name, keys)
