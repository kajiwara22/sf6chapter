"""バックラー統計の収集と R2 への Parquet 配置（ADR-072）

R2 レイアウト:

    stats/character_usage/{YYYYMM}_{locale}.parquet
    stats/matchup_stats/{YYYYMM}.parquet
    stats/matchup_details/{YYYYMM}.parquet
    stats/manifest.json
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from ..storage.r2_uploader import R2Uploader
from ..utils.logger import get_logger
from . import buckler_client, parquet
from .buckler_client import SUPPORTED_USAGE_LOCALES, format_data_month

logger = get_logger()

MANIFEST_KEY = "stats/manifest.json"
MANIFEST_SCHEMA = 1


def usage_key(data_month: str, locale: str) -> str:
    return f"stats/character_usage/{data_month}_{locale}.parquet"


def stats_key(data_month: str) -> str:
    return f"stats/matchup_stats/{data_month}.parquet"


def details_key(data_month: str) -> str:
    return f"stats/matchup_details/{data_month}.parquet"


@dataclass
class CollectionResult:
    """1ヶ月分の収集結果"""

    data_month: str
    usage_rows: dict[str, int] = field(default_factory=dict)
    stats_rows: int = 0
    details_rows: int = 0
    uploaded_keys: list[str] = field(default_factory=list)
    local_files: list[str] = field(default_factory=list)


class BucklerStatsCollector:
    """バックラー公開統計を取得し、Parquet として R2（またはローカル）へ配置する"""

    def __init__(
        self,
        r2_uploader: R2Uploader | None = None,
        output_dir: str | Path | None = None,
        raw_dir: str | Path | None = None,
    ):
        """
        Args:
            r2_uploader: R2 アップローダー。None の場合はローカル出力のみ
            output_dir: ローカル出力先（Parquet）
            raw_dir: 生 JSON の保存先（None なら保存しない）
        """
        self.r2_uploader = r2_uploader
        self.output_dir = Path(output_dir) if output_dir else None
        self.raw_dir = Path(raw_dir) if raw_dir else None

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def collect_month(
        self,
        year: int,
        month: int,
        locales: tuple[str, ...] = SUPPORTED_USAGE_LOCALES,
        upload: bool = True,
    ) -> CollectionResult:
        """指定した年月の統計を取得して Parquet 化する"""
        data_month = format_data_month(year, month)
        result = CollectionResult(data_month=data_month)

        # 1. 使用率（ロケール別）
        usage_tables: dict[str, list[dict[str, Any]]] = {}
        for locale in locales:
            payload = buckler_client.fetch_usage_rates(data_month, locale)
            self._save_raw(payload, f"{data_month}_{locale}_usagerate.json")
            rows = parquet.usage_rows(payload, data_month, locale)
            usage_tables[locale] = rows
            result.usage_rows[locale] = len(rows)
            logger.info("使用率を取得: %s / %s (%d行)", data_month, locale, len(rows))

        # 2. マッチアップ（dia はロケール非依存）
        payload = buckler_client.fetch_matchup_diagram(data_month)
        self._save_raw(payload, f"{data_month}_dia.json")
        stats_rows, detail_rows = parquet.matchup_rows(payload, data_month)
        result.stats_rows = len(stats_rows)
        result.details_rows = len(detail_rows)
        logger.info("マッチアップを取得: %s (stats %d行 / details %d行)", data_month, len(stats_rows), len(detail_rows))

        # 3. 出力
        for locale, rows in usage_tables.items():
            self._write(rows, parquet.USAGE_SCHEMA, usage_key(data_month, locale), upload, result)

        self._write(stats_rows, parquet.MATCHUP_STATS_SCHEMA, stats_key(data_month), upload, result)
        self._write(detail_rows, parquet.MATCHUP_DETAILS_SCHEMA, details_key(data_month), upload, result)

        # 4. manifest 更新（R2 のみ）
        if upload and self.r2_uploader:
            self._update_manifest(result, usage_tables)

        return result

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _save_raw(self, payload: dict[str, Any], filename: str) -> None:
        if self.raw_dir is None:
            return
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        logger.info("生JSONを保存: %s", path)

    def _write(
        self,
        rows: list[dict[str, Any]],
        schema: pa.Schema,
        key: str,
        upload: bool,
        result: CollectionResult,
    ) -> None:
        table = pa.Table.from_pylist(rows, schema=schema)

        if upload and self.r2_uploader:
            self._put_parquet(table, key)
            result.uploaded_keys.append(key)
            return

        if self.output_dir is None:
            raise ValueError("upload=False の場合は output_dir を指定してください")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # R2 のキー構造をそのままローカルでも再現する（同名ファイルの衝突を避ける）
        path = self.output_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="snappy")
        result.local_files.append(str(path))
        logger.info("Parquetを保存: %s (%d行)", path, len(rows))

    def _put_parquet(self, table: pa.Table, key: str) -> None:
        buffer = io.BytesIO()
        pq.write_table(table, buffer, compression="snappy")
        self.r2_uploader.s3_client.put_object(  # type: ignore[union-attr]
            Bucket=self.r2_uploader.bucket_name,  # type: ignore[union-attr]
            Key=key,
            Body=buffer.getvalue(),
            ContentType="application/octet-stream",
        )
        logger.info("R2へアップロード: %s (%d行)", key, table.num_rows)

    def _update_manifest(self, result: CollectionResult, usage_tables: dict[str, list[dict[str, Any]]]) -> None:
        existing = self._load_manifest()
        months = set(existing.get("months", []))
        months.add(result.data_month)

        counts = dict(existing.get("counts", {}))
        counts[result.data_month] = {
            "matchup_stats": result.stats_rows,
            "matchup_details": result.details_rows,
            "character_usage": {locale: len(rows) for locale, rows in usage_tables.items()},
        }

        manifest = {
            "schema": MANIFEST_SCHEMA,
            "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "latestMonth": max(months),
            "months": sorted(months),
            "locales": list(SUPPORTED_USAGE_LOCALES),
            "counts": counts,
        }

        self.r2_uploader.upload_json(manifest, MANIFEST_KEY)  # type: ignore[union-attr]
        logger.info("manifestを更新: %s (latest=%s)", MANIFEST_KEY, manifest["latestMonth"])

    def _load_manifest(self) -> dict[str, Any]:
        try:
            obj = self.r2_uploader.s3_client.get_object(  # type: ignore[union-attr]
                Bucket=self.r2_uploader.bucket_name,  # type: ignore[union-attr]
                Key=MANIFEST_KEY,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return {}
            raise
        return json.loads(obj["Body"].read().decode("utf-8"))
