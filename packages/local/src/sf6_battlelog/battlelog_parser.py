"""
SF6対戦ログHTMLパーサー

battlelog ページから __NEXT_DATA__ スクリプトタグを抽出して、
対戦ログデータを JSON として取得します。
"""

import json
import re
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)


class BattlelogParser:
    """battlelog ページから対戦データを抽出するパーサー"""

    @staticmethod
    def extract_next_data(html: str) -> dict[str, Any]:
        """
        HTML から __NEXT_DATA__ スクリプトタグを抽出して JSON を返す

        Args:
            html: battlelog ページの HTML

        Returns:
            __NEXT_DATA__ に含まれる JSON データ

        Raises:
            ValueError: __NEXT_DATA__ スクリプトタグが見つからない場合
            json.JSONDecodeError: JSON のパースに失敗した場合
        """
        # __NEXT_DATA__ スクリプトタグを検索
        match = re.search(
            r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )

        if not match:
            raise ValueError("__NEXT_DATA__ script tag not found in HTML")

        json_str = match.group(1)
        logger.debug(f"Extracted JSON: {len(json_str)} chars")

        # JSON をパース
        try:
            data = json.loads(json_str)
            logger.debug(f"Successfully parsed JSON with keys: {list(data.keys())}")
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            raise

    @staticmethod
    def get_replay_list(next_data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        __NEXT_DATA__ から対戦ログリストを取得

        Args:
            next_data: __NEXT_DATA__ の JSON オブジェクト

        Returns:
            対戦データの配列

        Raises:
            KeyError: 期待されるキーが存在しない場合
        """
        try:
            replay_list = next_data["props"]["pageProps"]["replay_list"]
            logger.info(f"Found {len(replay_list)} replays")
            return replay_list
        except KeyError as e:
            logger.error(f"Failed to extract replay_list: {e}")
            raise

    @staticmethod
    def get_pagination_info(next_data: dict[str, Any]) -> dict[str, int]:
        """
        __NEXT_DATA__ からページング情報を取得

        Args:
            next_data: __NEXT_DATA__ の JSON オブジェクト

        Returns:
            current_page と total_page を含む辞書
        """
        try:
            page_props = next_data["props"]["pageProps"]
            return {
                "current_page": page_props["current_page"],
                "total_page": page_props["total_page"],
            }
        except KeyError as e:
            logger.error(f"Failed to extract pagination info: {e}")
            raise

    @staticmethod
    def get_fighter_info(next_data: dict[str, Any]) -> dict[str, Any]:
        """
        __NEXT_DATA__ からプレイヤー情報を取得

        Args:
            next_data: __NEXT_DATA__ の JSON オブジェクト

        Returns:
            プレイヤー情報（fighter_banner_info）
        """
        try:
            fighter_info = next_data["props"]["pageProps"]["fighter_banner_info"]
            logger.debug(
                f"Fighter info: {fighter_info['personal_info']['fighter_id']}"
            )
            return fighter_info
        except KeyError as e:
            logger.error(f"Failed to extract fighter info: {e}")
            raise
