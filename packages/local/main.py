#!/usr/bin/env python3
"""
SF6 Chapter - メイン処理スクリプト
Pub/Subから新着動画を受信し、チャプター生成・アップロードを実行
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List,Tuple

# プロジェクトルートのconfigディレクトリをパスに追加
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.pubsub import PubSubSubscriber
from src.video import VideoDownloader
from src.detection import TemplateMatcher, MatchDetection
from src.character import CharacterRecognizer
from src.youtube import YouTubeChapterUpdater
from src.storage import R2Uploader


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
        self.recognizer = CharacterRecognizer(
            aliases_path=str(project_root / "config" / "character_aliases.json")
        )
        self.youtube_updater = YouTubeChapterUpdater()
        self.r2_uploader = R2Uploader()

    def process_video(self, message_data: Dict[str, Any]) -> None:
        """
        動画処理のメインフロー

        Args:
            message_data: Pub/Subメッセージデータ
        """
        video_id = message_data.get("videoId")
        if not video_id:
            print("Error: videoId not found in message")
            return

        print(f"\n{'='*60}")
        print(f"Processing video: {video_id}")
        print(f"Title: {message_data.get('title', 'N/A')}")
        print(f"{'='*60}\n")

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
            matches: List[Dict[str, Any]] = []
            chapters: List[Dict[str, Any]] = []

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
            print(f"   - Uploaded to R2")

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
    """動画ダウンロードのテスト"""
    print(f"[TEST] Downloading video: {video_id}")
    downloader = VideoDownloader(download_dir="./download")
    video_path = downloader.download(video_id)
    print(f"✅ Downloaded: {video_path}")
    return video_path


def test_detection(video_path: str) -> List[MatchDetection]:
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


def test_recognition(detections: List[MatchDetection]) -> List[Tuple[Dict[str, str], Dict[str, str]]]:
    """キャラクター認識のテスト"""
    print(f"[TEST] Recognizing characters from {len(detections)} frames")
    project_root = Path(__file__).parent.parent.parent.parent
    recognizer = CharacterRecognizer(
        aliases_path=str(project_root / "config" / "character_aliases.json")
    )

    results = []
    for i, detection in enumerate(detections, 1):
        print(f"   Processing match {i}/{len(detections)}...")
        normalized, raw = recognizer.recognize_from_frame(detection.frame)
        results.append((normalized, raw))
        print(f"   ✅ {normalized.get('1p')} VS {normalized.get('2p')}")
        print(f"      (raw: {raw.get('1p')} vs {raw.get('2p')})")

    return results


def test_chapters(video_id: str, detections: List[MatchDetection], results: List[Tuple[Dict[str, str], Dict[str, str]]]) -> None:
    """YouTubeチャプター更新のテスト"""
    print(f"[TEST] Updating YouTube chapters for video: {video_id}")

    chapters = []
    for i, (detection, (normalized, _)) in enumerate(zip(detections, results), 1):
        chapter = {
            "startTime": int(detection.timestamp),
            "title": f"第{i:02d}戦 {normalized.get('1p')} VS {normalized.get('2p')}",
        }
        chapters.append(chapter)

    print(f"Generated chapters:")
    for ch in chapters:
        print(f"   {ch['startTime']}s - {ch['title']}")

    # 実際に更新
    updater = YouTubeChapterUpdater()
    updater.update_video_description(video_id, chapters)
    print(f"✅ Updated YouTube description")


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
                parser.error("--video-path is required for detection test")
            detections = test_detection(video_path)

        if args.test_step in ["recognize", "all"]:
            if not detections:
                if not video_path:
                    parser.error("--video-path is required")
                detections = test_detection(video_path)
            results = test_recognition(detections)

        if args.test_step in ["chapters", "all"]:
            if not args.video_id:
                parser.error("--video-id is required for chapters test")
            if not detections or not results:
                if not video_path:
                    parser.error("--video-path is required")
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
