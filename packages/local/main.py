#!/usr/bin/env python3
"""
SF6 Chapter - メイン処理スクリプト
Pub/Subから新着動画を受信し、チャプター生成・アップロードを実行
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートのconfigディレクトリをパスに追加
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.character import CharacterRecognizer
from src.detection import MatchDetection, TemplateMatcher
from src.pubsub import PubSubSubscriber
from src.storage import R2Uploader
from src.video import VideoDownloader
from src.youtube import YouTubeChapterUpdater


class SF6ChapterProcessor:
    """SF6チャプター処理のメインクラス"""

    def __init__(self):
        """初期化"""
        # 設定
        self.template_path = os.environ.get("TEMPLATE_PATH", "./template/round1.png")
        self.download_dir = os.environ.get("DOWNLOAD_DIR", "./download")
        self.crop_region = (339, 886, 1748, 980)  # キャラクター名表示領域

        # 除外テンプレート（Round 2, Final Round）
        self.reject_templates = [
            os.environ.get("REJECT_TEMPLATE_ROUND2", "./template/round2.png"),
            os.environ.get("REJECT_TEMPLATE_FINAL", "./template/final_round.png"),
        ]

        # モジュール初期化
        self.subscriber = PubSubSubscriber()
        self.downloader = VideoDownloader(download_dir=self.download_dir)
        # Round 1表示領域（画面中央上部）
        self.round1_search_region = (575, 333, 1500, 700)

        self.matcher = TemplateMatcher(
            template_path=self.template_path,
            threshold=0.32,
            min_interval_sec=2.0,
            reject_templates=self.reject_templates,
            reject_threshold=0.35,
            search_region=self.round1_search_region,
            post_check_frames=10,  # 検出後10フレームをチェック
            post_check_reject_limit=2,  # 2回以上除外マッチがあれば誤検知
        )
        self.recognizer = CharacterRecognizer(aliases_path=str(project_root / "config" / "character_aliases.json"))
        self.youtube_updater = YouTubeChapterUpdater()
        self.r2_uploader = R2Uploader()

    def process_video(self, message_data: dict[str, Any]) -> None:
        """
        動画処理のメインフロー

        Args:
            message_data: Pub/Subメッセージデータ
        """
        video_id = message_data.get("videoId")
        if not video_id:
            print("Error: videoId not found in message")
            return

        print(f"\n{'=' * 60}")
        print(f"Processing video: {video_id}")
        print(f"Title: {message_data.get('title', 'N/A')}")
        print(f"{'=' * 60}\n")

        try:
            # 1. 動画ダウンロード
            print("[1/6] Downloading video...")
            video_path = self.downloader.download(video_id)
            print(f"Downloaded: {video_path}")

            # 2. テンプレートマッチングで対戦シーンを検出
            print("[2/6] Detecting match scenes...")
            detections = self.matcher.detect_matches(
                video_path=video_path,
                crop_region=self.crop_region,
            )
            print(f"Found {len(detections)} matches")

            if not detections:
                print("No matches found, skipping video")
                return

            # 3. Gemini APIでキャラクター認識
            print("[3/6] Recognizing characters...")
            matches: list[dict[str, Any]] = []
            chapters: list[dict[str, Any]] = []

            for i, detection in enumerate(detections, 1):
                try:
                    normalized, raw = self.recognizer.recognize_from_frame(detection.frame)

                    match_id = f"{video_id}_{int(detection.timestamp)}"
                    match_data = {
                        "id": match_id,
                        "videoId": video_id,
                        "startTime": int(detection.timestamp),
                        "player1": {
                            "character": normalized.get("1p", "Unknown"),
                            "characterRaw": raw.get("1p", ""),
                            "side": "left",
                        },
                        "player2": {
                            "character": normalized.get("2p", "Unknown"),
                            "characterRaw": raw.get("2p", ""),
                            "side": "right",
                        },
                        "detectedAt": datetime.utcnow().isoformat() + "Z",
                        "confidence": detection.confidence,
                        "templateMatchScore": detection.confidence,
                        "frameTimestamp": detection.frame_number,
                    }
                    matches.append(match_data)

                    # チャプター情報
                    chapter = {
                        "startTime": int(detection.timestamp),
                        "title": f"第{i:02d}戦 {normalized.get('1p')} VS {normalized.get('2p')}",
                        "matchId": match_id,
                    }
                    chapters.append(chapter)

                    print(f"  {chapter['title']} at {detection.timestamp:.1f}s")

                except Exception as e:
                    print(f"Error recognizing characters for match {i}: {e}")
                    continue

            # 4. YouTube チャプター更新
            print("[4/6] Updating YouTube chapters...")
            self.youtube_updater.update_video_description(video_id, chapters)

            # 5. JSONデータをR2にアップロード
            print("[5/6] Uploading JSON data to R2...")
            video_data = {
                "videoId": video_id,
                "title": message_data.get("title", ""),
                "channelId": message_data.get("channelId", ""),
                "channelTitle": message_data.get("channelTitle", ""),
                "publishedAt": message_data.get("publishedAt", ""),
                "processedAt": datetime.utcnow().isoformat() + "Z",
                "chapters": chapters,
                "detectionStats": {
                    "totalFrames": 0,  # TODO: 実際のフレーム数
                    "matchedFrames": len(detections),
                },
            }

            # 動画メタデータをアップロード
            self.r2_uploader.upload_json(video_data, f"videos/{video_id}.json")

            # 対戦データを個別にアップロード
            for match in matches:
                self.r2_uploader.upload_json(match, f"matches/{match['id']}.json")

            # 6. Parquetファイルを更新
            print("[6/6] Updating Parquet files...")
            self.r2_uploader.update_parquet_table([video_data], "videos.parquet")
            self.r2_uploader.update_parquet_table(matches, "matches.parquet")

            print(f"\n✅ Successfully processed video: {video_id}")
            print(f"   - Detected {len(matches)} matches")
            print(f"   - Created {len(chapters)} chapters")
            print("   - Uploaded to R2")

        except Exception as e:
            print(f"\n❌ Error processing video {video_id}: {e}")
            import traceback

            traceback.print_exc()

    def run_once(self) -> None:
        """1回だけPub/SubからPullして処理"""
        print("Pulling messages from Pub/Sub...")
        self.subscriber.pull_messages(
            callback=self.process_video,
            max_messages=10,
            timeout=30.0,
        )

    def run_forever(self) -> None:
        """常駐モードで実行"""
        print("Starting streaming mode...")
        self.subscriber.listen_streaming(callback=self.process_video)


def test_download(video_id: str) -> str:
    """動画ダウンロードのテスト（既存ファイルがあれば再利用）"""
    print(f"[TEST] Downloading video: {video_id}")
    downloader = VideoDownloader(download_dir="./download")
    video_path = downloader.download(video_id, skip_if_exists=True)
    print(f"✅ Downloaded: {video_path}")
    return video_path


def test_detection(video_path: str) -> list[MatchDetection]:
    """対戦シーン検出のテスト"""
    print(f"[TEST] Detecting matches in: {video_path}")
    template_path = os.environ.get("TEMPLATE_PATH", "./template/round1.png")

    # Round 1表示領域（画面中央上部）
    round1_search_region = (575, 333, 1500, 800)

    reject_templates = [
        os.environ.get("REJECT_TEMPLATE_ROUND2", "./template/round2.png"),
        os.environ.get("REJECT_TEMPLATE_FINAL", "./template/final_round.png"),
    ]
    matcher = TemplateMatcher(
        template_path=template_path,
        threshold=0.32,
        min_interval_sec=2.0,
        reject_templates=reject_templates,
        reject_threshold=0.35,
        search_region=round1_search_region,
        post_check_frames=10,  # 検出後10フレームをチェック
        post_check_reject_limit=2,  # 2回以上除外マッチがあれば誤検知
    )
    crop_region = (339, 886, 1748, 980)
    detections = matcher.detect_matches(video_path=video_path, crop_region=crop_region)
    print(f"✅ Found {len(detections)} matches")
    for i, det in enumerate(detections, 1):
        print(f"   {i}. {det.timestamp:.1f}s (confidence: {det.confidence:.3f})")
    return detections


def test_recognition(detections: list[MatchDetection]) -> list[tuple[dict[str, str], dict[str, str]]]:
    """キャラクター認識のテスト"""
    print(f"[TEST] Recognizing characters from {len(detections)} frames")
    project_root = Path(__file__).parent.parent.parent
    recognizer = CharacterRecognizer(aliases_path=str(project_root / "config" / "character_aliases.json"))

    results = []
    for i, detection in enumerate(detections, 1):
        print(f"   Processing match {i}/{len(detections)}...")
        normalized, raw = recognizer.recognize_from_frame(detection.frame)
        results.append((normalized, raw))
        print(f"   ✅ {normalized.get('1p')} VS {normalized.get('2p')}")
        print(f"      (raw: {raw.get('1p')} vs {raw.get('2p')})")

    return results


def save_chapters_to_file(
    video_id: str, detections: list[MatchDetection], results: list[tuple[dict[str, str], dict[str, str]]]
) -> str:
    """
    チャプターデータを中間ファイルに保存

    Args:
        video_id: YouTube動画ID
        detections: 検出結果リスト
        results: 認識結果リスト

    Returns:
        保存したファイルのパス
    """
    import json

    chapters = []
    for i, (detection, (normalized, raw)) in enumerate(zip(detections, results, strict=False), 1):
        chapter = {
            "startTime": int(detection.timestamp),
            "title": f"第{i:02d}戦 {normalized.get('1p')} VS {normalized.get('2p')}",
            "normalized": normalized,
            "raw": raw,
        }
        chapters.append(chapter)

    chapter_file = f"./chapters/{video_id}_chapters.json"
    Path(chapter_file).parent.mkdir(parents=True, exist_ok=True)

    with open(chapter_file, "w", encoding="utf-8") as f:
        json.dump({"videoId": video_id, "chapters": chapters}, f, ensure_ascii=False, indent=2)

    print(f"✅ Saved chapters to: {chapter_file}")
    return chapter_file


def load_chapters_from_file(video_id: str) -> list[dict[str, Any]] | None:
    """
    中間ファイルからチャプターデータを読み込み

    Args:
        video_id: YouTube動画ID

    Returns:
        チャプターリスト（ファイルが存在しない場合はNone）
    """
    import json

    chapter_file = f"./chapters/{video_id}_chapters.json"
    if not Path(chapter_file).exists():
        return None

    with open(chapter_file, encoding="utf-8") as f:
        data = json.load(f)

    print(f"✅ Loaded chapters from: {chapter_file}")
    return data["chapters"]


def test_chapters(
    video_id: str,
    detections: list[MatchDetection] | None = None,
    results: list[tuple[dict[str, str], dict[str, str]]] | None = None,
    use_saved: bool = False,
) -> None:
    """
    YouTubeチャプター更新のテスト

    Args:
        video_id: YouTube動画ID
        detections: 検出結果リスト（use_saved=Falseの場合は必須）
        results: 認識結果リスト（use_saved=Falseの場合は必須）
        use_saved: 保存済みチャプターファイルを使用するか
    """
    print(f"[TEST] Updating YouTube chapters for video: {video_id}")

    if use_saved:
        # 保存済みファイルから読み込み
        chapters_data = load_chapters_from_file(video_id)
        if not chapters_data:
            raise FileNotFoundError(f"Chapter file not found for video: {video_id}")
        chapters = [{"startTime": ch["startTime"], "title": ch["title"]} for ch in chapters_data]
    else:
        # 検出・認識結果から生成
        if not detections or not results:
            raise ValueError("detections and results are required when use_saved=False")

        chapters = []
        for i, (detection, (normalized, _)) in enumerate(zip(detections, results, strict=False), 1):
            chapter = {
                "startTime": int(detection.timestamp),
                "title": f"第{i:02d}戦 {normalized.get('1p')} VS {normalized.get('2p')}",
            }
            chapters.append(chapter)

        # 中間ファイルに保存
        save_chapters_to_file(video_id, detections, results)

    print("Generated chapters:")
    for ch in chapters:
        print(f"   {ch['startTime']}s - {ch['title']}")

    # 実際に更新
    updater = YouTubeChapterUpdater()
    updater.update_video_description(video_id, chapters)
    print("✅ Updated YouTube description")


def main():
    """エントリーポイント"""
    import argparse

    parser = argparse.ArgumentParser(description="SF6 Chapter Processor")

    # メインモード
    parser.add_argument(
        "--mode",
        choices=["once", "daemon", "test"],
        default="once",
        help="Execution mode: 'once' for single pull, 'daemon' for continuous streaming, 'test' for testing individual steps",
    )

    # テストオプション
    parser.add_argument(
        "--test-step",
        choices=["download", "detect", "recognize", "chapters", "all"],
        help="Test specific processing step (requires --mode test)",
    )
    parser.add_argument(
        "--video-id",
        help="YouTube video ID for testing",
    )
    parser.add_argument(
        "--video-path",
        help="Path to downloaded video file (skip download step)",
    )
    parser.add_argument(
        "--use-saved-chapters",
        action="store_true",
        help="Use saved chapter file instead of running detection/recognition (only for --test-step chapters)",
    )

    args = parser.parse_args()

    # テストモード
    if args.mode == "test":
        if not args.test_step:
            parser.error("--test-step is required when --mode test")

        video_path = args.video_path
        detections = None
        results = None

        # ステップ実行
        if args.test_step in ["download", "all"]:
            if not args.video_id:
                parser.error("--video-id is required for download test")
            video_path = test_download(args.video_id)

        if args.test_step in ["detect", "all"]:
            if not video_path:
                # video_pathが指定されていない場合、video_idから自動取得（既存ファイル優先）
                if not args.video_id:
                    parser.error("--video-id or --video-path is required for detection test")
                video_path = test_download(args.video_id)
            detections = test_detection(video_path)

        if args.test_step in ["recognize", "all"]:
            if not detections:
                if not video_path:
                    # video_pathが指定されていない場合、video_idから自動取得（既存ファイル優先）
                    if not args.video_id:
                        parser.error("--video-id or --video-path is required")
                    video_path = test_download(args.video_id)
                detections = test_detection(video_path)
            results = test_recognition(detections)

        if args.test_step in ["chapters", "all"]:
            if not args.video_id:
                parser.error("--video-id is required for chapters test")

            if args.use_saved_chapters:
                # 保存済みチャプターファイルを使用
                test_chapters(args.video_id, use_saved=True)
            else:
                # 通常の処理（検出・認識を実行）
                if not detections or not results:
                    if not video_path:
                        # video_pathが指定されていない場合、video_idから自動取得（既存ファイル優先）
                        video_path = test_download(args.video_id)
                    detections = test_detection(video_path)
                    results = test_recognition(detections)
                test_chapters(args.video_id, detections, results)

        return

    # 通常モード
    processor = SF6ChapterProcessor()

    if args.mode == "once":
        processor.run_once()
    else:
        processor.run_forever()


if __name__ == "__main__":
    main()
