"""
RESULT画面検出器のテスト

ResultScreenDetector の機能をテストします。
"""

import pytest
import numpy as np
import cv2
from pathlib import Path

from src.detection import ResultScreenDetector, ResultDetection


class TestResultScreenDetector:
    """ResultScreenDetector のテストクラス"""

    @pytest.fixture
    def dummy_templates(self, tmp_path):
        """ダミーテンプレート画像を作成"""
        # RESULT画面テンプレート（白い矩形）
        result_template = np.ones((100, 200, 3), dtype=np.uint8) * 255
        cv2.putText(result_template, "RESULT", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
        result_path = tmp_path / "result_screen.png"
        cv2.imwrite(str(result_path), result_template)

        # Win テキストテンプレート（白い矩形）
        win_template = np.ones((80, 100, 3), dtype=np.uint8) * 255
        cv2.putText(win_template, "Win", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
        win_path = tmp_path / "win_text.png"
        cv2.imwrite(str(win_path), win_template)

        return str(result_path), str(win_path)

    def test_initialization_success(self, dummy_templates):
        """正常な初期化テスト"""
        result_path, win_path = dummy_templates

        detector = ResultScreenDetector(
            result_template_path=result_path,
            win_template_path=win_path,
        )

        assert detector is not None
        assert detector.result_template is not None
        assert detector.win_template is not None
        assert detector.result_threshold == 0.3
        assert detector.win_threshold == 0.3

    def test_initialization_missing_result_template(self, dummy_templates):
        """result_template が見つからない場合のテスト"""
        _, win_path = dummy_templates

        with pytest.raises(FileNotFoundError):
            ResultScreenDetector(
                result_template_path="/nonexistent/path.png",
                win_template_path=win_path,
            )

    def test_initialization_missing_win_template(self, dummy_templates):
        """win_template が見つからない場合のテスト"""
        result_path, _ = dummy_templates

        with pytest.raises(FileNotFoundError):
            ResultScreenDetector(
                result_template_path=result_path,
                win_template_path="/nonexistent/path.png",
            )

    def test_detect_result_no_detection(self, dummy_templates):
        """RESULT画面が検出されない場合のテスト"""
        result_path, win_path = dummy_templates
        detector = ResultScreenDetector(
            result_template_path=result_path,
            win_template_path=win_path,
        )

        # 真っ黒なフレーム（RESULT画面がない）
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        result = detector.detect_result(frame)

        assert isinstance(result, ResultDetection)
        assert result.winner_side is None
        assert result.detection_confidence == 0.0
        assert result.win_position == "unknown"
        assert result.detection_method == "image_template_matching"

    def test_detect_result_with_template_in_frame(self, dummy_templates, tmp_path):
        """テンプレートがフレーム内に含まれる場合のテスト"""
        result_path, win_path = dummy_templates
        detector = ResultScreenDetector(
            result_template_path=result_path,
            win_template_path=win_path,
        )

        # フレーム作成（RESULT テンプレートと Win テンプレートを配置）
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        # テンプレートを読み込んでフレームに埋め込み
        result_tmpl = cv2.imread(result_path)
        win_tmpl = cv2.imread(win_path)

        # RESULT テンプレートを左上に配置
        frame[0:result_tmpl.shape[0], 0:result_tmpl.shape[1]] = result_tmpl

        # Win テンプレート（左側）を配置
        y_offset = 200
        x_offset = 100
        frame[y_offset:y_offset + win_tmpl.shape[0], x_offset:x_offset + win_tmpl.shape[1]] = win_tmpl

        result = detector.detect_result(frame)

        # 高い信頼度で検出されることを期待
        assert result.winner_side is not None or result.win_position != "unknown"

    def test_preprocess_for_matching(self, dummy_templates):
        """画像前処理（エッジ抽出）のテスト"""
        result_path, win_path = dummy_templates
        detector = ResultScreenDetector(
            result_template_path=result_path,
            win_template_path=win_path,
        )

        # テスト画像
        img = np.ones((100, 200, 3), dtype=np.uint8) * 128
        cv2.rectangle(img, (20, 20), (180, 80), (255, 255, 255), -1)

        # 前処理実行
        edges = detector._preprocess_for_matching(img)

        # 結果の確認
        assert isinstance(edges, np.ndarray)
        assert edges.dtype == np.uint8
        assert edges.shape == (100, 200)  # グレースケール化、エッジ抽出
        assert edges.max() > 0  # エッジが抽出されている

    def test_custom_thresholds(self, dummy_templates):
        """カスタム閾値での初期化テスト"""
        result_path, win_path = dummy_templates

        detector = ResultScreenDetector(
            result_template_path=result_path,
            win_template_path=win_path,
            result_threshold=0.5,
            win_threshold=0.4,
        )

        assert detector.result_threshold == 0.5
        assert detector.win_threshold == 0.4

    def test_result_detection_dataclass(self):
        """ResultDetection データクラスのテスト"""
        detection = ResultDetection(
            winner_side="player1",
            detection_confidence=0.8,
            win_position="left",
            detection_method="image_template_matching",
        )

        assert detection.winner_side == "player1"
        assert detection.detection_confidence == 0.8
        assert detection.win_position == "left"
        assert detection.detection_method == "image_template_matching"

    def test_result_detection_none_winner(self):
        """勝者が検出されない場合のテスト"""
        detection = ResultDetection(
            winner_side=None,
            detection_confidence=0.0,
            win_position="unknown",
            detection_method="image_template_matching",
        )

        assert detection.winner_side is None
        assert detection.detection_confidence == 0.0
        assert detection.win_position == "unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
