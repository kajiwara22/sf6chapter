"""データマニフェスト（ADR-055）のユニットテスト"""

from __future__ import annotations

import hashlib
import json

from botocore.exceptions import ClientError

from src.storage.r2_uploader import (
    MANIFEST_KEY,
    MANIFEST_SCHEMA,
    R2Uploader,
    publish_manifest,
)


class FakeS3Client:
    """head_object / put_object のみを実装したモック"""

    def __init__(self, heads: dict[str, dict]):
        self.heads = heads
        self.puts: list[dict] = []

    def head_object(self, Bucket: str, Key: str):  # noqa: N803 - boto3 のシグネチャに合わせる
        if Key not in self.heads:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "HeadObject")
        return self.heads[Key]

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        return {"ETag": '"x"'}


def _expected_version(files: dict[str, str]) -> str:
    payload = "\n".join(f"{key}:{files[key]}" for key in sorted(files))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class TestPublishManifest:
    def test_builds_version_and_uploads(self):
        client = FakeS3Client(
            {
                "matches.parquet": {"ETag": '"abc"', "ContentLength": 10},
                "battlelog_replays.parquet": {"ETag": '"def"', "ContentLength": 20},
            }
        )

        manifest = publish_manifest(client, "bucket")

        expected = {"matches.parquet": "abc", "battlelog_replays.parquet": "def"}
        assert manifest["version"] == _expected_version(expected)
        assert manifest["schema"] == MANIFEST_SCHEMA
        assert manifest["files"]["matches.parquet"] == {"etag": "abc", "size": 10}
        assert manifest["generatedAt"].endswith("Z")

        assert len(client.puts) == 1
        assert client.puts[0]["Key"] == MANIFEST_KEY
        assert json.loads(client.puts[0]["Body"]) == manifest

    def test_version_is_order_independent(self):
        keys = ["matches.parquet", "round_stats.parquet"]
        client = FakeS3Client(
            {
                "matches.parquet": {"ETag": '"aaa"', "ContentLength": 1},
                "round_stats.parquet": {"ETag": '"bbb"', "ContentLength": 2},
            }
        )
        version = publish_manifest(client, "bucket", keys=tuple(keys))["version"]
        assert version == _expected_version({"matches.parquet": "aaa", "round_stats.parquet": "bbb"})

    def test_missing_files_are_skipped(self):
        client = FakeS3Client(
            {"matches.parquet": {"ETag": '"abc"', "ContentLength": 10}}
        )

        manifest = publish_manifest(client, "bucket")

        assert set(manifest["files"].keys()) == {"matches.parquet"}

    def test_uploader_delegates_to_module_function(self):
        uploader = R2Uploader(
            access_key_id="dummy",
            secret_access_key="dummy",
            endpoint_url="https://example.invalid",
            bucket_name="bucket",
        )
        uploader.s3_client = FakeS3Client(
            {"matches.parquet": {"ETag": '"abc"', "ContentLength": 10}}
        )

        manifest = uploader.publish_manifest()

        assert manifest["files"]["matches.parquet"]["etag"] == "abc"
        assert uploader.s3_client.puts[0]["Key"] == MANIFEST_KEY
