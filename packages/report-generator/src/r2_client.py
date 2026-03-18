"""
Cloudflare R2からParquetファイルをダウンロード（S3互換API）
"""

import os
import tempfile

import boto3


def download_parquet(
    r2_key: str = "battlelog_replays.parquet",
    *,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    endpoint_url: str | None = None,
    bucket_name: str | None = None,
) -> str:
    """R2からParquetファイルをダウンロードし、ローカルパスを返す。

    Returns:
        ダウンロードしたファイルのローカルパス
    """
    access_key_id = access_key_id or os.environ.get("R2_ACCESS_KEY_ID")
    secret_access_key = secret_access_key or os.environ.get("R2_SECRET_ACCESS_KEY")
    endpoint = endpoint_url or os.environ.get("R2_ENDPOINT_URL")
    bucket = bucket_name or os.environ.get("R2_BUCKET_NAME", "sf6-chapter-data")

    if not all([access_key_id, secret_access_key, endpoint]):
        raise ValueError("R2 credentials must be set: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL")

    if not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"

    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )

    local_path = os.path.join(tempfile.gettempdir(), r2_key)
    s3_client.download_file(bucket, r2_key, local_path)
    return local_path
