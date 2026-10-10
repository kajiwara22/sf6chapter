#!/usr/bin/env python3
"""
ドライブゲージ・SAゲージ計測の再処理 CLI（ADR-048）

既存動画（download/ に残っているもの）からラウンド単位のゲージ変動を再計測する。
本線パイプラインは動画検出時に同じ計測を相乗りで実行するため、
この CLI はバックフィル用途（決定8）で使用する。

Usage:
    # 検出済みの中間ファイル（intermediate/{video_id}/detection_summary.json）を使う
    uv run python scripts/analyze_gauges.py --video-id DSgD_bQhxp0

    # 試合開始時刻を直接指定する
    uv run python scripts/analyze_gauges.py --video-path "./download/xxx.mp4" --match-starts "21,128,278"

    # 最初の300秒だけ計測する（動作確認用）
    uv run python scripts/analyze_gauges.py --video-id DSgD_bQhxp0 --max-seconds 300
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import cv2

from src.detection import GaugeAnalyzer, load_detection_params
from src.detection.gauge import build_round_stats_rows
from src.utils.logger import setup_logger

logger = setup_logger()


def resolve_video_path(video_id: str | None, video_path: str | None, download_dir: Path) -> Path:
    """動画ファイルのパスを解決する（download/ の [videoId].mp4 を検索）"""
    if video_path:
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {path}")
        return path

    if not video_id:
        raise ValueError("--video-id または --video-path を指定してください")

    candidates = [p for p in download_dir.glob("*.mp4") if f"[{video_id}]" in p.name]
    if not candidates:
        raise FileNotFoundError(f"Video file for {video_id} not found in {download_dir}")
    return sorted(candidates)[-1]


def load_match_starts(video_id: str | None, intermediate_dir: Path, override: str | None) -> list[float]:
    """試合開始時刻を解決する（CLI 引数 > 中間ファイル）"""
    if override:
        return sorted(float(value) for value in override.split(",") if value.strip())

    if not video_id:
        raise ValueError("試合開始時刻を取得するには --video-id が必要です（または --match-starts を指定）")

    summary_path = intermediate_dir / video_id / "detection_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(
            f"detection_summary.json が見つかりません: {summary_path}\n"
            "  --match-starts で試合開始時刻を指定するか、先に動画検出を実行してください"
        )

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    return sorted(float(detection["timestamp"]) for detection in summary.get("detections", []))


def analyze_video(
    video_path: Path,
    match_starts: list[float],
    params,
    app_root: Path,
    max_seconds: float | None = None,
) -> tuple[GaugeAnalyzer, float, float]:
    """動画を1回デコードしてゲージを計測する

    Returns:
        (analyzer, 動画長[秒], 処理時間[秒])
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if total_frames > 0 else 0.0

    analyzer = GaugeAnalyzer(params, app_root)
    frame_count = 0
    started = time.time()
    limit_frames = int(max_seconds * fps) if max_seconds else None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            analyzer.feed(frame, frame_count / fps)
            frame_count += 1
            if frame_count % int(fps * 60) == 0:
                logger.info(
                    "Progress: %.1f%% (%.0fs / %.0fs)",
                    100 * frame_count / total_frames if total_frames else 0,
                    frame_count / fps,
                    duration,
                )
            if limit_frames is not None and frame_count >= limit_frames:
                break
    finally:
        cap.release()

    elapsed = time.time() - started
    video_end = min(duration, max_seconds) if max_seconds else duration
    return analyzer, video_end, elapsed


