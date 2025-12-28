"""
テンプレートマッチングによる対戦シーン検出
OpenCVを使用してフレームから対戦開始画面を検出
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Any
from dataclasses import dataclass


@dataclass
class MatchDetection:
    """マッチ検出結果"""
    timestamp: float  # 秒
    frame_number: int
    confidence: float  # マッチング信頼度
    frame: np.ndarray  # 検出されたフレーム


class TemplateMatcher:
    """テンプレートマッチングによる対戦シーン検出器"""

    def __init__(
        self,
        template_path: str,
        threshold: float = 0.8,
        min_interval_sec: float = 2.0,
        frame_interval: int = 30,
    ):
        """
        Args:
            template_path: テンプレート画像のパス
            threshold: マッチング閾値（0.0-1.0）
            min_interval_sec: 連続検出を避けるための最小間隔（秒）
            frame_interval: チェックするフレーム間隔
        """
        self.template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if self.template is None:
            raise FileNotFoundError(f"Template image not found: {template_path}")

        self.threshold = threshold
        self.min_interval_sec = min_interval_sec
        self.frame_interval = frame_interval

    def detect_matches(
        self,
        video_path: str,
        start_sec: float = 0,
        duration_sec: float | None = None,
        crop_region: Tuple[int, int, int, int] | None = None,
    ) -> List[MatchDetection]:
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
            raise IOError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        start_frame = int(start_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        if duration_sec is not None:
            end_frame = start_frame + int(duration_sec * fps)
        else:
            end_frame = total_frames

        detections: List[MatchDetection] = []
        frame_count = start_frame
        prev_timestamp: float | None = None

        print(f"Scanning video from {start_sec}s to {end_frame/fps:.1f}s...")

        while frame_count < end_frame:
            ret, frame = cap.read()
            if not ret:
                break

            # 進捗表示（10秒ごと）
            if (frame_count - start_frame) % int(fps * 10) == 0:
                progress = 100 * (frame_count - start_frame) / (end_frame - start_frame)
                print(f"Progress: {progress:.1f}% ({frame_count - start_frame}/{end_frame - start_frame} frames)")

            # frame_interval毎にマッチング
            if (frame_count - start_frame) % self.frame_interval == 0:
                result = cv2.matchTemplate(frame, self.template, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

                if max_val >= self.threshold:
                    timestamp = frame_count / fps

                    # 連続マッチのスキップ
                    if prev_timestamp is None or timestamp - prev_timestamp >= self.min_interval_sec:
                        prev_timestamp = timestamp

                        # キャラクター名領域を切り抜き
                        cropped_frame = frame
                        if crop_region:
                            x1, y1, x2, y2 = crop_region
                            cropped_frame = frame[y1:y2, x1:x2]

                        detection = MatchDetection(
                            timestamp=timestamp,
                            frame_number=frame_count,
                            confidence=float(max_val),
                            frame=cropped_frame.copy(),
                        )
                        detections.append(detection)

                        print(f"Match detected at {timestamp:.1f}s (confidence: {max_val:.3f})")

            frame_count += 1

        cap.release()
        print(f"Detection complete. Found {len(detections)} matches.")

        return detections

    @staticmethod
    def save_detection_frame(detection: MatchDetection, output_path: str) -> None:
        """検出フレームを画像として保存"""
        cv2.imwrite(output_path, detection.frame)
