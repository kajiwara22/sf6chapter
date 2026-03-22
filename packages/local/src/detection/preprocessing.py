"""
画像前処理ユーティリティ

複数のモジュールで共有される画像前処理関数を集約。
- テンプレートマッチング用: グレースケール化 → ノイズ除去 → エッジ検出
- キャラクター再認識用: ネガポジ反転（ADR-033）
"""

import cv2
import numpy as np


def preprocess_for_recognition(image: np.ndarray, method: str = "negative") -> np.ndarray:
    """
    キャラクター再認識用の画像前処理（ADR-033）

    Battlelogマッチング失敗時に、フレーム画像に前処理を適用して
    Gemini APIでの再認識精度を向上させる。

    Args:
        image: 入力画像 (BGR)
        method: 前処理手法名（"negative" のみサポート）

    Returns:
        前処理済み画像 (BGR)

    Raises:
        ValueError: サポートされていない前処理手法が指定された場合
    """
    if method == "negative":
        return cv2.bitwise_not(image)
    raise ValueError(f"Unsupported preprocessing method: {method}")


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
