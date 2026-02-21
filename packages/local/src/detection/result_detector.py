"""
対戦終了画面（RESULT画面）からの勝敗検出

OpenCVテンプレートマッチングを使用して、RESULT画面から
「Win」テキストの位置を検出し、勝者（player1 or player2）を判定。
"""

from dataclasses import dataclass

import cv2
import numpy as np

from ..utils.logger import get_logger

logger = get_logger()


@dataclass
class ResultDetection:
    """RESULT画面検出結果"""

    winner_side: str | None  # "player1" | "player2" | None
    detection_confidence: float  # マッチング信頼度 (0.0-1.0)
    win_position: str  # "left" | "right" | "unknown"
    detection_method: str  # "image_template_matching"


class ResultScreenDetector:
    """RESULT画面からの勝敗検出"""

    def __init__(
        self,
        result_template_paths: list[str] | str,
        win_template_paths: list[str] | str,
        result_threshold: float = 0.3,
        win_threshold: float = 0.3,
        result_screen_search_region: tuple[int, int, int, int] | None = None,
        win_text_search_region: tuple[int, int, int, int] | None = None,
    ):
        """
        初期化

        Args:
            result_template_paths: RESULT画面テンプレート画像のパス（文字列または配列）
            win_template_paths: 「Win」テキストテンプレート画像のパス（文字列または配列）
            result_threshold: RESULT画面検出の閾値 (0.0-1.0)
            win_threshold: Win位置検出の閾値 (0.0-1.0)
            result_screen_search_region: RESULT画面検出の検索領域 (x1, y1, x2, y2)、Noneで全体
            win_text_search_region: Win テキスト検出の検索領域 (x1, y1, x2, y2)、Noneで全体

        Raises:
            FileNotFoundError: テンプレートファイルが見つからない場合
        """
        # 文字列から配列に統一
        if isinstance(result_template_paths, str):
            result_template_paths = [result_template_paths]
        if isinstance(win_template_paths, str):
            win_template_paths = [win_template_paths]

        # RESULT画面テンプレート（複数対応）
        self.result_templates_edges: list[np.ndarray] = []
        for template_path in result_template_paths:
            template = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template is None:
                raise FileNotFoundError(f"Result template not found: {template_path}")
            template_edges = self._preprocess_for_matching(template)
            self.result_templates_edges.append(template_edges)

        # 「Win」テキストテンプレート（複数対応）
        self.win_templates_edges: list[np.ndarray] = []
        for template_path in win_template_paths:
            template = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template is None:
                raise FileNotFoundError(f"Win template not found: {template_path}")
            template_edges = self._preprocess_for_matching(template)
            self.win_templates_edges.append(template_edges)

        self.result_threshold = result_threshold
        self.win_threshold = win_threshold
        self.result_screen_search_region = result_screen_search_region
        self.win_text_search_region = win_text_search_region

    @staticmethod
    def _preprocess_for_matching(image: np.ndarray) -> np.ndarray:
        """
        テンプレートマッチング用の前処理：エッジ抽出

        Args:
            image: 入力画像 (BGR)

        Returns:
            エッジ抽出済みのグレースケール画像
        """
        # グレースケール化
        gray = (
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            if len(image.shape) == 3
            else image
        )

        # ガウシアンブラーでノイズ除去
        blurred = cv2.GaussianBlur(gray, (17, 17), 0)

        # Cannyエッジ検出
        edges = cv2.Canny(blurred, 50, 150)

        return edges

    def _has_result_screen(self, frame: np.ndarray) -> bool:
        """
        RESULT画面の存在確認（複数テンプレートのいずれかにマッチ）

        Args:
            frame: フレーム画像 (BGR)

        Returns:
            RESULT画面が検出されたかどうか
        """
        # 検索領域を適用
        if self.result_screen_search_region:
            x1, y1, x2, y2 = self.result_screen_search_region
            search_frame = frame[y1:y2, x1:x2]
        else:
            search_frame = frame

        frame_edges = self._preprocess_for_matching(search_frame)

        # 複数テンプレートのいずれかが閾値を超えたかチェック
        max_score = 0.0
        for template_edges in self.result_templates_edges:
            match_result = cv2.matchTemplate(
                frame_edges, template_edges, cv2.TM_CCOEFF_NORMED
            )
            max_val = match_result.max()
            max_score = max(max_score, max_val)

        is_detected = max_score >= self.result_threshold

        logger.debug(
            f"🔍 RESULT screen detection: "
            f"max_match_value={max_score:.3f} | threshold={self.result_threshold:.3f} | "
            f"templates_count={len(self.result_templates_edges)} | detected={is_detected}"
        )

        return is_detected

    def _get_win_position(self, frame: np.ndarray) -> str:
        """
        「Win」テキストの左右位置を判定（複数テンプレートのいずれかにマッチ）

        Args:
            frame: フレーム画像 (BGR)

        Returns:
            "left" | "right" | "unknown"
        """
        # 検索領域を適用
        if self.win_text_search_region:
            x1, y1, x2, y2 = self.win_text_search_region
            search_frame = frame[y1:y2, x1:x2]
            region_offset_x = x1
        else:
            search_frame = frame
            region_offset_x = 0

        frame_edges = self._preprocess_for_matching(search_frame)

        # 複数テンプレートのマッチ結果を集約
        all_win_matches = np.empty((0, 2), dtype=np.int64)
        for template_edges in self.win_templates_edges:
            matches = cv2.matchTemplate(
                frame_edges, template_edges, cv2.TM_CCOEFF_NORMED
            )
            # 閾値以上のマッチ位置を取得
            win_matches = np.argwhere(matches >= self.win_threshold)
            all_win_matches = np.vstack([all_win_matches, win_matches]) if len(win_matches) > 0 else all_win_matches

        if len(all_win_matches) == 0:
            logger.debug(f"   🔍 Win text detection: no matches (threshold={self.win_threshold:.3f}, templates_count={len(self.win_templates_edges)})")
            return "unknown"

        # 重心計算 (argwhereは(row, col)の順序なので注意)
        # 検索領域が指定されている場合、オフセットを加算
        centroid_x = np.mean(all_win_matches[:, 1]) + region_offset_x
        frame_width = frame.shape[1]
        frame_center = frame_width / 2
        position = "left" if centroid_x < frame_center else "right"

        logger.debug(
            f"   🔍 Win text detection: "
            f"match_count={len(all_win_matches)} | templates_count={len(self.win_templates_edges)} | centroid_x={centroid_x:.1f} | "
            f"frame_center={frame_center:.1f} | position={position}"
        )

        return position

    def detect_result(self, frame: np.ndarray) -> ResultDetection:
        """
        RESULT画面から勝敗を検出

        流れ:
        1. RESULT画面の存在確認
        2. 「Win」テキスト位置検出
        3. 左右判定 → winner_side を決定

        Args:
            frame: 対戦画面フレーム (BGR, 1080p推定)

        Returns:
            ResultDetection オブジェクト
        """
        result = ResultDetection(
            winner_side=None,
            detection_confidence=0.0,
            win_position="unknown",
            detection_method="image_template_matching",
        )

        # ステップ1: RESULT画面の存在確認
        logger.debug("  [Step 1] Checking RESULT screen presence...")
        if not self._has_result_screen(frame):
            logger.debug("  [Step 1] ❌ RESULT screen not detected")
            return result

        logger.debug("  [Step 1] ✅ RESULT screen detected")

        # ステップ2: 「Win」テキスト位置検出
        logger.debug("  [Step 2] Detecting Win text position...")
        win_position = self._get_win_position(frame)
        result.win_position = win_position

        if win_position in ["left", "right"]:
            result.winner_side = "player1" if win_position == "left" else "player2"
            result.detection_confidence = 0.8  # テンプレートマッチング信頼度

            logger.debug(
                f"  [Step 2] ✅ Result detected: "
                f"winner_side={result.winner_side} | "
                f"win_position={win_position} | "
                f"confidence={result.detection_confidence}"
            )
        else:
            logger.debug(
                f"  [Step 2] ⚠️ Win text position unknown: {win_position}"
            )

        return result
