"""
Gemini APIを使用したキャラクター認識（Vertex AI経由）
画像からSF6のキャラクター名を認識
"""

import json
import os
import time
from typing import Any

import cv2
import numpy as np
from google import genai
from google.genai import errors as genai_errors
from PIL import Image

from ..auth import get_oauth_credentials
from ..utils.logger import get_logger

logger = get_logger()

# 認識できなかった場合の定数
UNKNOWN_CHARACTER = "UNKNOWN"

# ADR-042: Vertex AI Flex PayGo のリトライ/タイムアウト設定
_FLEX_TIMEOUT_MS = 1_800_000  # 30分（Vertex AI Flex PayGo の最大タイムアウト）
_FLEX_MAX_RETRIES = 3
_FLEX_BASE_DELAY_SEC = 5

# ADR-042: Vertex AI Flex PayGo を使うためのリクエストヘッダー
# 公式: https://docs.cloud.google.com/vertex-ai/docs/flex-paygo
# "Flex PayGo only" モード（Provisioned Throughput を持っていない PayGo 用途）
_FLEX_PAYGO_HEADERS = {
    "X-Vertex-AI-LLM-Request-Type": "shared",
    "X-Vertex-AI-LLM-Shared-Request-Type": "flex",
}


class CharacterRecognizer:
    """Gemini APIを使用したキャラクター認識器（Vertex AI経由）"""

    def __init__(
        self,
        aliases_path: str,
        model_name: str = "gemini-3.1-flash-lite",
        client_secrets_file: str = "client_secrets.json",
        token_file: str = "token.pickle",
        project_id: str | None = None,
        location: str = "global",
        use_flex: bool = True,
    ):
        """
        Args:
            aliases_path: キャラクター名正規化マッピングファイルのパス（必須）
            model_name: 使用するモデル名（ADR-042: gemini-3.1-flash-lite）
            client_secrets_file: OAuth2クライアントシークレットファイルのパス
            token_file: 認証トークン保存ファイルのパス（pickle形式）
            project_id: Google Cloud プロジェクトID（省略時は環境変数GOOGLE_CLOUD_PROJECTを使用）
            location: Vertex AIのロケーション
                - ADR-042: gemini-3.1-flash-lite は us-central1 非対応のため "global" がデフォルト
                - 利用可能: global / us / eu
            use_flex: Vertex AI Flex PayGo を使うかどうか（ADR-042）
                - True: Flex PayGo（50% off、~30分まで待機、sheddable）。Standard へ自動フォールバックする。
                - False: Standard PayGo のみで実行
        """
        # OAuth2認証を使用（Vertex AI経由、YouTube APIと共通）
        project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            raise ValueError("GOOGLE_CLOUD_PROJECT must be set")

        creds = get_oauth_credentials(
            client_secrets_file=client_secrets_file,
            token_file=token_file,
        )

        # ADR-042: Vertex AI 上の Flex PayGo はヘッダーで指定する
        # （Gemini Developer API の `service_tier` パラメータとは別物。
        #  Vertex AI で `GenerateContentConfig.service_tier` を渡すと
        #  `400 INVALID_ARGUMENT` で拒否される）
        # Standard クライアント（Flex 失敗時のフォールバック用）も必ず1つ持っておく。
        self._project_id = project_id
        self._location = location
        self._credentials = creds

        self.standard_client = self._build_client(extra_headers=None)
        self.flex_client = self._build_client(extra_headers=_FLEX_PAYGO_HEADERS) if use_flex else None

        self.model_name = model_name
        self.use_flex = use_flex

        # キャラクター名正規化マッピング読み込み（必須）
        self.aliases_map: dict[str, str] = {}
        self.valid_characters: list[str] = []
        self._load_aliases(aliases_path)

    def _build_client(self, extra_headers: dict[str, str] | None) -> genai.Client:
        """Vertex AI 用の genai.Client を構築する（Flex/Standard で別インスタンスを使う）"""
        headers: dict[str, str] = {}
        if extra_headers:
            headers.update(extra_headers)
        http_options = genai.types.HttpOptions(
            api_version="v1",
            timeout=_FLEX_TIMEOUT_MS,
            headers=headers or None,
        )
        return genai.Client(
            vertexai=True,
            project=self._project_id,
            location=self._location,
            credentials=self._credentials,
            http_options=http_options,
        )

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

    # ---------------------------------------------------------------------
    # 内部ユーティリティ
    # ---------------------------------------------------------------------

    def _build_base_config_kwargs(self) -> dict[str, Any]:
        """ADR-019/042 で共通の GenerateContentConfig パラメータを返す"""
        # ADR-019: OCRタスク最適化のため低温度（temperature=0.1）
        # ADR-042: thinking_budget=0 で OCR に不要な thinking tokens 課金を回避
        # 注: Vertex AI では service_tier はパラメータではなくヘッダーで指定するため
        #     ここには載せない（_build_client 側で設定済み）
        return {
            "temperature": 0.1,
            "top_p": 0.95,
            "top_k": 40,
            "thinking_config": genai.types.ThinkingConfig(thinking_budget=0),
            "response_mime_type": "application/json",
        }

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """ADR-042: Flex の sheddable 性質に応じた 503/429 リトライ対象判定"""
        if isinstance(exc, genai_errors.APIError):
            code = getattr(exc, "code", None)
            return code in (429, 503)
        return False

    def _generate_with_retry(
        self,
        contents: list[Any],
        config: genai.types.GenerateContentConfig,
    ) -> Any:
        """
        ADR-042: Flex PayGo 用のリトライ + Standard フォールバック付き API 呼び出し

        1. Flex クライアント（ヘッダー付き）で実行
        2. 503/429 のときは指数バックオフでリトライ
        3. リトライ枯渇したら Standard クライアントで再試行
        """
        # use_flex=False のときは Standard で一発実行
        if self.flex_client is None:
            return self.standard_client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )

        # Flex リトライ
        last_exc: Exception | None = None
        for attempt in range(_FLEX_MAX_RETRIES):
            try:
                return self.flex_client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                if not self._is_retryable_error(exc):
                    raise
                last_exc = exc
                if attempt < _FLEX_MAX_RETRIES - 1:
                    delay = _FLEX_BASE_DELAY_SEC * (2**attempt)
                    logger.warning(
                        "Flex PayGo busy (attempt %d/%d): %s. Retrying in %ds...",
                        attempt + 1,
                        _FLEX_MAX_RETRIES,
                        exc,
                        delay,
                    )
                    time.sleep(delay)

        # Standard フォールバック
        logger.warning(
            "Flex PayGo retries exhausted (last error: %s). Falling back to Standard PayGo.",
            last_exc,
        )
        return self.standard_client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )

    # ---------------------------------------------------------------------
    # 個別認識（ADR-033 再認識フローや単発テストで使用）
    # ---------------------------------------------------------------------

    def _build_single_prompt(self) -> str:
        """ADR-019 のプロンプト（OCRタスク明示、JP/JAMIE混同防止）"""
        char_list = ", ".join(self.valid_characters)
        return (
            "あなたはOCR専門家です。この画像はストリートファイター6のラウンド開始画面です。\n"
            "画面上部に表示されているキャラクター名のテキストを1文字ずつ正確に読み取ってください。\n\n"
            "タスク: 左側（画面上部左）のキャラクター名を1p、右側（画面上部右）のキャラクター名を2pとして認識してください。\n\n"
            "【重要】文字数を必ず確認してください:\n"
            "- 'JP' は2文字のみです。絶対に 'JAMIE'（5文字）ではありません。\n"
            "- 'ED' は2文字のみです。絶対に 'E.HONDA'（7文字）ではありません。\n"
            "- 表示されている文字が2文字なら、その2文字だけを読み取ってください。\n"
            "- 表示されている文字が5文字なら、その5文字を読み取ってください。\n\n"
            "【認識手順】\n"
            "1. 画面上部の左右を確認\n"
            "2. それぞれの文字数を数える\n"
            "3. 表示されている文字を正確に読み取る\n"
            "4. 下記のリストから完全一致するものを選ぶ\n\n"
            f"有効なキャラクター名（必ずこの中から選んでください）:\n{char_list}\n\n"
            "例:\n"
            '- 画面に "JP" と "RYU" が表示 → {"1p": "JP", "2p": "RYU"}\n'
            '- 画面に "JAMIE" と "KEN" が表示 → {"1p": "JAMIE", "2p": "KEN"}\n\n'
            '出力形式: {"1p": "RYU", "2p": "KEN"}'
        )

    def recognize_from_frame(
        self,
        frame: np.ndarray,
        save_debug_image: str | None = None,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """
        フレーム画像からキャラクターを認識（1リクエスト）

        Args:
            frame: OpenCV形式のフレーム（BGR）
            save_debug_image: デバッグ用画像保存パス（オプション）

        Returns:
            (正規化済み結果, 生の認識結果)のタプル
        """
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(frame_rgb)

        if save_debug_image:
            pil_image.save(save_debug_image)

        prompt = self._build_single_prompt()
        config_kwargs = self._build_base_config_kwargs()
        config_kwargs["response_schema"] = {
            "type": "object",
            "properties": {
                "1p": {"type": "string", "enum": self.valid_characters},
                "2p": {"type": "string", "enum": self.valid_characters},
            },
            "required": ["1p", "2p"],
        }
        config = genai.types.GenerateContentConfig(**config_kwargs)

        logger.debug(
            "Calling Gemini API (model=%s, tier=%s) for single frame",
            self.model_name,
            "flex" if self.use_flex else "standard",
        )
        response = self._generate_with_retry(contents=[prompt, pil_image], config=config)
        raw_result = json.loads(response.text)

        normalized_result = {
            "1p": self.normalize_character_name(raw_result.get("1p", "")),
            "2p": self.normalize_character_name(raw_result.get("2p", "")),
        }

        if normalized_result["1p"] == UNKNOWN_CHARACTER:
            logger.warning("Failed to recognize 1p character, raw: %s", raw_result.get("1p"))
        if normalized_result["2p"] == UNKNOWN_CHARACTER:
            logger.warning("Failed to recognize 2p character, raw: %s", raw_result.get("2p"))

        return normalized_result, raw_result

    def recognize_with_preprocessing(
        self,
        frame: np.ndarray,
        method: str = "negative",
    ) -> tuple[dict[str, str], dict[str, str]]:
        """
        前処理を適用してからキャラクターを再認識（ADR-033）

        ADR-042: 再認識は対象が 1〜数フレームに限定されるためバッチ化せず個別送信のまま維持する。

        Args:
            frame: OpenCV形式のフレーム（BGR）
            method: 前処理手法名（デフォルト: "negative"）

        Returns:
            (正規化済み結果, 生の認識結果)のタプル
        """
        from ..detection.preprocessing import preprocess_for_recognition

        preprocessed = preprocess_for_recognition(frame, method=method)
        return self.recognize_from_frame(preprocessed)

    # ---------------------------------------------------------------------
    # バッチ認識（ADR-042）
    # ---------------------------------------------------------------------

    def _build_batch_prompt(self, num_images: int) -> str:
        """ADR-042: バッチ送信用プロンプト（検証Notebookで100%一致を達成したもの）"""
        char_list = ", ".join(self.valid_characters)
        return (
            "あなたはOCR専門家です。以下の複数画像はそれぞれストリートファイター6のラウンド開始画面です。\n"
            f"画像は image 1 から image {num_images} までの順番で提示されます。\n"
            "各画像について、画面上部左のキャラクター名を1p、右側のキャラクター名を2pとして認識してください。\n\n"
            "【重要】文字数を必ず確認してください:\n"
            "- 'JP' は2文字のみです。絶対に 'JAMIE'（5文字）ではありません。\n"
            "- 'ED' は2文字のみです。絶対に 'E.HONDA'（7文字）ではありません。\n\n"
            f"有効なキャラクター名（必ずこの中から選んでください）:\n{char_list}\n\n"
            "出力形式（必ず index を含めてください、image 1 → index=1 のように1始まり）:\n"
            '{"results": [{"index": 1, "1p": "RYU", "2p": "KEN"}, {"index": 2, "1p": "...", "2p": "..."}]}'
        )

    def recognize_from_frames(
        self,
        frames: list[np.ndarray],
    ) -> list[tuple[dict[str, str], dict[str, str]]]:
        """
        複数フレームを1リクエストで一括認識（ADR-042）

        バッチ送信が失敗 or 一部 index が欠損した場合は、該当フレームのみ個別送信にフォールバックする。

        Args:
            frames: OpenCV形式のフレームリスト

        Returns:
            各フレームの (正規化済み結果, 生の認識結果) リスト（入力順）
        """
        if not frames:
            return []

        num = len(frames)

        # バッチ送信を試行
        try:
            batch_raw = self._call_batch_api(frames)
        except Exception:
            logger.exception(
                "Batch recognition failed entirely. Falling back to individual recognition for all %d frames.",
                num,
            )
            return self._recognize_individually(frames)

        # index でレスポンスを正規化（1始まり）
        results_by_index: dict[int, dict[str, str]] = {}
        for item in batch_raw.get("results", []):
            idx = item.get("index")
            if isinstance(idx, int) and 1 <= idx <= num:
                results_by_index[idx] = item

        results: list[tuple[dict[str, str], dict[str, str]]] = []
        missing_indices: list[int] = []
        for i in range(1, num + 1):
            item = results_by_index.get(i)
            if item is None:
                missing_indices.append(i)
                results.append(({}, {}))  # プレースホルダ、後でフォールバック値で置換
                continue
            raw = {"1p": item.get("1p", ""), "2p": item.get("2p", "")}
            normalized = {
                "1p": self.normalize_character_name(raw["1p"]),
                "2p": self.normalize_character_name(raw["2p"]),
            }
            if normalized["1p"] == UNKNOWN_CHARACTER:
                logger.warning("Batch index=%d: failed to recognize 1p, raw=%s", i, raw["1p"])
            if normalized["2p"] == UNKNOWN_CHARACTER:
                logger.warning("Batch index=%d: failed to recognize 2p, raw=%s", i, raw["2p"])
            results.append((normalized, raw))

        # 欠損 index は個別送信でフォールバック
        if missing_indices:
            logger.warning(
                "Batch response missing %d index(es): %s. Falling back to individual recognition.",
                len(missing_indices),
                missing_indices,
            )
            for idx in missing_indices:
                try:
                    results[idx - 1] = self.recognize_from_frame(frames[idx - 1])
                except Exception:
                    logger.exception("Individual fallback failed for index=%d", idx)
                    results[idx - 1] = (
                        {"1p": UNKNOWN_CHARACTER, "2p": UNKNOWN_CHARACTER},
                        {"1p": "", "2p": ""},
                    )

        return results

    def _call_batch_api(self, frames: list[np.ndarray]) -> dict[str, Any]:
        """バッチ送信本体。レスポンス JSON を辞書で返す（リトライ/フォールバックは _generate_with_retry に委譲）"""
        pil_images = []
        for frame in frames:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_images.append(Image.fromarray(frame_rgb))

        prompt = self._build_batch_prompt(len(frames))
        contents = [prompt, *pil_images]

        config_kwargs = self._build_base_config_kwargs()
        config_kwargs["response_schema"] = {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "1p": {"type": "string", "enum": self.valid_characters},
                            "2p": {"type": "string", "enum": self.valid_characters},
                        },
                        "required": ["index", "1p", "2p"],
                    },
                },
            },
            "required": ["results"],
        }
        config = genai.types.GenerateContentConfig(**config_kwargs)

        logger.info(
            "Calling Gemini batch API: %d frames in 1 request (model=%s, tier=%s)",
            len(frames),
            self.model_name,
            "flex" if self.use_flex else "standard",
        )
        response = self._generate_with_retry(contents=contents, config=config)
        return json.loads(response.text)

    def _recognize_individually(
        self,
        frames: list[np.ndarray],
    ) -> list[tuple[dict[str, str], dict[str, str]]]:
        """全フレームを個別送信で処理（バッチ送信が完全失敗した時のフォールバック）"""
        results: list[tuple[dict[str, str], dict[str, str]]] = []
        for i, frame in enumerate(frames, 1):
            try:
                results.append(self.recognize_from_frame(frame))
            except Exception:
                logger.exception("Individual fallback failed for frame %d", i)
                results.append(
                    (
                        {"1p": UNKNOWN_CHARACTER, "2p": UNKNOWN_CHARACTER},
                        {"1p": "", "2p": ""},
                    )
                )
        return results

    # ---------------------------------------------------------------------
    # 旧 API 互換: recognize_batch は recognize_from_frames に委譲
    # ---------------------------------------------------------------------

    def recognize_batch(
        self,
        frames: list[np.ndarray],
    ) -> list[tuple[dict[str, str], dict[str, str]]]:
        """
        複数フレームを認識（ADR-042 以降は内部的に1リクエストにまとめて送信）

        後方互換のためのエイリアス。新規実装は recognize_from_frames を直接使うことを推奨。
        """
        return self.recognize_from_frames(frames)
