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

# アプリケーションルートのconfigディレクトリのパスを取得
# ローカル実行: packages/local/main.py → packages/local/config
# Docker実行: /app/main.py → /app/config
app_root = Path(__file__).parent
sys.path.insert(0, str(app_root))

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
        # アプリケーションルートディレクトリ（ローカル: packages/local/, Docker: /app/）
        self.app_root = Path(__file__).parent

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
        self.recognizer = CharacterRecognizer(aliases_path=str(self.app_root / "config" / "character_aliases.json"))
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
                self.r2_uploader.update_parquet_table([video_data], "videos.parquet", dedup_key="videoId")
                self.r2_uploader.update_parquet_table(matches, "matches.parquet", dedup_key="id")
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

    def _save_detection_summary(self, video_id: str, output_dir: Path, detections: list[MatchDetection]) -> None:
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


# ====================
# 中間ファイル管理ヘルパー関数
# ====================


def get_intermediate_dir(video_id: str) -> Path:
    """
    動画IDの中間ファイルディレクトリを取得

    Args:
        video_id: YouTube動画ID

    Returns:
        中間ファイルディレクトリのPath
    """
    base_dir = Path(os.environ.get("INTERMEDIATE_DIR", "./intermediate"))
    video_dir = base_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    return video_dir


def save_detection_results(video_id: str, detections: list[MatchDetection], video_path: str) -> Path:
    """
    検出結果を中間ファイルに保存

    Args:
        video_id: YouTube動画ID
        detections: 検出結果リスト
        video_path: 処理した動画ファイルのパス

    Returns:
        保存先ディレクトリのPath
    """
    import json

    output_dir = get_intermediate_dir(video_id)

    # 検出サマリーを保存
    summary = {
        "videoId": video_id,
        "videoPath": video_path,
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

    logger.info("✅ Saved detection summary: %s", summary_path)

    # 検出フレーム画像を保存
    template_path = os.environ.get("TEMPLATE_PATH", "./template/round1.png")
    reject_templates = [
        os.environ.get("REJECT_TEMPLATE_ROUND2", "./template/round2.png"),
        os.environ.get("REJECT_TEMPLATE_FINAL", "./template/final_round.png"),
    ]
    round1_search_region = (575, 333, 1500, 800)

    matcher = TemplateMatcher(
        template_path=template_path,
        threshold=0.32,
        min_interval_sec=2.0,
        reject_templates=reject_templates,
        reject_threshold=0.35,
        search_region=round1_search_region,
        post_check_frames=10,
        post_check_reject_limit=2,
    )

    for i, detection in enumerate(detections, 1):
        frame_path = output_dir / f"frame_{i:03d}_{int(detection.timestamp)}s.png"
        matcher.save_detection_frame(detection, str(frame_path))

    logger.info("✅ Saved %d detection frames to: %s", len(detections), output_dir)

    return output_dir


def load_detection_results(video_id: str) -> tuple[list[MatchDetection], str] | None:
    """
    中間ファイルから検出結果を読み込み

    Args:
        video_id: YouTube動画ID

    Returns:
        (検出結果リスト, 動画パス) のタプル、ファイルが存在しない場合はNone
    """
    import json

    import cv2

    output_dir = get_intermediate_dir(video_id)
    summary_path = output_dir / "detection_summary.json"

    if not summary_path.exists():
        return None

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    detections = []
    for det_info in summary["detections"]:
        # フレーム画像を読み込み
        frame_path = output_dir / f"frame_{det_info['index']:03d}_{int(det_info['timestamp'])}s.png"
        if not frame_path.exists():
            logger.warning("Frame image not found: %s", frame_path)
            continue

        frame = cv2.imread(str(frame_path))
        if frame is None:
            logger.warning("Failed to load frame: %s", frame_path)
            continue

        detection = MatchDetection(
            frame=frame,
            timestamp=det_info["timestamp"],
            frame_number=det_info["frameNumber"],
            confidence=det_info["confidence"],
        )
        detections.append(detection)

    video_path = summary.get("videoPath", "")
    logger.info("✅ Loaded %d detections from: %s", len(detections), output_dir)

    return detections, video_path


def save_recognition_results(
    video_id: str, detections: list[MatchDetection], results: list[tuple[dict[str, str], dict[str, str]]]
) -> None:
    """
    認識結果を中間ファイルに保存

    Args:
        video_id: YouTube動画ID
        detections: 検出結果リスト
        results: 認識結果リスト
    """
    import json

    output_dir = get_intermediate_dir(video_id)

    chapters = []
    for i, (detection, (normalized, raw)) in enumerate(zip(detections, results, strict=False), 1):
        chapter = {
            "index": i,
            "startTime": int(detection.timestamp),
            "title": f"第{i:02d}戦 {normalized.get('1p')} VS {normalized.get('2p')}",
            "normalized": normalized,
            "raw": raw,
            "confidence": detection.confidence,
        }
        chapters.append(chapter)

    chapters_data = {
        "videoId": video_id,
        "recognizedAt": datetime.utcnow().isoformat() + "Z",
        "totalMatches": len(chapters),
        "chapters": chapters,
    }

    chapters_path = output_dir / "chapters.json"
    with open(chapters_path, "w", encoding="utf-8") as f:
        json.dump(chapters_data, f, ensure_ascii=False, indent=2)

    logger.info("✅ Saved recognition results: %s", chapters_path)


def load_recognition_results(video_id: str) -> list[dict[str, Any]] | None:
    """
    中間ファイルから認識結果を読み込み

    Args:
        video_id: YouTube動画ID

    Returns:
        チャプターリスト、ファイルが存在しない場合はNone
    """
    import json

    output_dir = get_intermediate_dir(video_id)
    chapters_path = output_dir / "chapters.json"

    if not chapters_path.exists():
        return None

    with open(chapters_path, encoding="utf-8") as f:
        data = json.load(f)

    logger.info("✅ Loaded recognition results from: %s", chapters_path)
    return data["chapters"]


def test_download(video_id: str) -> str:
    """動画ダウンロードのテスト（既存ファイルがあれば再利用）"""
    logger.info("[TEST] Downloading video: %s", video_id)
    downloader = VideoDownloader(download_dir="./download")
    video_path = downloader.download(video_id, skip_if_exists=True)
    logger.info("✅ Downloaded: %s", video_path)
    return video_path


def test_detection(video_id: str, video_path: str, save_intermediate: bool = True) -> list[MatchDetection]:
    """
    対戦シーン検出のテスト

    Args:
        video_id: YouTube動画ID
        video_path: 動画ファイルのパス
        save_intermediate: 中間ファイルに保存するか

    Returns:
        検出結果リスト
    """
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

    # 中間ファイルに保存
    if save_intermediate and video_id:
        save_detection_results(video_id, detections, video_path)

    return detections


def test_recognition(
    video_id: str,
    detections: list[MatchDetection] | None = None,
    from_intermediate: bool = False,
    save_intermediate: bool = True,
) -> list[tuple[dict[str, str], dict[str, str]]]:
    """
    キャラクター認識のテスト

    Args:
        video_id: YouTube動画ID
        detections: 検出結果リスト（from_intermediate=Falseの場合は必須）
        from_intermediate: 中間ファイルから検出結果を読み込むか
        save_intermediate: 中間ファイルに保存するか

    Returns:
        認識結果リスト
    """
    # 中間ファイルから読み込み
    if from_intermediate:
        loaded = load_detection_results(video_id)
        if not loaded:
            raise FileNotFoundError(f"Detection results not found for video: {video_id}")
        detections, _ = loaded
        logger.info("✅ Loaded detections from intermediate files")

    if not detections:
        raise ValueError("detections is required when from_intermediate=False")

    logger.info("[TEST] Recognizing characters from %d frames", len(detections))
    app_root = Path(__file__).parent
    recognizer = CharacterRecognizer(aliases_path=str(app_root / "config" / "character_aliases.json"))

    results = []
    for i, detection in enumerate(detections, 1):
        logger.info("   Processing match %d/%d...", i, len(detections))
        normalized, raw = recognizer.recognize_from_frame(detection.frame)
        results.append((normalized, raw))
        logger.info("   ✅ %s VS %s", normalized.get("1p"), normalized.get("2p"))
        logger.info("      (raw: %s vs %s)", raw.get("1p"), raw.get("2p"))

    # 中間ファイルに保存
    if save_intermediate and video_id:
        save_recognition_results(video_id, detections, results)

    return results


def test_chapters(
    video_id: str,
    detections: list[MatchDetection] | None = None,
    results: list[tuple[dict[str, str], dict[str, str]]] | None = None,
    from_intermediate: bool = False,
) -> list[dict[str, Any]]:
    """
    YouTubeチャプター更新のテスト

    Args:
        video_id: YouTube動画ID
        detections: 検出結果リスト（from_intermediate=Falseの場合は必須）
        results: 認識結果リスト（from_intermediate=Falseの場合は必須）
        from_intermediate: 中間ファイルから認識結果を読み込むか

    Returns:
        生成されたチャプターリスト
    """
    logger.info("[TEST] Updating YouTube chapters for video: %s", video_id)

    if from_intermediate:
        # 中間ファイルから読み込み
        chapters_data = load_recognition_results(video_id)
        if not chapters_data:
            raise FileNotFoundError(f"Recognition results not found for video: {video_id}")
        chapters = [{"startTime": ch["startTime"], "title": ch["title"]} for ch in chapters_data]
    else:
        # 検出・認識結果から生成
        if not detections or not results:
            raise ValueError("detections and results are required when from_intermediate=False")

        chapters = []
        for i, (detection, (normalized, _)) in enumerate(zip(detections, results, strict=False), 1):
            chapter = {
                "startTime": int(detection.timestamp),
                "title": f"第{i:02d}戦 {normalized.get('1p')} VS {normalized.get('2p')}",
            }
            chapters.append(chapter)

        # 中間ファイルに保存（まだ保存されていない場合）
        save_recognition_results(video_id, detections, results)

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
    from_intermediate: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    R2アップロードとParquet更新のテスト

    Args:
        video_id: YouTube動画ID
        detections: 検出結果リスト（from_intermediate=Falseの場合は必須）
        results: 認識結果リスト（from_intermediate=Falseの場合は必須）
        from_intermediate: 中間ファイルから認識結果を読み込むか

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

    if from_intermediate:
        # 中間ファイルから読み込み
        saved_chapters = load_recognition_results(video_id)
        if not saved_chapters:
            raise FileNotFoundError(f"Recognition results not found for video: {video_id}")

        logger.info("✅ Using saved recognition results from intermediate files")
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
                "confidence": chapter_data.get("confidence", 0.0),
                "templateMatchScore": chapter_data.get("confidence", 0.0),
                "frameTimestamp": 0,
            }
            matches.append(match_data)

    else:
        # detectionsとresultsから生成
        if not detections or not results:
            raise ValueError("detections and results are required when from_intermediate=False")

        logger.info("Generating data from detections and results")

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

        # 中間ファイルに保存（まだ保存されていない場合）
        save_recognition_results(video_id, detections, results)

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
    r2_uploader.update_parquet_table([video_data], "videos.parquet", dedup_key="videoId")
    r2_uploader.update_parquet_table(matches, "matches.parquet", dedup_key="id")

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
        "--from-intermediate",
        action="store_true",
        help="Load detection/recognition results from intermediate files instead of running from scratch",
    )

    args = parser.parse_args()

    # テストモード
    if args.mode == "test":
        if not args.test_step:
            parser.error("--test-step is required when --mode test")

        if not args.video_id:
            parser.error("--video-id is required for test mode")

        video_path = args.video_path
        detections = None
        results = None

        # ステップ実行
        if args.test_step in ["download", "all"]:
            video_path = test_download(args.video_id)

        if args.test_step in ["detect", "all"]:
            if not video_path:
                # video_pathが指定されていない場合、video_idから自動取得（既存ファイル優先）
                video_path = test_download(args.video_id)
            detections = test_detection(args.video_id, video_path)

        if args.test_step in ["recognize", "all"]:
            # --from-intermediateが指定されている場合は中間ファイルから読み込み
            if args.from_intermediate:
                results = test_recognition(args.video_id, from_intermediate=True)
            else:
                # 検出結果がない場合は、detectステップから実行
                if not detections:
                    if not video_path:
                        video_path = test_download(args.video_id)
                    detections = test_detection(args.video_id, video_path)
                results = test_recognition(args.video_id, detections=detections)

        if args.test_step in ["chapters", "all"]:
            # --from-intermediateが指定されている場合は中間ファイルから読み込み
            if args.from_intermediate:
                test_chapters(args.video_id, from_intermediate=True)
            else:
                # 検出・認識結果がない場合は、前ステップから実行
                if not detections or not results:
                    if not video_path:
                        video_path = test_download(args.video_id)
                    detections = test_detection(args.video_id, video_path)
                    results = test_recognition(args.video_id, detections=detections)
                test_chapters(args.video_id, detections, results)

        if args.test_step in ["r2", "all"]:
            # --from-intermediateが指定されている場合は中間ファイルから読み込み
            if args.from_intermediate:
                test_r2_upload(args.video_id, from_intermediate=True)
            else:
                # 検出・認識結果がない場合は、前ステップから実行
                if not detections or not results:
                    if not video_path:
                        video_path = test_download(args.video_id)
                    detections = test_detection(args.video_id, video_path)
                    results = test_recognition(args.video_id, detections=detections)
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
