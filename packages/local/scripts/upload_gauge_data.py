#!/usr/bin/env python3
"""round_stats / gauges の R2 反映 CLI（ADR-048/049/050/051）

`intermediate/{videoId}/` に出力済みの計測結果を R2 に反映する。

アップロードするもの:
- `gauges/{matchId}.json`        … Web 詳細パネル用の変化点（ドライブ・SA・体力）
- `round_stats.parquet`          … 集計（1行=1ラウンド×1サイド。勝敗・ゲージ・体力・バーンアウト・カウンター列を含む）
- `config/character_health.json` … 実 HP 計算用の最大体力表（単一ソース）

入力（`analyze_counters.py` / `analyze_gauges.py` / 本線パイプラインが出力）:
- `intermediate/{videoId}/gauges/gauges.json`
- `intermediate/{videoId}/counters/counters.json`（任意。無い場合 counterCount は null）
- `intermediate/{videoId}/matches.json`（キャラクター名）
- `intermediate/{videoId}/chapters.json`（任意。round_count の突合に使う）

ラウンド数の突合（ADR-048 決定4）は、R2 の `videos/{videoId}.json`（matchId → replay_id）と
`battlelog_replays.parquet`（replay_id → round_results）から復元する。

Usage:
    # 1 本を反映
    uv run python scripts/upload_gauge_data.py --video-id DSgD_bQhxp0

    # 内容を確認するだけ（R2 へは書き込まない）
    uv run python scripts/upload_gauge_data.py --video-id DSgD_bQhxp0 --dry-run

    # intermediate/ に gauges/gauges.json がある動画をすべて反映
    uv run python scripts/upload_gauge_data.py --all
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pyarrow.parquet as pq

from src.character import default_health_path, load_character_health
from src.detection.gauge import build_round_stats_rows
from src.storage.r2_uploader import R2Uploader
from src.utils.logger import setup_logger

logger = setup_logger()


def load_env_file(path: Path) -> None:
    """KEY=VALUE 形式の .env を読み、未設定の環境変数だけ補完する

    既存の環境変数を上書きしない。値の前後のクォートは取り除く。
    """
    if not path.exists():
        return
    loaded = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    logger.info("[Env] %s から %d 件の環境変数を読み込みました", path, loaded)


def parse_round_results(value: Any) -> list[int]:
    """Battlelog の round_results（`'[0, 0]'` 形式の文字列）を int のリストにする"""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    if isinstance(value, list):
        return [int(item) for item in value]
    return []


def parse_round_count(round_results: Any) -> int | None:
    """Battlelog の round_results からラウンド数を返す"""
    results = parse_round_results(round_results)
    return len(results) if results else None


def _get_bytes(s3_client: Any, bucket: str, key: str) -> bytes | None:
    """R2 からオブジェクトを取得する（存在しない場合は None）"""
    from botocore.exceptions import ClientError

    try:
        return s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            return None
        raise


class BattlelogResolver:
    """Battlelog のラウンド結果（勝敗・勝利方法・ラウンド数）を matchId 単位で解決する（ADR-048/051）"""

    def __init__(self, s3_client: Any, bucket: str):
        self.s3_client = s3_client
        self.bucket = bucket
        self._battlelog_cache: dict[str, dict[str, Any]] | None = None

    def _replay_data(self) -> dict[str, dict[str, Any]]:
        """battlelog_replays.parquet を replay_id → ラウンド結果 の辞書にする（初回のみ取得）"""
        if self._battlelog_cache is not None:
            return self._battlelog_cache

        data: dict[str, dict[str, Any]] = {}
        raw = _get_bytes(self.s3_client, self.bucket, "battlelog_replays.parquet")
        if raw is None:
            logger.warning("[Battlelog] battlelog_replays.parquet が R2 にありません（突合をスキップ）")
            self._battlelog_cache = data
            return data

        table = pq.read_table(io.BytesIO(raw))
        for row in table.to_pylist():
            replay_id = row.get("replay_id")
            if not replay_id:
                continue
            player1 = parse_round_results(row.get("p1_round_results"))
            player2 = parse_round_results(row.get("p2_round_results"))
            data[replay_id] = {
                "roundCount": max(len(player1), len(player2)) if (player1 or player2) else None,
                "player1": player1,
                "player2": player2,
            }
        self._battlelog_cache = data
        return data

    def resolve(self, video_id: str) -> dict[str, dict[str, Any]]:
        """videoId の matchId → Battlelog ラウンド結果を返す（取得できない場合は空辞書）"""
        raw = _get_bytes(self.s3_client, self.bucket, f"videos/{video_id}.json")
        if raw is None:
            logger.warning("[Battlelog] videos/%s.json が R2 にありません（突合をスキップ）", video_id)
            return {}

        try:
            video_data = json.loads(raw)
        except ValueError:
            logger.warning("[Battlelog] videos/%s.json の解析に失敗しました", video_id)
            return {}

        replay_data = self._replay_data()
        resolved: dict[str, dict[str, Any]] = {}
        for chapter in video_data.get("chapters", []):
            match_id = chapter.get("matchId")
            if not match_id:
                continue
            info = replay_data.get(chapter.get("replay_id") or "") or {}
            resolved[match_id] = {
                "roundCount": info.get("roundCount"),
                "player1": info.get("player1", []),
                "player2": info.get("player2", []),
                # ADR-051: 試合の勝敗をゲージ詳細 JSON にも保持する
                "player1Result": chapter.get("player1_result"),
                "player2Result": chapter.get("player2_result"),
            }
        return resolved


def apply_round_count_flags(
    gauge_result: dict[str, Any],
    round_counts: dict[str, int | None],
) -> None:
    """gauges JSON に検出ラウンド数と Battlelog ラウンド数の突合結果を付与する（main.py と同じ形式）"""
    for match_id, match_gauges in (gauge_result.get("matches") or {}).items():
        detected = len(match_gauges.get("rounds", []))
        expected = round_counts.get(match_id)
        match_gauges["detectedRoundCount"] = detected
        match_gauges["battlelogRoundCount"] = expected
        match_gauges["roundCountMatch"] = None if expected is None else detected == expected
        if expected is not None and detected != expected:
            logger.warning(
                "[Gauge] round count mismatch for %s: detected=%d battlelog=%d",
                match_id,
                detected,
                expected,
            )


def load_json(path: Path) -> Any:
    """JSON を読み込む（存在しない場合は None）"""
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_video_rows(
    video_id: str,
    intermediate_dir: Path,
    battlelog_info: dict[str, dict[str, Any]],
    health_warn: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """1 動画分の gauges JSON と round_stats 行を組み立てる

    Returns:
        (gauges JSON（videoId 付き matchId → データ）, round_stats の行リスト)
    """
    video_dir = intermediate_dir / video_id
    gauge_result = load_json(video_dir / "gauges" / "gauges.json")
    if not gauge_result:
        raise FileNotFoundError(f"gauges.json がありません: {video_dir / 'gauges' / 'gauges.json'}")

    matches = load_json(video_dir / "matches.json") or []
    counter_result = load_json(video_dir / "counters" / "counters.json")

    round_counts = {match_id: info.get("roundCount") for match_id, info in battlelog_info.items()}
    apply_round_count_flags(gauge_result, round_counts)

    # ADR-051: 試合の勝敗をゲージ詳細 JSON に付与する
    for match_id, match_gauges in (gauge_result.get("matches") or {}).items():
        info = battlelog_info.get(match_id) or {}
        match_gauges["player1Result"] = info.get("player1Result")
        match_gauges["player2Result"] = info.get("player2Result")

    if health_warn:
        health_table = load_character_health(str(default_health_path(project_root)))
        characters = {
            (match.get(side) or {}).get("character")
            for match in matches
            for side in ("player1", "player2")
        }
        health_table.warn_unknown(characters)

    round_results_by_match = {
        match_id: {"player1": info.get("player1") or [], "player2": info.get("player2") or []}
        for match_id, info in battlelog_info.items()
        if info.get("player1") or info.get("player2")
    }
    stats_rows = build_round_stats_rows(
        gauge_result,
        matches,
        counter_result=counter_result,
        round_results_by_match=round_results_by_match,
    )

    # matches.json に無い試合（検出が分割されたケース。ADR-048 の既知制約）は videoId が null に
    # なるため、対象動画の videoId で補完する（null のままだと再処理時に置換されず残留する）
    missing_meta = sorted({row["matchId"] for row in stats_rows if not row.get("videoId")})
    if missing_meta:
        logger.warning(
            "[Gauge] matches.json に無い試合の round_stats を videoId=%s として補完します: %s",
            video_id,
            missing_meta,
        )
        for row in stats_rows:
            if not row.get("videoId"):
                row["videoId"] = video_id

    gauges_by_match = {
        match_id: {"videoId": video_id, **match_gauges}
        for match_id, match_gauges in (gauge_result.get("matches") or {}).items()
    }
    return gauges_by_match, stats_rows


def collect_video_ids(intermediate_dir: Path) -> list[str]:
    """intermediate/ 配下で gauges/gauges.json を持つ動画 ID を列挙する"""
    return sorted(
        path.parent.parent.name
        for path in intermediate_dir.glob("*/gauges/gauges.json")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="round_stats / gauges の R2 反映（ADR-048/049/050）")
    parser.add_argument("--video-id", action="append", default=[], help="対象の YouTube 動画ID（複数指定可）")
    parser.add_argument("--all", action="store_true", help="intermediate/ に gauges.json がある動画をすべて反映")
    parser.add_argument("--intermediate-dir", default="./intermediate", help="中間ファイルディレクトリ")
    parser.add_argument("--env-file", default="./.env", help="R2 認証情報を読み込む .env（未設定時のみ補完）")
    parser.add_argument("--dry-run", action="store_true", help="R2 へ書き込まず、内容だけ表示する")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))

    intermediate_dir = Path(args.intermediate_dir)
    video_ids = list(args.video_id)
    if args.all:
        discovered = collect_video_ids(intermediate_dir)
        video_ids.extend(vid for vid in discovered if vid not in video_ids)
    if not video_ids:
        parser.error("--video-id または --all を指定してください")

    uploader = R2Uploader()
    resolver = BattlelogResolver(uploader.s3_client, uploader.bucket_name)
    logger.info("[R2] bucket=%s videos=%s dry_run=%s", uploader.bucket_name, video_ids, args.dry_run)

    total_rows = 0
    for video_id in video_ids:
        battlelog_info = resolver.resolve(video_id)
        gauges_by_match, stats_rows = build_video_rows(video_id, intermediate_dir, battlelog_info)
        total_rows += len(stats_rows)

        matched = sum(1 for gauges in gauges_by_match.values() if gauges.get("roundCountMatch") is True)
        mismatched = sum(1 for gauges in gauges_by_match.values() if gauges.get("roundCountMatch") is False)
        logger.info(
            "[Gauge] videoId=%s matches=%d round_stats=%d round_count(match/mismatch/unknown)=%d/%d/%d",
            video_id,
            len(gauges_by_match),
            len(stats_rows),
            matched,
            mismatched,
            len(gauges_by_match) - matched - mismatched,
        )

        if args.dry_run:
            logger.info("[DryRun] gauges アップロード予定: %d 件", len(gauges_by_match))
            if stats_rows:
                logger.info("[DryRun] round_stats 行: %d 件（先頭: %s）", len(stats_rows), stats_rows[0])
            continue

        for match_id, gauges in gauges_by_match.items():
            uploader.upload_json(gauges, f"gauges/{match_id}.json")

        health_path = default_health_path(project_root)
        if health_path.exists():
            with open(health_path, encoding="utf-8") as f:
                uploader.upload_json(json.load(f), "config/character_health.json")
        else:
            logger.warning("[Health] 最大体力表が見つかりません: %s", health_path)

        if stats_rows:
            uploader.update_parquet_table(stats_rows, "round_stats.parquet", video_id=video_id)
        else:
            logger.warning("[Gauge] round_stats の行が 0 件のため round_stats.parquet は更新しません: %s", video_id)

    logger.info("[Done] videos=%d round_stats rows=%d dry_run=%s", len(video_ids), total_rows, args.dry_run)


if __name__ == "__main__":
    main()
