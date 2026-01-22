"""
Gemini APIを使用したキャラクター認識（Vertex AI経由）
画像からSF6のキャラクター名を認識
"""

import json
import os

import cv2
import numpy as np
from google import genai
from PIL import Image

from ..auth import get_oauth_credentials
from ..utils.logger import get_logger

logger = get_logger()

# 認識できなかった場合の定数
UNKNOWN_CHARACTER = "UNKNOWN"


class CharacterRecognizer:
    """Gemini APIを使用したキャラクター認識器（Vertex AI経由）"""

    def __init__(
        self,
        aliases_path: str,
        model_name: str = "gemini-2.5-flash-lite",
        client_secrets_file: str = "client_secrets.json",
        token_file: str = "token.pickle",
        project_id: str | None = None,
        location: str = "us-central1",
    ):
        """
        Args:
            aliases_path: キャラクター名正規化マッピングファイルのパス（必須）
            model_name: 使用するモデル名
            client_secrets_file: OAuth2クライアントシークレットファイルのパス
            token_file: 認証トークン保存ファイルのパス（pickle形式）
            project_id: Google Cloud プロジェクトID（省略時は環境変数GOOGLE_CLOUD_PROJECTを使用）
            location: Vertex AIのロケーション（デフォルト: us-central1）
        """
        # OAuth2認証を使用（Vertex AI経由、YouTube APIと共通）
        project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            raise ValueError("GOOGLE_CLOUD_PROJECT must be set")

        creds = get_oauth_credentials(
            client_secrets_file=client_secrets_file,
            token_file=token_file,
        )
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            credentials=creds,
        )

        self.model_name = model_name

        # キャラクター名正規化マッピング読み込み（必須）
        self.aliases_map: dict[str, str] = {}
        self.valid_characters: list[str] = []
        self._load_aliases(aliases_path)

    def _load_aliases(self, aliases_path: str) -> None:
        """キャラクター名正規化マッピングを読み込み"""
        with open(aliases_path, encoding="utf-8") as f:
            data = json.load(f)

        # エイリアスから正規名へのマッピングを構築
        # 有効なキャラクター名リストも同時に構築
        for char_data in data["characters"].values():
            canonical = char_data["canonical"]
            self.valid_characters.append(canonical)
            for alias in char_data["aliases"]:
                self.aliases_map[alias.lower()] = canonical

    def is_valid_character(self, name: str) -> bool:
        """指定された名前が有効なキャラクター名かどうかを判定"""
        return name in self.valid_characters

    def normalize_character_name(self, raw_name: str) -> str:
        """
        キャラクター名を正規化

        Args:
            raw_name: Gemini APIから返された生の名前

        Returns:
            正規化されたキャラクター名（無効な場合はUNKNOWN_CHARACTER）
        """
        if not raw_name:
            return UNKNOWN_CHARACTER
        normalized = self.aliases_map.get(raw_name.lower())
        if normalized is None:
            logger.warning("Unknown character name from Gemini: %s", raw_name)
            return UNKNOWN_CHARACTER
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

        # 有効なキャラクター名リスト
        valid_chars = self.valid_characters

        # プロンプト（候補リストを含める）
        char_list = ", ".join(valid_chars)
        prompt = (
            "この画像はストリートファイター6のラウンド開始画面です。\n"
            "左側のキャラクターを1p、右側のキャラクターを2pとし、"
            "それぞれのキャラクター名をJSONで返してください。\n\n"
            f"有効なキャラクター名（必ずこの中から選んでください）:\n{char_list}\n\n"
            '出力形式: {"1p": "RYU", "2p": "KEN"}'
        )

        # Gemini API呼び出し（スキーマ制約付き）
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[prompt, pil_image],
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {
                        "1p": {"type": "string", "enum": valid_chars},
                        "2p": {"type": "string", "enum": valid_chars},
                    },
                    "required": ["1p", "2p"],
                },
            ),
        )

        # レスポンスパース
        raw_result = json.loads(response.text)

        # キャラクター名正規化と検証
        normalized_result = {
            "1p": self.normalize_character_name(raw_result.get("1p", "")),
            "2p": self.normalize_character_name(raw_result.get("2p", "")),
        }

        # 認識失敗のログ出力
        if normalized_result["1p"] == UNKNOWN_CHARACTER:
            logger.warning("Failed to recognize 1p character, raw: %s", raw_result.get("1p"))
        if normalized_result["2p"] == UNKNOWN_CHARACTER:
            logger.warning("Failed to recognize 2p character, raw: %s", raw_result.get("2p"))

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
            except Exception:
                logger.exception("Error recognizing frame %d", i)
                results.append(({}, {}))

        return results
