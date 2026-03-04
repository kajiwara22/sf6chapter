#!/usr/bin/env python3
"""
中間ファイルから winner_side を読み込んで、parquet の result フィールドを補填する修復スクリプト

使用方法:
  python3 -m src.repair_result_from_intermediate FrOc1qYFXvc
"""

import json
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    ClientError = None

from .utils.logger import get_logger

logger = get_logger()


class ResultRepair:
    """中間ファイルから winner_side を読み込んで parquet を修復"""

    def __init__(
        self,
        intermediate_dir: str = "./intermediate",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        endpoint_url: str | None = None,
        bucket_name: str | None = None,
    ):
        """
        Args:
            intermediate_dir: 中間ファイルのルートディレクトリ
            access_key_id: R2 アクセスキーID
            secret_access_key: R2 シークレットアクセスキー
            endpoint_url: R2 エンドポイントURL
            bucket_name: バケット名
        """
        import os

        self.intermediate_dir = Path(intermediate_dir)
        self.access_key_id = access_key_id or os.environ.get("R2_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.environ.get("R2_SECRET_ACCESS_KEY")
        endpoint = endpoint_url or os.environ.get("R2_ENDPOINT_URL")
        self.bucket_name = bucket_name or os.environ.get("R2_BUCKET_NAME", "sf6-chapter-data")

        if not all([self.access_key_id, self.secret_access_key, endpoint]):
            logger.warning(
                "R2 credentials not found, will only work with local parquet files"
            )
            self.s3_client = None
        else:
            # エンドポイントURLの正規化
            if not endpoint.startswith("http"):
                endpoint = f"https://{endpoint}"

            self.s3_client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
            )

    def load_intermediate_chapters(self, video_id: str) -> dict[str, Any]:
        """
        中間ファイルから chapters.json を読み込む

        Returns:
            chapters のリスト（キーは startTime）
        """
        chapters_file = self.intermediate_dir / video_id / "chapters.json"
        if not chapters_file.exists():
            logger.warning("Intermediate file not found: %s", chapters_file)
            return {}

        with open(chapters_file) as f:
            data = json.load(f)

        # chapters リストを startTime でキー化
        result = {}
        for chapter in data.get("chapters", []):
            start_time = chapter.get("startTime")
            if start_time is not None:
                result[start_time] = chapter

        return result

    def repair_parquet_from_local(
        self, video_id: str, parquet_path: str = ".uncommit/matches.parquet"
    ) -> int:
        """
        ローカルの parquet ファイルを修復（中間ファイルから winner_side を読み込む）

        Args:
            video_id: 修復対象の videoId
            parquet_path: parquet ファイルのパス

        Returns:
            修復されたレコード数
        """
        parquet_path = Path(parquet_path)
        if not parquet_path.exists():
            logger.error("Parquet file not found: %s", parquet_path)
            return 0

        # 中間ファイルから chapters を読み込む
        chapters = self.load_intermediate_chapters(video_id)
        if not chapters:
            logger.error("No intermediate chapters found for videoId=%s", video_id)
            return 0

        logger.info("Loaded %d chapters from intermediate file", len(chapters))

        # parquet を読み込む
        table = pq.read_table(parquet_path)
        data = table.to_pylist()

        # video_id に一致するレコードを修復
        repaired_count = 0
        for record in data:
            if record.get("videoId") == video_id:
                start_time = record.get("startTime")
                if start_time in chapters:
                    chapter = chapters[start_time]
                    winner_side = chapter.get("winner_side")

                    # winner_side から result を推定
                    if winner_side:
                        if winner_side == "player1":
                            record["player1"]["result"] = "win"
                            record["player2"]["result"] = "loss"
                        elif winner_side == "player2":
                            record["player1"]["result"] = "loss"
                            record["player2"]["result"] = "win"
                        repaired_count += 1
                        logger.info(
                            "Repaired match at %ds: winner_side=%s",
                            start_time,
                            winner_side,
                        )

        logger.info("Repaired %d records", repaired_count)

        # スキーマを定義
        player_struct = pa.struct([
            pa.field("character", pa.string()),
            pa.field("result", pa.string(), nullable=True),
            pa.field("side", pa.string()),
        ])

        schema = pa.schema([
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
        ])

        # 修復後の parquet をファイルに書き込む
        import io

        buffer = io.BytesIO()
        new_table = pa.Table.from_pylist(data, schema=schema)
        pq.write_table(new_table, buffer, compression="snappy")
        buffer.seek(0)

        # ファイルに保存
        with open(parquet_path, "wb") as f:
            f.write(buffer.getvalue())

        logger.info("Saved repaired parquet: %s", parquet_path)
        return repaired_count

    def repair_parquet_from_r2(
        self, video_id: str, key: str = "matches.parquet"
    ) -> int:
        """
        R2 上の parquet ファイルを修復（中間ファイルから winner_side を読み込む）

        Args:
            video_id: 修復対象の videoId
            key: R2オブジェクトキー

        Returns:
            修復されたレコード数
        """
        if not self.s3_client:
            logger.error("R2 client not configured")
            return 0

        # 中間ファイルから chapters を読み込む
        chapters = self.load_intermediate_chapters(video_id)
        if not chapters:
            logger.error("No intermediate chapters found for videoId=%s", video_id)
            return 0

        logger.info("Loaded %d chapters from intermediate file", len(chapters))

        try:
            # R2 から parquet を取得
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            import io

            buffer = io.BytesIO(response["Body"].read())
            table = pq.read_table(buffer)
            data = table.to_pylist()

        except ClientError as e:
            logger.error("Error reading parquet from R2: %s", e)
            return 0

        # video_id に一致するレコードを修復
        repaired_count = 0
        for record in data:
            if record.get("videoId") == video_id:
                start_time = record.get("startTime")
                if start_time in chapters:
                    chapter = chapters[start_time]
                    winner_side = chapter.get("winner_side")

                    # winner_side から result を推定
                    if winner_side:
                        if winner_side == "player1":
                            record["player1"]["result"] = "win"
                            record["player2"]["result"] = "loss"
                        elif winner_side == "player2":
                            record["player1"]["result"] = "loss"
                            record["player2"]["result"] = "win"
                        repaired_count += 1
                        logger.info(
                            "Repaired match at %ds: winner_side=%s",
                            start_time,
                            winner_side,
                        )

        logger.info("Repaired %d records", repaired_count)

        # スキーマを定義
        player_struct = pa.struct([
            pa.field("character", pa.string()),
            pa.field("result", pa.string(), nullable=True),
            pa.field("side", pa.string()),
        ])

        schema = pa.schema([
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
        ])

        # 修復後の parquet をメモリに書き込む
        import io

        buffer = io.BytesIO()
        new_table = pa.Table.from_pylist(data, schema=schema)
        pq.write_table(new_table, buffer, compression="snappy")
        buffer.seek(0)

        # R2 にアップロード
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=buffer.getvalue(),
                ContentType="application/octet-stream",
            )
            logger.info("Uploaded repaired parquet to R2: %s", key)
            return repaired_count
        except ClientError as e:
            logger.error("Error uploading parquet to R2: %s", e)
            return 0


def main():
    """メイン処理"""
    if len(sys.argv) < 2:
        print("Usage: python3 src/repair_result_from_intermediate.py <video_id> [--r2]")
        print()
        print("Options:")
        print("  --r2  Upload repaired parquet to R2 instead of local file")
        sys.exit(1)

    video_id = sys.argv[1]
    use_r2 = "--r2" in sys.argv

    # 修復を実行
    repair = ResultRepair()

    if use_r2:
        logger.info("Repairing from R2...")
        repaired = repair.repair_parquet_from_r2(video_id)
    else:
        logger.info("Repairing from local parquet...")
        repaired = repair.repair_parquet_from_local(video_id)

    logger.info("Completed: repaired %d records", repaired)


if __name__ == "__main__":
    main()
