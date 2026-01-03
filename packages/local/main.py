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
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.character import CharacterRecognizer
from src.detection import MatchDetection, TemplateMatcher
from src.firestore import FirestoreClient
from src.pubsub import PubSubSubscriber
from src.storage import R2Uploader
from src.utils.logger import setup_logger
from src.video import VideoDownloader
from src.youtube import YouTubeChapterUpdater

# ロガー初期化
logger = setup_logger()


class SF6ChapterProcessor:
    """SF6チャプター処理のメインクラス"""

    def __init__(self):
        """初期化"""
        # 設定
        self.template_path = os.environ.get("TEMPLATE_PATH", "./template/round1.png")
        self.download_dir = os.environ.get("DOWNLOAD_DIR", "./download")
        self.crop_region = (339, 886, 1748, 980)  # キャラクター名表示領域

        # 中間ファイル保存ディレクトリ
        self.intermediate_dir = Path(os.environ.get("INTERMEDIATE_DIR", "./intermediate"))
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)

        # R2アップロードを有効にするかどうか（環境変数で制御）
        self.enable_r2 = os.environ.get("ENABLE_R2", "false").lower() in ("true", "1", "yes")

        # 除外テンプレート（Round 2, Final Round）
        self.reject_templates = [
            os.environ.get("REJECT_TEMPLATE_ROUND2", "./template/round2.png"),
            os.environ.get("REJECT_TEMPLATE_FINAL", "./template/final_round.png"),
        ]

        # モジュール初期化
        self.subscriber = PubSubSubscriber()
        self.firestore = FirestoreClient()
        self.downloader = VideoDownloader(download_dir=self.download_dir)
        # Round 1表示領域（画面中央上部）
        self.round1_search_region = (575, 333, 1500, 800)

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

        # R2Uploaderはenable_r2がTrueの場合のみ初期化
        self.r2_uploader = R2Uploader() if self.enable_r2 else None

    def process_video(self, message_data: dict[str, Any]) -> None:
        """
        動画処理のメインフロー

        Args:
            message_data: Pub/Subメッセージデータ
        """
        video_id = message_data.get("videoId")
        if not video_id:
            logger.error("videoId not found in message")
            return

        logger.info("=" * 60)
        logger.info("Processing video: %s", video_id)
        logger.info("Title: %s", message_data.get("title", "N/A"))
        logger.info("=" * 60)

        # 0. Firestoreで処理済みかチェック
        if self.firestore.is_completed(video_id):
            logger.info("Video already completed, skipping")
            logger.info("=" * 60)
            return

        # 処理開始をFirestoreに記録
        self.firestore.update_status(video_id, FirestoreClient.STATUS_PROCESSING)

        # 中間ファイル保存用ディレクトリを作成
        video_intermediate_dir = self.intermediate_dir / video_id
        video_intermediate_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. 動画ダウンロード
            logger.info("[1/6] Downloading video...")
            video_path = self.downloader.download(video_id)
            logger.info("Downloaded: %s", video_path)

            # 2. テンプレートマッチングで対戦シーンを検出
            logger.info("[2/6] Detecting match scenes...")
            detections = self.matcher.detect_matches(
                video_path=video_path,
                crop_region=self.crop_region,
            )
            logger.info("Found %d matches", len(detections))

            # 検出結果を中間ファイルに保存
            self._save_detection_summary(video_id, video_intermediate_dir, detections)

            if not detections:
                logger.info("No matches found, skipping video")
                return

            # 3. Gemini APIでキャラクター認識
            logger.info("[3/6] Recognizing characters...")
            matches: list[dict[str, Any]] = []
            chapters: list[dict[str, Any]] = []

            for i, detection in enumerate(detections, 1):
                try:
                    # フレーム画像を保存
                    frame_path = video_intermediate_dir / f"frame_{i:03d}_{int(detection.timestamp)}s.png"
                    self.matcher.save_detection_frame(detection, str(frame_path))

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
                        "savedFramePath": str(frame_path),  # 保存したフレーム画像のパス
                    }
                    matches.append(match_data)

                    # チャプター情報
                    chapter = {
                        "startTime": int(detection.timestamp),
                        "title": f"第{i:02d}戦 {normalized.get('1p')} VS {normalized.get('2p')}",
                        "matchId": match_id,
                    }
                    chapters.append(chapter)

                    logger.info("  %s at %.1fs", chapter["title"], detection.timestamp)

                except Exception:
                    logger.exception("Error recognizing characters for match %d", i)
                    continue

            # 4. YouTube チャプター更新
            logger.info("[4/6] Updating YouTube chapters...")
            self.youtube_updater.update_video_description(video_id, chapters)

            # 5-6. R2アップロード処理（有効な場合のみ）
            if self.enable_r2 and self.r2_uploader:
                # 5. JSONデータをR2にアップロード
                logger.info("[5/6] Uploading JSON data to R2...")
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
                logger.info("[6/6] Updating Parquet files...")
                self.r2_uploader.update_parquet_table([video_data], "videos.parquet")
                self.r2_uploader.update_parquet_table(matches, "matches.parquet")
            else:
                logger.info("[5/6] R2 upload disabled (ENABLE_R2=false)")
                logger.info("[6/6] Skipping Parquet update")

                # ローカルに保存
                import json

                output_dir = Path("./output")
                output_dir.mkdir(exist_ok=True)

                video_data = {
                    "videoId": video_id,
                    "title": message_data.get("title", ""),
                    "channelId": message_data.get("channelId", ""),
                    "channelTitle": message_data.get("channelTitle", ""),
                    "publishedAt": message_data.get("publishedAt", ""),
                    "processedAt": datetime.utcnow().isoformat() + "Z",
                    "chapters": chapters,
                    "detectionStats": {
                        "totalFrames": 0,
                        "matchedFrames": len(detections),
                    },
                }

                # JSONファイルとして保存
                video_json_path = output_dir / f"{video_id}_video.json"
                with open(video_json_path, "w", encoding="utf-8") as f:
                    json.dump(video_data, f, ensure_ascii=False, indent=2)
                logger.info("   Saved video data: %s", video_json_path)

                # 対戦データも保存
                matches_json_path = output_dir / f"{video_id}_matches.json"
                with open(matches_json_path, "w", encoding="utf-8") as f:
                    json.dump(matches, f, ensure_ascii=False, indent=2)
                logger.info("   Saved matches data: %s", matches_json_path)

            # 最終結果を中間ファイルとして保存
            self._save_final_results(video_id, video_intermediate_dir, video_data, matches, chapters)

            # 処理完了をFirestoreに記録
            self.firestore.update_status(video_id, FirestoreClient.STATUS_COMPLETED)

            logger.info("")
            logger.info("✅ Successfully processed video: %s", video_id)
            logger.info("   - Detected %d matches", len(matches))
            logger.info("   - Created %d chapters", len(chapters))
            logger.info("   - Intermediate files saved to: %s", video_intermediate_dir)
            if self.enable_r2:
                logger.info("   - Uploaded to R2")
            else:
                logger.info("   - Saved locally to ./output/")

        except Exception as e:
            # 処理失敗をFirestoreに記録
            self.firestore.update_status(video_id, FirestoreClient.STATUS_FAILED, error_message=str(e))
            logger.error("")
            logger.exception("❌ Error processing video %s", video_id)

    def run_once(self) -> None:
        """1回だけPub/SubからPullして処理"""
        logger.info("Pulling messages from Pub/Sub...")
        self.subscriber.pull_messages(
            callback=self.process_video,
            max_messages=10,
            timeout=30.0,
        )

    def run_forever(self) -> None:
        """常駐モードで実行"""
        logger.info("Starting streaming mode...")
        self.subscriber.listen_streaming(callback=self.process_video)

    def _save_detection_summary(
        self, video_id: str, output_dir: Path, detections: list[MatchDetection]
    ) -> None:
        """
        検出結果のサマリーを保存

        Args:
            video_id: YouTube動画ID
            output_dir: 出力ディレクトリ
            detections: 検出結果リスト
        """
        import json

        summary = {
            "videoId": video_id,
            "detectedAt": datetime.utcnow().isoformat() + "Z",
            "totalDetections": len(detections),
            "detections": [
                {
                    "index": i,
                    "timestamp": det.timestamp,
                    "frameNumber": det.frame_number,
                    "confidence": det.confidence,
                }
                for i, det in enumerate(detections, 1)
            ],
        }

        summary_path = output_dir / "detection_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info("   Saved detection summary: %s", summary_path)

    def _save_final_results(
        self,
        video_id: str,
        output_dir: Path,
        video_data: dict[str, Any],
        matches: list[dict[str, Any]],
        chapters: list[dict[str, Any]],
    ) -> None:
        """
        最終結果を中間ファイルとして保存

        Args:
            video_id: YouTube動画ID
            output_dir: 出力ディレクトリ
            video_data: 動画メタデータ
            matches: 対戦データリスト
            chapters: チャプターリスト
        """
        import json

        # 動画データ
        video_path = output_dir / "video_data.json"
        with open(video_path, "w", encoding="utf-8") as f:
            json.dump(video_data, f, ensure_ascii=False, indent=2)

        # 対戦データ
        matches_path = output_dir / "matches.json"
        with open(matches_path, "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)

        # チャプターデータ
        chapters_path = output_dir / "chapters.json"
        with open(chapters_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "videoId": video_id,
                    "chapters": chapters,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        logger.info("   Saved final results:")
        logger.info("     - %s", video_path)
        logger.info("     - %s", matches_path)
        logger.info("     - %s", chapters_path)


def test_download(video_id: str) -> str:
    """動画ダウンロードのテスト（既存ファイルがあれば再利用）"""
    logger.info("[TEST] Downloading video: %s", video_id)
    downloader = VideoDownloader(download_dir="./download")
    video_path = downloader.download(video_id, skip_if_exists=True)
    logger.info("✅ Downloaded: %s", video_path)
    return video_path


def test_detection(video_path: str) -> list[MatchDetection]:
    """対戦シーン検出のテスト"""
    logger.info("[TEST] Detecting matches in: %s", video_path)
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
    logger.info("✅ Found %d matches", len(detections))
    for i, det in enumerate(detections, 1):
        logger.info("   %d. %.1fs (confidence: %.3f)", i, det.timestamp, det.confidence)
    return detections


def test_recognition(detections: list[MatchDetection]) -> list[tuple[dict[str, str], dict[str, str]]]:
    """キャラクター認識のテスト"""
    logger.info("[TEST] Recognizing characters from %d frames", len(detections))
    project_root = Path(__file__).parent.parent.parent
    recognizer = CharacterRecognizer(aliases_path=str(project_root / "config" / "character_aliases.json"))

    results = []
    for i, detection in enumerate(detections, 1):
        logger.info("   Processing match %d/%d...", i, len(detections))
        normalized, raw = recognizer.recognize_from_frame(detection.frame)
        results.append((normalized, raw))
        logger.info("   ✅ %s VS %s", normalized.get("1p"), normalized.get("2p"))
        logger.info("      (raw: %s vs %s)", raw.get("1p"), raw.get("2p"))

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

    logger.info("✅ Saved chapters to: %s", chapter_file)
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

    logger.info("✅ Loaded chapters from: %s", chapter_file)
    return data["chapters"]


def test_chapters(
    video_id: str,
    detections: list[MatchDetection] | None = None,
    results: list[tuple[dict[str, str], dict[str, str]]] | None = None,
    use_saved: bool = False,
) -> list[dict[str, Any]]:
    """
    YouTubeチャプター更新のテスト

    Args:
        video_id: YouTube動画ID
        detections: 検出結果リスト（use_saved=Falseの場合は必須）
        results: 認識結果リスト（use_saved=Falseの場合は必須）
        use_saved: 保存済みチャプターファイルを使用するか

    Returns:
        生成されたチャプターリスト
    """
    logger.info("[TEST] Updating YouTube chapters for video: %s", video_id)

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

    logger.info("Generated chapters:")
    for ch in chapters:
        logger.info("   %ds - %s", ch["startTime"], ch["title"])

    # 実際に更新
    updater = YouTubeChapterUpdater()
    updater.update_video_description(video_id, chapters)
    logger.info("✅ Updated YouTube description")

    return chapters


def test_r2_upload(
    video_id: str,
    detections: list[MatchDetection] | None = None,
    results: list[tuple[dict[str, str], dict[str, str]]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    R2アップロードとParquet更新のテスト

    Args:
        video_id: YouTube動画ID
        detections: 検出結果リスト（保存済みチャプターがない場合は必須）
        results: 認識結果リスト（保存済みチャプターがない場合は必須）

    Returns:
        (video_data, matches) のタプル
    """
    logger.info("[TEST] Testing R2 upload and Parquet update for video: %s", video_id)

    # ENABLE_R2環境変数をチェック
    enable_r2 = os.environ.get("ENABLE_R2", "false").lower() in ("true", "1", "yes")

    if not enable_r2:
        logger.warning("⚠️  R2 upload is disabled (ENABLE_R2=false)")
        logger.info("   Set ENABLE_R2=true to test R2 upload")
        return {}, []

    # R2Uploaderを初期化
    r2_uploader = R2Uploader()

    # 保存済みチャプターファイルがあれば読み込む
    saved_chapters = load_chapters_from_file(video_id)

    if saved_chapters:
        logger.info("✅ Using saved chapter data from file")
        # 保存済みデータから生成
        chapters = []
        matches = []

        for chapter_data in saved_chapters:
            # チャプターデータ
            match_id = f"{video_id}_{chapter_data['startTime']}"
            chapter = {
                "startTime": chapter_data["startTime"],
                "title": chapter_data["title"],
                "matchId": match_id,
            }
            chapters.append(chapter)

            # 対戦データ
            normalized = chapter_data.get("normalized", {})
            raw = chapter_data.get("raw", {})
            match_data = {
                "id": match_id,
                "videoId": video_id,
                "startTime": chapter_data["startTime"],
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
                "confidence": 0.0,  # 保存データには含まれない
                "templateMatchScore": 0.0,
                "frameTimestamp": 0,
            }
            matches.append(match_data)

    else:
        # 保存データがない場合は、detectionsとresultsから生成
        logger.info("No saved chapter data found, generating from detections and results")

        if not detections or not results:
            raise ValueError("detections and results are required when no saved chapter data exists")

        # チャプターデータを生成
        chapters = []
        for i, (detection, (normalized, _)) in enumerate(zip(detections, results, strict=False), 1):
            chapter = {
                "startTime": int(detection.timestamp),
                "title": f"第{i:02d}戦 {normalized.get('1p')} VS {normalized.get('2p')}",
                "matchId": f"{video_id}_{int(detection.timestamp)}",
            }
            chapters.append(chapter)

        # 対戦データを生成
        matches = []
        for _i, (detection, (normalized, raw)) in enumerate(zip(detections, results, strict=False), 1):
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

    # 動画メタデータを生成
    video_data = {
        "videoId": video_id,
        "title": f"Test Video {video_id}",  # テストなのでダミータイトル
        "channelId": "test_channel",
        "channelTitle": "Test Channel",
        "publishedAt": datetime.utcnow().isoformat() + "Z",
        "processedAt": datetime.utcnow().isoformat() + "Z",
        "chapters": chapters,
        "detectionStats": {
            "totalFrames": 0,
            "matchedFrames": len(matches),  # matchesの数を使用（detectionsはNoneの可能性がある）
        },
    }

    # 5. JSONデータをR2にアップロード
    logger.info("[5/6] Uploading JSON data to R2...")
    r2_uploader.upload_json(video_data, f"videos/{video_id}.json")

    for match in matches:
        r2_uploader.upload_json(match, f"matches/{match['id']}.json")

    # 6. Parquetファイルを更新
    logger.info("[6/6] Updating Parquet files...")
    r2_uploader.update_parquet_table([video_data], "videos.parquet")
    r2_uploader.update_parquet_table(matches, "matches.parquet")

    logger.info("✅ R2 upload and Parquet update completed")
    logger.info("   - Uploaded %d matches", len(matches))
    logger.info("   - Updated Parquet tables")

    return video_data, matches


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
        choices=["download", "detect", "recognize", "chapters", "r2", "all"],
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

        if args.test_step in ["r2", "all"]:
            if not args.video_id:
                parser.error("--video-id is required for R2 test")

            # 保存済みチャプターファイルの確認
            saved_chapters = load_chapters_from_file(args.video_id)

            if saved_chapters:
                # 保存済みデータがあれば、それを使用（検出・認識をスキップ）
                logger.info("Using saved chapter data for R2 upload test")
                test_r2_upload(args.video_id)
            else:
                # 保存データがない場合は、検出・認識を実行
                logger.info("No saved chapter data found, running detection and recognition")
                if not detections or not results:
                    if not video_path:
                        # video_pathが指定されていない場合、video_idから自動取得（既存ファイル優先）
                        video_path = test_download(args.video_id)
                    detections = test_detection(video_path)
                    results = test_recognition(detections)

                test_r2_upload(args.video_id, detections, results)

        return

    # 通常モード
    processor = SF6ChapterProcessor()

    if args.mode == "once":
        processor.run_once()
    else:
        processor.run_forever()


if __name__ == "__main__":
    main()
