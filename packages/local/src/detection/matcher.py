"""
テンプレートマッチングによる対戦シーン検出
OpenCVを使用してフレームから対戦開始画面を検出
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np

from ..utils.logger import get_logger
from .preprocessing import preprocess_for_matching

if TYPE_CHECKING:
    from .result_detector import ResultScreenDetector

logger = get_logger()


@dataclass
class MatchDetection:
    """マッチ検出結果"""

    timestamp: float  # 秒
    frame_number: int
    confidence: float  # マッチング信頼度
    frame: np.ndarray  # 検出されたフレーム
    winner_side: str | None = None  # RESULT画面検出による勝者側 ("player1" | "player2" | None)


class TemplateMatcher:
    """テンプレートマッチングによる対戦シーン検出器"""

    def __init__(
        self,
        template_path: str,
        threshold: float = 0.4,
        min_interval_sec: float = 2.0,
        frame_interval: int = 2,
        reject_templates: list[str] | None = None,
        reject_threshold: float = 0.35,
        search_region: tuple[int, int, int, int] | None = None,
        post_check_frames: int = 10,
        post_check_reject_limit: int = 2,
        recognize_frame_offset: int = 6,
        recognize_frame_offset_alt: int = 4,
        recognize_frame_offset_threshold: float = 5.0,
        result_detector: "ResultScreenDetector | None" = None,
    ):
        """
        Args:
            template_path: テンプレート画像のパス（Round 1）
            threshold: マッチング閾値（0.0-1.0）
            min_interval_sec: 連続検出を避けるための最小間隔（秒）
            frame_interval: チェックするフレーム間隔
            reject_templates: 除外したい画像のパスリスト（Round 2, Final Roundなど）
            reject_threshold: 除外判定の閾値（これ以上マッチしたら除外）
            search_region: Round 1表示領域の限定 (x1, y1, x2, y2)
            post_check_frames: 検出後に確認するフレーム数
            post_check_reject_limit: この数以上除外マッチがあれば誤検知と判定
            recognize_frame_offset: 認識用フレームのデフォルトオフセット（フレーム数）
            recognize_frame_offset_alt: 認識用フレームの代替オフセット（フレーム数）
            recognize_frame_offset_threshold: 動的オフセット選択の閾値（標準偏差の差分）
            result_detector: RESULT画面検出器（オプション）- None でRESULT検出をスキップ
        """
        self.template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if self.template is None:
            raise FileNotFoundError(f"Template image not found: {template_path}")

        # テンプレートを前処理（エッジ抽出）
        self.template_edges = preprocess_for_matching(self.template)

        # 除外用テンプレート（Round 2, Final Round）
        self.reject_templates_edges = []
        if reject_templates:
            for reject_path in reject_templates:
                reject_img = cv2.imread(reject_path, cv2.IMREAD_COLOR)
                if reject_img is not None:
                    reject_edges = preprocess_for_matching(reject_img)
                    self.reject_templates_edges.append(reject_edges)

        self.threshold = threshold
        self.reject_threshold = reject_threshold
        self.min_interval_sec = min_interval_sec
        self.frame_interval = frame_interval
        self.search_region = search_region
        self.post_check_frames = post_check_frames
        self.post_check_reject_limit = post_check_reject_limit
        self.recognize_frame_offset = recognize_frame_offset
        self.recognize_frame_offset_alt = recognize_frame_offset_alt
        self.recognize_frame_offset_threshold = recognize_frame_offset_threshold
        self.result_detector = result_detector

    def _check_subsequent_frames(self, cap: cv2.VideoCapture, start_frame: int, num_frames: int) -> int:
        """
        検出後の後続フレームで除外テンプレートマッチの回数をカウント

        Args:
            cap: VideoCapture オブジェクト
            start_frame: 開始フレーム番号
            num_frames: チェックするフレーム数

        Returns:
            除外テンプレートにマッチしたフレーム数
        """
        reject_count = 0
        current_pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))

        for i in range(num_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame + i)
            ret, frame = cap.read()
            if not ret:
                break

            # 検索範囲を限定
            if self.search_region:
                x1, y1, x2, y2 = self.search_region
                search_frame = frame[y1:y2, x1:x2]
            else:
                search_frame = frame

            # フレームを前処理
            frame_edges = preprocess_for_matching(search_frame)

            # 除外テンプレートとマッチング
            for reject_template in self.reject_templates_edges:
                reject_result = cv2.matchTemplate(frame_edges, reject_template, cv2.TM_CCOEFF_NORMED)
                _, reject_max_val, _, _ = cv2.minMaxLoc(reject_result)

                if reject_max_val >= self.reject_threshold:
                    reject_count += 1
                    break  # 1つでもマッチしたらカウント

        # 元の位置に戻す
        cap.set(cv2.CAP_PROP_POS_FRAMES, current_pos)

        return reject_count

    @staticmethod
    def _calc_frame_std(frame: np.ndarray) -> float:
        """
        フレームの標準偏差を計算（品質指標として使用）

        Args:
            frame: BGRフレーム

        Returns:
            グレースケール変換後の標準偏差
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(np.std(gray))

    def _select_best_offset_frame(
        self,
        cap: cv2.VideoCapture,
        base_frame_number: int,
        crop_region: tuple[int, int, int, int] | None,
    ) -> tuple[np.ndarray, int]:
        """
        動的オフセット選択：2つのオフセットから品質の高いフレームを選択

        判定ルール:
        - std(offset_alt) - std(offset) >= threshold → offset_altを採用
        - それ以外 → offsetを採用（デフォルト）

        Args:
            cap: VideoCapture オブジェクト
            base_frame_number: 検出されたフレーム番号
            crop_region: キャラクター名部分の切り抜き領域 (x1, y1, x2, y2)

        Returns:
            (選択されたフレーム, 使用したオフセット値)
        """
        current_pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))

        # デフォルトオフセットのフレームを取得
        offset_frame_number = base_frame_number + self.recognize_frame_offset
        cap.set(cv2.CAP_PROP_POS_FRAMES, offset_frame_number)
        ret_offset, frame_offset = cap.read()

        # 代替オフセットのフレームを取得
        offset_alt_frame_number = base_frame_number + self.recognize_frame_offset_alt
        cap.set(cv2.CAP_PROP_POS_FRAMES, offset_alt_frame_number)
        ret_alt, frame_alt = cap.read()

        # 元の位置に戻す
        cap.set(cv2.CAP_PROP_POS_FRAMES, current_pos)

        # 読み込み失敗時のフォールバック
        if not ret_offset and not ret_alt:
            logger.warning("Failed to read both offset frames")
            return None, 0
        if not ret_offset:
            logger.warning("Failed to read default offset frame, using alt offset")
            return frame_alt, self.recognize_frame_offset_alt
        if not ret_alt:
            logger.warning("Failed to read alt offset frame, using default offset")
            return frame_offset, self.recognize_frame_offset

        # crop_regionで切り抜いて品質を比較
        if crop_region:
            x1, y1, x2, y2 = crop_region
            cropped_offset = frame_offset[y1:y2, x1:x2]
            cropped_alt = frame_alt[y1:y2, x1:x2]
        else:
            cropped_offset = frame_offset
            cropped_alt = frame_alt

        std_offset = self._calc_frame_std(cropped_offset)
        std_alt = self._calc_frame_std(cropped_alt)
        std_diff = std_alt - std_offset

        # 閾値に基づいて選択
        if std_diff >= self.recognize_frame_offset_threshold:
            logger.info(
                "  → Selected alt offset +%d frames (std: %.2f → %.2f, diff=%.2f >= threshold %.1f)",
                self.recognize_frame_offset_alt, std_offset, std_alt, std_diff, self.recognize_frame_offset_threshold
            )
            return frame_alt, self.recognize_frame_offset_alt
        else:
            logger.info(
                "  → Selected default offset +%d frames (std: %.2f vs %.2f, diff=%.2f < threshold %.1f)",
                self.recognize_frame_offset, std_offset, std_alt, std_diff, self.recognize_frame_offset_threshold
            )
            return frame_offset, self.recognize_frame_offset

    def detect_matches(
        self,
        video_path: str,
        start_sec: float = 0,
        duration_sec: float | None = None,
        crop_region: tuple[int, int, int, int] | None = None,
    ) -> list[MatchDetection]:
        """
        動画から対戦シーンを検出

        Args:
            video_path: 動画ファイルのパス
            start_sec: 検出開始位置（秒）
            duration_sec: 検出期間（秒、Noneで動画終端まで）
            crop_region: キャラクター名部分の切り抜き領域 (x1, y1, x2, y2)

        Returns:
            検出結果のリスト
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise OSError(f"Cannot open video: {video_path}")

        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            start_frame = int(start_sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            end_frame = start_frame + int(duration_sec * fps) if duration_sec is not None else total_frames

            detections: list[MatchDetection] = []
            frame_count = start_frame
            prev_timestamp: float | None = None

            logger.info("Scanning video from %.1fs to %.1fs...", start_sec, end_frame / fps)
            logger.info("Threshold is %.2f", self.threshold)

            while frame_count < end_frame:
                ret, frame = cap.read()
                if not ret:
                    break

                # 進捗表示（10秒ごと）
                if (frame_count - start_frame) % int(fps * 10) == 0:
                    progress = 100 * (frame_count - start_frame) / (end_frame - start_frame)
                    logger.info("Progress: %.1f%% (%d/%d frames)", progress, frame_count - start_frame, end_frame - start_frame)

                # frame_interval毎にマッチング
                if (frame_count - start_frame) % self.frame_interval == 0:
                    # 検索範囲を限定
                    if self.search_region:
                        x1, y1, x2, y2 = self.search_region
                        search_frame = frame[y1:y2, x1:x2]
                    else:
                        search_frame = frame

                    # フレームを前処理（エッジ抽出）
                    frame_edges = preprocess_for_matching(search_frame)

                    # エッジ画像同士でマッチング
                    result = cv2.matchTemplate(frame_edges, self.template_edges, cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

                    # Round 1テンプレート検出
                    round1_detected = False
                    if max_val >= self.threshold:
                        # 除外テンプレート（Round 2, Final Round）との照合
                        should_reject = False
                        reject_reason = ""
                        for idx, reject_template in enumerate(self.reject_templates_edges):
                            reject_result = cv2.matchTemplate(frame_edges, reject_template, cv2.TM_CCOEFF_NORMED)
                            _, reject_max_val, _, _ = cv2.minMaxLoc(reject_result)

                            if reject_max_val >= self.reject_threshold:
                                should_reject = True
                                reject_reason = f"reject_template_{idx} (confidence: {reject_max_val:.3f})"
                                break

                        if should_reject:
                            logger.info("Rejected match at %.1fs - matched %s", frame_count / fps, reject_reason)
                            frame_count += 1
                            continue

                        timestamp = frame_count / fps

                        # 連続マッチのスキップ
                        if prev_timestamp is None or timestamp - prev_timestamp >= self.min_interval_sec:
                            # 後続フレームで除外テンプレートマッチをチェック
                            if self.reject_templates_edges and self.post_check_frames > 0:
                                subsequent_reject_count = self._check_subsequent_frames(
                                    cap, frame_count + 1, self.post_check_frames
                                )

                                if subsequent_reject_count >= self.post_check_reject_limit:
                                    logger.info(
                                        "Rejected match at %.1fs - subsequent frames have %d reject matches (limit: %d)",
                                        timestamp, subsequent_reject_count, self.post_check_reject_limit
                                    )
                                    # 誤検知判定されたら、次のチェックまでスキップ
                                    prev_timestamp = timestamp
                                    frame_count += 1
                                    continue

                            prev_timestamp = timestamp

                            logger.info("Match detected at %.1fs (confidence: %.3f)", timestamp, max_val)

                            # 認識用フレームを取得（動的オフセット選択）
                            recognize_frame = frame
                            used_offset = 0
                            if self.recognize_frame_offset > 0:
                                selected_frame, used_offset = self._select_best_offset_frame(
                                    cap, frame_count, crop_region
                                )
                                if selected_frame is not None:
                                    recognize_frame = selected_frame
                                else:
                                    logger.warning("Failed to read offset frames, using original frame")
                                # 現在位置を元に戻す（次のループのため）
                                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count + 1)

                            # キャラクター名領域を切り抜き
                            cropped_frame = recognize_frame
                            if crop_region:
                                x1, y1, x2, y2 = crop_region
                                cropped_frame = recognize_frame[y1:y2, x1:x2]

                            detection = MatchDetection(
                                timestamp=timestamp,
                                frame_number=frame_count,
                                confidence=float(max_val),
                                frame=cropped_frame.copy(),
                            )
                            detections.append(detection)
                            round1_detected = True

                    # RESULT画面検出（Round 1検出後で、RESULT未検出の場合）
                    if (not round1_detected
                        and self.result_detector is not None
                        and len(detections) > 0
                        and detections[-1].winner_side is None):
                        # Round 1フレーム（search_region適用済み）をそのまま使用
                        result_detection = self.result_detector.detect_result(frame)
                        if result_detection.winner_side is not None:
                            detections[-1].winner_side = result_detection.winner_side
                            logger.info("RESULT detected at %.1fs: %s (win_position=%s)",
                                        frame_count / fps, result_detection.winner_side, result_detection.win_position)

                frame_count += 1

            logger.info("Detection complete. Found %d matches.", len(detections))
            return detections
        finally:
            cap.release()

    @staticmethod
    def save_detection_frame(detection: MatchDetection, output_path: str) -> None:
        """検出フレームを画像として保存"""
        cv2.imwrite(output_path, detection.frame)
