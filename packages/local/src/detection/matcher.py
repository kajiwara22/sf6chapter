"""
テンプレートマッチングによる対戦シーン検出
OpenCVを使用してフレームから対戦開始画面を検出
"""

from dataclasses import dataclass

import cv2
import numpy as np


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
        threshold: float = 0.4,
        min_interval_sec: float = 2.0,
        frame_interval: int = 2,
        reject_templates: list[str] | None = None,
        reject_threshold: float = 0.35,
        search_region: tuple[int, int, int, int] | None = None,
        post_check_frames: int = 10,
        post_check_reject_limit: int = 2,
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
        """
        self.template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if self.template is None:
            raise FileNotFoundError(f"Template image not found: {template_path}")

        # テンプレートを前処理（エッジ抽出）
        self.template_edges = self._preprocess_for_matching(self.template)

        # 除外用テンプレート（Round 2, Final Round）
        self.reject_templates_edges = []
        if reject_templates:
            for reject_path in reject_templates:
                reject_img = cv2.imread(reject_path, cv2.IMREAD_COLOR)
                if reject_img is not None:
                    reject_edges = self._preprocess_for_matching(reject_img)
                    self.reject_templates_edges.append(reject_edges)

        self.threshold = threshold
        self.reject_threshold = reject_threshold
        self.min_interval_sec = min_interval_sec
        self.frame_interval = frame_interval
        self.search_region = search_region
        self.post_check_frames = post_check_frames
        self.post_check_reject_limit = post_check_reject_limit

    @staticmethod
    def _preprocess_for_matching(image: np.ndarray) -> np.ndarray:
        """
        文字検出用の前処理: エッジ抽出
        背景の影響を除去して文字の輪郭を強調
        """
        # グレースケール化
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        # ガウシアンブラーでノイズ除去
        blurred = cv2.GaussianBlur(gray, (17, 17), 0)

        # Cannyエッジ検出
        edges = cv2.Canny(blurred, 50, 150)

        return edges

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
            frame_edges = self._preprocess_for_matching(search_frame)

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

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        start_frame = int(start_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        end_frame = start_frame + int(duration_sec * fps) if duration_sec is not None else total_frames

        detections: list[MatchDetection] = []
        frame_count = start_frame
        prev_timestamp: float | None = None

        print(f"Scanning video from {start_sec}s to {end_frame / fps:.1f}s...")
        print(f"Threshold is {self.threshold}")

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
                # 検索範囲を限定
                if self.search_region:
                    x1, y1, x2, y2 = self.search_region
                    search_frame = frame[y1:y2, x1:x2]
                else:
                    search_frame = frame

                # フレームを前処理（エッジ抽出）
                frame_edges = self._preprocess_for_matching(search_frame)

                # エッジ画像同士でマッチング
                result = cv2.matchTemplate(frame_edges, self.template_edges, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

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
                        print(f"Rejected match at {frame_count / fps:.1f}s - matched {reject_reason}")
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
                                print(
                                    f"Rejected match at {timestamp:.1f}s - subsequent frames have {subsequent_reject_count} reject matches (limit: {self.post_check_reject_limit})"
                                )
                                # 誤検知判定されたら、次のチェックまでスキップ
                                prev_timestamp = timestamp
                                frame_count += 1
                                continue

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
