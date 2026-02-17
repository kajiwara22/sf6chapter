#!/usr/bin/env python3
"""
SF6 Battlelog マッピング処理

YouTubeのチャプター情報とBattlelogの対戦ログをマッピングし、
勝敗情報を付与する。
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger()


class CharacterNormalizer:
    """キャラクター名の正規化"""

    def __init__(self, aliases_file: Optional[str] = None):
        """
        Args:
            aliases_file: character_aliases.json のパス
        """
        self.aliases_map = {}
        if aliases_file and Path(aliases_file).exists():
            self._load_aliases(aliases_file)
        else:
            # デフォルトの簡易マッピング
            self._setup_default_aliases()

    def _load_aliases(self, file_path: str) -> None:
        """aliases ファイルから読み込み"""
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
            for char_key, char_data in data.get("characters", {}).items():
                canonical = char_data.get("canonical", char_key)
                for alias in char_data.get("aliases", []):
                    self.aliases_map[alias.lower()] = canonical

    def _setup_default_aliases(self) -> None:
        """デフォルトの正規化マッピング"""
        self.aliases_map = {
            # Akuma / Gouki
            "akuma": "GOUKI",
            "豪鬼": "GOUKI",
            "gouki": "GOUKI",
            # JP
            "jp": "JP",
            "j.p.": "JP",
            "ジェイピー": "JP",
            # Blanka
            "blanka": "BLANKA",
            "ブランカ": "BLANKA",
            # Chun-Li
            "chun-li": "CHUN-LI",
            "chunli": "CHUN-LI",
            "春麗": "CHUN-LI",
            # Dhalsim
            "dhalsim": "DHALSIM",
            "ダルシム": "DHALSIM",
            # Dee Jay
            "dee jay": "DEE JAY",
            "deejay": "DEE JAY",
            "ディージェイ": "DEE JAY",
            # Guile
            "guile": "GUILE",
            "ガイル": "GUILE",
            # Marisa
            "marisa": "MARISA",
            "マリーザ": "MARISA",
            # Manon
            "manon": "MANON",
            "マノン": "MANON",
            # Ryu
            "ryu": "RYU",
            "リュウ": "RYU",
            # Ken
            "ken": "KEN",
            "ケン": "KEN",
            # Mai
            "mai": "MAI",
            "マイ": "MAI",
            "不知火舞": "MAI",
            # Ed
            "ed": "ED",
            "エド": "ED",
        }

    def normalize(self, name: str) -> str:
        """
        キャラクター名を正規化

        Args:
            name: キャラクター名（大文字小文字混在、日本語など）

        Returns:
            正規化されたキャラクター名（大文字）
        """
        normalized = self.aliases_map.get(name.lower(), name.upper())
        return normalized


class BattlelogMatcher:
    """Battlelogマッチング処理"""

    def __init__(self, normalizer: CharacterNormalizer):
        self.normalizer = normalizer

    def extract_chapter_characters(self, chapter_title: str) -> Optional[tuple[str, str]]:
        """
        チャプターのタイトルからキャラクター名を抽出

        Args:
            chapter_title: チャプタータイトル（例: "GOUKI VS JP"）

        Returns:
            (char1, char2) または None
        """
        if " VS " not in chapter_title:
            return None

        parts = chapter_title.split(" VS ")
        if len(parts) != 2:
            return None

        char1 = parts[0].strip()
        char2 = parts[1].strip()
        return (char1, char2)

    def extract_battlelog_characters(
        self, replay: dict[str, Any]
    ) -> tuple[str, str]:
        """
        Battlelogレコードからキャラクター名を抽出

        Args:
            replay: Battlelogのレプレイ情報

        Returns:
            (char1, char2)
        """
        # playing_character_tool_name を優先、フォールバック として character_name
        p1_char = (
            replay.get("player1_info", {}).get("playing_character_tool_name")
            or replay.get("player1_info", {}).get("character_name", "Unknown")
        )
        p2_char = (
            replay.get("player2_info", {}).get("playing_character_tool_name")
            or replay.get("player2_info", {}).get("character_name", "Unknown")
        )
        return (p1_char, p2_char)

    def extract_battle_results(
        self, replay: dict[str, Any]
    ) -> tuple[str, str]:
        """
        Battlelogレコードから各プレイヤーの勝敗を判定

        Args:
            replay: Battlelogのレプレイ情報

        Returns:
            (player1_result, player2_result) - "win" または "loss"
        """
        p1_results = replay.get("player1_info", {}).get("round_results", [])
        p2_results = replay.get("player2_info", {}).get("round_results", [])

        p1_wins = sum(1 for r in p1_results if r > 0)
        p2_wins = sum(1 for r in p2_results if r > 0)

        # 勝敗を判定
        if p1_wins > p2_wins:
            p1_result = "win"
            p2_result = "loss"
        else:
            p1_result = "loss"
            p2_result = "win"

        return (p1_result, p2_result)

    def _determine_confidence_level(self, time_diff: float) -> str:
        """
        時間差に基づいて信頼度レベルを決定

        仕様に従う:
        - high: 時間差180秒以内
        - medium: 時間差180〜600秒
        - low: キャラクター不一致 またはマッチなし（この関数では呼ばれない）

        Args:
            time_diff: 時刻差（秒）

        Returns:
            信頼度レベル ("high" | "medium")
        """
        if time_diff <= 180:
            return "high"
        elif time_diff <= 600:
            return "medium"
        else:
            return "low"

    def match_chapter_with_battlelog(
        self,
        chapter: dict[str, Any],
        battlelog_replays: list[dict[str, Any]],
        video_published_at: str,
        used_replay_ids: set[str],
        tolerance_seconds: int = 600,  # 最大 10分
    ) -> dict[str, Any]:
        """
        チャプターをBattlelogの対戦と照合

        マッピングロジック:
        1. チャプター推定時刻 = 配信開始時刻 + startTime
        2. キャラクター名を照合（文字揺れ吸収）
        3. 時間差が最小のリプレイを選択
        4. 時間差600秒超は失敗、重複排除

        Args:
            chapter: チャプター情報
            battlelog_replays: Battlelogの対戦ログ（アップロード時刻昇順）
            video_published_at: 動画公開日時（ISO 8601）
            used_replay_ids: 既にマッチ済みのリプレイID集合
            tolerance_seconds: 時刻差の許容範囲（秒、デフォルト: 600秒=10分）

        Returns:
            マッピング結果
            {
                "matched": bool,
                "confidence": "high" | "medium" | "low",
                "player1_character": str | None,
                "player1_result": "win" | "loss" | None,
                "player2_character": str | None,
                "player2_result": "win" | "loss" | None,
                "replay_id": str | None,
                "uploaded_at": int | None,
                "time_difference_seconds": int | None,
                "details": str,
            }
        """
        chapter_title = chapter.get("title", "")
        start_time = chapter.get("startTime", 0)

        # ステップ1: チャプターのキャラクター名を抽出
        chapter_chars = self.extract_chapter_characters(chapter_title)
        if not chapter_chars:
            logger.info(f"  ✗ {start_time}s: {chapter_title} - VS抽出失敗")
            return {
                "matched": False,
                "confidence": "low",
                "player1_character": None,
                "player1_result": None,
                "player2_character": None,
                "player2_result": None,
                "replay_id": None,
                "uploaded_at": None,
                "time_difference_seconds": None,
                "details": f"Failed to extract characters from title: {chapter_title}",
            }

        chapter_char1, chapter_char2 = chapter_chars
        chapter_chars_set = {
            self.normalizer.normalize(chapter_char1),
            self.normalizer.normalize(chapter_char2),
        }

        logger.debug(
            f"  チャプター {start_time}s: {chapter_title} "
            f"→ {chapter_chars_set}"
        )

        # ステップ1: 動画公開日時をパース
        try:
            video_time = datetime.fromisoformat(
                video_published_at.replace("Z", "+00:00")
            )
        except Exception as e:
            logger.error(f"Failed to parse video_published_at: {e}")
            return {
                "matched": False,
                "confidence": "low",
                "player1_character": None,
                "player1_result": None,
                "player2_character": None,
                "player2_result": None,
                "replay_id": None,
                "uploaded_at": None,
                "time_difference_seconds": None,
                "details": f"Failed to parse video_published_at: {e}",
            }

        # チャプターの推定絶対時刻を計算
        chapter_absolute_time = video_time + timedelta(seconds=start_time)

        # ステップ2&3: キャラクター一致 + 時間差最小のリプレイを探す
        best_match = None
        min_time_diff = float("inf")

        for replay in battlelog_replays:
            replay_id = replay.get("replay_id")

            # 既にマッチ済みならスキップ
            if replay_id in used_replay_ids:
                continue

            # キャラクターを抽出・正規化
            p1_char, p2_char = self.extract_battlelog_characters(replay)
            battlelog_chars_set = {
                self.normalizer.normalize(p1_char),
                self.normalizer.normalize(p2_char),
            }

            # ステップ2: キャラクター名が一致するか？
            if chapter_chars_set != battlelog_chars_set:
                continue

            # 時刻をチェック
            uploaded_at = replay.get("uploaded_at")
            if not uploaded_at:
                continue

            try:
                replay_time = datetime.fromtimestamp(uploaded_at, tz=timezone.utc)
                time_diff = (replay_time - chapter_absolute_time).total_seconds()

                # ステップ3: 時間差が正か、許容範囲内か確認
                # リプレイは試合後のアップロードなので、時間差は正の値になるはず
                if time_diff < 0:
                    # マッチング対象外（チャプター時刻より前のアップロード）
                    continue

                if time_diff > tolerance_seconds:
                    # 許容範囲外（10分超）
                    continue

                # 時間差が最小のものを記録
                if time_diff < min_time_diff:
                    min_time_diff = time_diff
                    p1_result, p2_result = self.extract_battle_results(replay)
                    confidence = self._determine_confidence_level(time_diff)

                    best_match = {
                        "replay_id": replay_id,
                        "uploaded_at": uploaded_at,
                        "time_difference": time_diff,
                        "player1_character": p1_char,
                        "player1_result": p1_result,
                        "player2_character": p2_char,
                        "player2_result": p2_result,
                        "confidence": confidence,
                    }

            except Exception as e:
                logger.debug(f"Failed to process replay: {e}")
                continue

        # ステップ4: マッチング結果の検証
        if not best_match:
            logger.info(f"  ✗ {start_time}s: {chapter_title} - マッチなし")
            return {
                "matched": False,
                "confidence": "low",
                "player1_character": None,
                "player1_result": None,
                "player2_character": None,
                "player2_result": None,
                "replay_id": None,
                "uploaded_at": None,
                "time_difference_seconds": None,
                "details": f"No matching replay found within {tolerance_seconds}s",
            }

        logger.info(
            f"  ✓ {start_time}s: {chapter_title} - "
            f"replay_id={best_match['replay_id']}, "
            f"{best_match['player1_character']}({best_match['player1_result']}) vs "
            f"{best_match['player2_character']}({best_match['player2_result']}), "
            f"confidence={best_match['confidence']}, "
            f"time_diff={best_match['time_difference']:.1f}s"
        )

        return {
            "matched": True,
            "confidence": best_match["confidence"],
            "player1_character": best_match["player1_character"],
            "player1_result": best_match["player1_result"],
            "player2_character": best_match["player2_character"],
            "player2_result": best_match["player2_result"],
            "replay_id": best_match["replay_id"],
            "uploaded_at": best_match["uploaded_at"],
            "time_difference_seconds": int(best_match["time_difference"]),
            "details": f"Matched (time_diff={best_match['time_difference']:.1f}s)",
        }
