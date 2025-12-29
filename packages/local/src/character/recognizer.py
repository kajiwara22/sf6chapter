"""
Gemini APIを使用したキャラクター認識
画像からSF6のキャラクター名を認識
"""

import json
import os

import cv2
import google.generativeai as genai
import numpy as np
from PIL import Image


class CharacterRecognizer:
    """Gemini APIを使用したキャラクター認識器"""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.0-flash-exp",
        aliases_path: str | None = None,
    ):
        """
        Args:
            api_key: Gemini API Key（省略時は環境変数GEMINI_API_KEYを使用）
            model_name: 使用するモデル名
            aliases_path: キャラクター名正規化マッピングファイルのパス
        """
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY must be set")

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

        # キャラクター名正規化マッピング読み込み
        self.aliases_map: dict[str, str] = {}
        if aliases_path:
            self._load_aliases(aliases_path)

    def _load_aliases(self, aliases_path: str) -> None:
        """キャラクター名正規化マッピングを読み込み"""
        with open(aliases_path, encoding="utf-8") as f:
            data = json.load(f)

        # エイリアスから正規名へのマッピングを構築
        for char_data in data["characters"].values():
            canonical = char_data["canonical"]
            for alias in char_data["aliases"]:
                self.aliases_map[alias.lower()] = canonical

    def normalize_character_name(self, raw_name: str) -> str:
        """
        キャラクター名を正規化

        Args:
            raw_name: Gemini APIから返された生の名前

        Returns:
            正規化されたキャラクター名
        """
        normalized = self.aliases_map.get(raw_name.lower(), raw_name)
        return normalized

    def recognize_from_frame(
        self,
        frame: np.ndarray,
        save_debug_image: str | None = None,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """
        フレーム画像からキャラクターを認識

        Args:
            frame: OpenCV形式のフレーム（BGR）
            save_debug_image: デバッグ用画像保存パス（オプション）

        Returns:
            (正規化済み結果, 生の認識結果)のタプル
            例: ({"1p": "Ryu", "2p": "Ken"}, {"1p": "リュウ", "2p": "ケン"})
        """
        # OpenCV画像をPIL.Imageに変換
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(frame_rgb)

        # デバッグ画像保存
        if save_debug_image:
            pil_image.save(save_debug_image)

        # プロンプト
        prompt = (
            "この画像はストリートファイター6のラウンド開始画面です。"
            "左側のキャラクターを1p、右側のキャラクターを2pとし、"
            "それぞれのキャラクター名をJSONで返してください。"
            '例: {"1p": "Ryu", "2p": "Ken"}'
        )

        # Gemini API呼び出し
        response = self.model.generate_content(
            [prompt, pil_image],
            generation_config=genai.types.GenerationConfig(response_mime_type="application/json"),
        )

        # レスポンスパース
        raw_result = json.loads(response.text)

        # キャラクター名正規化
        normalized_result = {
            "1p": self.normalize_character_name(raw_result.get("1p", "")),
            "2p": self.normalize_character_name(raw_result.get("2p", "")),
        }

        return normalized_result, raw_result

    def recognize_batch(
        self,
        frames: list[np.ndarray],
    ) -> list[tuple[dict[str, str], dict[str, str]]]:
        """
        複数フレームを一括認識

        Args:
            frames: OpenCV形式のフレームリスト

        Returns:
            各フレームの認識結果リスト
        """
        results = []
        for i, frame in enumerate(frames):
            try:
                result = self.recognize_from_frame(frame)
                results.append(result)
            except Exception as e:
                print(f"Error recognizing frame {i}: {e}")
                results.append(({}, {}))

        return results
