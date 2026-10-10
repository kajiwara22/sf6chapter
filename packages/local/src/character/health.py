"""キャラクター別の最大体力の読み込み（ADR-050）

体力ゲージは％のみを記録し、実数値は `schema/character_health.json` から計算する。
表に無いキャラクターは既定値を使い、警告ログを出す（新キャラクター追加時の更新漏れ検知）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..utils.logger import get_logger

logger = get_logger()

# 既定の最大体力（表が見つからない場合のフォールバック）
FALLBACK_MAX_HEALTH = 10000


class CharacterHealthTable:
    """キャラクター別最大体力のテーブル"""

    def __init__(self, characters: dict[str, int], default: int = FALLBACK_MAX_HEALTH):
        self.characters = {str(key).upper(): int(value) for key, value in characters.items()}
        self.default = int(default)

    def max_health(self, character: str | None, warn: bool = False) -> int:
        """キャラクターの最大体力を返す（未知の場合は既定値）"""
        if not character:
            return self.default
        key = str(character).upper()
        if key in self.characters:
            return self.characters[key]
        if warn:
            logger.warning(
                "[Health] 最大体力表に未登録のキャラクターです: %s（既定 %d を使用。schema/character_health.json を更新してください）",
                character,
                self.default,
            )
        return self.default

    def warn_unknown(self, characters: set[str]) -> list[str]:
        """未登録キャラクターをまとめて警告し、その一覧を返す"""
        unknown = sorted({c for c in characters if c and str(c).upper() not in self.characters})
        for character in unknown:
            self.max_health(character, warn=True)
        return unknown


def default_health_path(app_root: Path) -> Path:
    """リポジトリ内の既定パス（packages/local/../../schema/character_health.json）"""
    return Path(app_root).parent.parent / "schema" / "character_health.json"


@lru_cache(maxsize=4)
def load_character_health(path: str | None = None) -> CharacterHealthTable:
    """最大体力表を読み込む（見つからない場合は既定値のみ）"""
    target = Path(path) if path else None
    if target is None or not target.exists():
        logger.warning("[Health] 最大体力表が見つかりません。既定 %d を使用します: %s", FALLBACK_MAX_HEALTH, target)
        return CharacterHealthTable({}, FALLBACK_MAX_HEALTH)

    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.exception("[Health] 最大体力表の読み込みに失敗しました: %s", target)
        return CharacterHealthTable({}, FALLBACK_MAX_HEALTH)

    table = CharacterHealthTable(data.get("characters", {}), data.get("default", FALLBACK_MAX_HEALTH))
    logger.info(
        "[Health] 最大体力表を読み込みました: %s（個別定義 %d 件・既定 %d）",
        target,
        len(table.characters),
        table.default,
    )
    return table
