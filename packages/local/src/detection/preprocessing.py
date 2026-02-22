"""
テンプレートマッチング用の画像前処理ユーティリティ

複数のモジュールで共有される画像前処理関数を集約。
グレースケール化 → ノイズ除去 → エッジ検出
"""

import cv2
import numpy as np


def preprocess_for_matching(image: np.ndarray) -> np.ndarray:
    """
    テンプレートマッチング用の画像前処理

    背景の影響を除去して文字の輪郭を強調します。

    Args:
        image: 入力画像 (BGR または グレースケール)

    Returns:
        エッジ抽出済みのグレースケール画像
    """
    # グレースケール化
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

    # ガウシアンブラーでノイズ除去
    blurred = cv2.GaussianBlur(gray, (17, 17), 0)

    # Cannyエッジ検出
    edges = cv2.Canny(blurred, 50, 150)

    return edges