def print_summary(gauge_result: dict[str, Any], match_starts: list[float]) -> None:
    """計測結果のサマリーを表示する"""
    logger.info("=" * 60)
    logger.info("Gauge analysis summary")
    logger.info("=" * 60)
    logger.info("ROUND banners: %s", [round(t, 2) for t in gauge_result.get("roundBannerTimes", [])])
    for match_id, match_data in (gauge_result.get("matches") or {}).items():
        logger.info("match %s (%d rounds)", match_id, len(match_data.get("rounds", [])))
        for round_data in match_data.get("rounds", []):
            for side in ("player1", "player2"):
                payload = round_data.get(side) or {}
                drive = payload.get("drive") or []
                sa = payload.get("sa") or []
                logger.info(
                    "  R%d %-8s drive_events=%-3d sa_events=%-3d burnout=%-2d ca=%-2d coverage=%.2f",
                    round_data.get("round", 0),
                    side,
                    len(drive),
                    len(sa),
                    len(payload.get("driveBurnout") or []),
                    len(payload.get("saCriticalArt") or []),
                    float(payload.get("coverage") or 0.0),
                )
    logger.info("match starts: %s", [round(t, 2) for t in match_starts])


def main() -> None:
    parser = argparse.ArgumentParser(description="ドライブゲージ・SAゲージの再計測（ADR-048）")
    parser.add_argument("--video-id", help="YouTube 動画ID")
    parser.add_argument("--video-path", help="動画ファイルのパス（省略時は download/ から解決）")
    parser.add_argument("--match-starts", help="試合開始時刻（秒）のカンマ区切り。省略時は中間ファイルから取得")
    parser.add_argument("--output-dir", help="出力先ディレクトリ（既定: intermediate/{video_id}/gauges）")
    parser.add_argument("--download-dir", default="./download", help="動画探索ディレクトリ")
    parser.add_argument("--intermediate-dir", default="./intermediate", help="中間ファイルディレクトリ")
    parser.add_argument("--profile", default="production", help="検出パラメータのプロファイル")
    parser.add_argument("--max-seconds", type=float, help="先頭から計測する秒数（動作確認用）")
    parser.add_argument("--no-csv", action="store_true", help="時系列CSVを出力しない")
    parser.add_argument("--no-snapshots", action="store_true", help="ROIクロップ画像を出力しない")
    args = parser.parse_args()

    app_root = project_root
    intermediate_dir = Path(args.intermediate_dir)
    video_path = resolve_video_path(args.video_id, args.video_path, Path(args.download_dir))
    logger.info("Video: %s", video_path)

    if not args.video_id:
        # ファイル名の [videoId] から推定する
        stem = video_path.stem
        if "[" in stem and "]" in stem:
            args.video_id = stem[stem.index("[") + 1 : stem.index("]")]
    logger.info("videoId: %s", args.video_id)

    match_starts = load_match_starts(args.video_id, intermediate_dir, args.match_starts)
    if not match_starts:
        raise ValueError("試合開始時刻が取得できませんでした")
    logger.info("Match starts: %s", match_starts)

    params = load_detection_params(profile=args.profile)
    if params.gauge_analysis is None or not params.gauge_analysis.enabled:
        raise ValueError("config/detection_params.json の gauge_analysis が無効です")

    analyzer, video_end, elapsed = analyze_video(
        video_path, match_starts, params.gauge_analysis, app_root, args.max_seconds
    )

    matches = [(f"{args.video_id}_{int(start)}", start) for start in match_starts]
    gauge_result = analyzer.build(matches, video_end=video_end)
    gauge_result["videoId"] = args.video_id

    output_dir = (
        Path(args.output_dir) if args.output_dir else intermediate_dir / (args.video_id or "unknown") / "gauges"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "gauges.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(gauge_result, f, ensure_ascii=False, indent=2)
    logger.info("✅ Saved gauge analysis: %s", json_path)

    if not args.no_csv:
        analyzer.write_samples_csv(output_dir / "gauges_samples.csv")
    if not args.no_snapshots:
        analyzer.save_snapshots(output_dir / "roi")

    stats_rows = build_round_stats_rows(
        gauge_result,
        [{"id": match_id, "videoId": args.video_id, "player1": {}, "player2": {}} for match_id, _ in matches],
    )
    stats_path = output_dir / "round_stats_preview.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats_rows, f, ensure_ascii=False, indent=2)
    logger.info("✅ Saved round stats preview: %s", stats_path)

    print_summary(gauge_result, match_starts)
    logger.info("Done in %.1fs (video %.0fs)", elapsed, video_end)


if __name__ == "__main__":
    main()
